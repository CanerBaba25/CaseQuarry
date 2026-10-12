import hashlib
import json
import math
import os
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from sqlalchemy import func, select

from . import audit
from .ingestion import empty_counts
from .models import Custodian, ImportBatch, Original, Source, UploadSession, new_id, now
from .schemas import Reason, UploadInput
from .security import Actor, authorize_case, current_actor, fail, get_db, utc
from .storage import file_hash

router = APIRouter(prefix="/api/v1")


def upload_identity(value):
    original_path = value or "evidence.bin"
    filename = Path(original_path.replace("\\", "/")).name
    if not filename or len(original_path) > 4000 or any(ord(char) < 32 for char in original_path):
        fail(422, "FILENAME_INVALID", "Use a valid filename or source path of at most 4,000 characters.")
    # Client paths are provenance labels; storage always uses server-created hash keys.
    return filename[:500], original_path


def batch_json(batch):
    return {"id": batch.id, "batch_id": batch.id, "job_id": batch.id, "case_id": batch.case_id, "source_id": batch.source_id, "state": batch.state, "counts": {**empty_counts(), **(batch.counts or {})}, "errors": batch.errors, "file_count": len(batch.files), "files": [{key: file[key] for key in ("filename", "byte_size", "sha256") if key in file} for file in batch.files], "checkpoint": {key: value for key, value in batch.checkpoint.items() if key != "lease_owner"}, "created_at": utc(batch.created_at).isoformat(), "updated_at": utc(batch.updated_at).isoformat(), "parser_version": batch.parser_version}


def get_batch(db, user, case_id, batch_id, permission="view"):
    authorize_case(db, user, case_id, permission)
    batch = db.scalar(select(ImportBatch).where(ImportBatch.id == batch_id, ImportBatch.case_id == case_id, ImportBatch.tenant_id == user.tenant_id))
    if not batch:
        fail(404, "NOT_FOUND", "This import is unavailable.")
    return batch


def ensure_source(db, user, case_id, source_id=None, source_label="Uploaded evidence", custodian_name=None):
    if source_id:
        source = db.scalar(select(Source).where(Source.id == source_id, Source.case_id == case_id, Source.tenant_id == user.tenant_id))
        if not source:
            fail(404, "NOT_FOUND", "This source is unavailable.")
        return source
    custodian = None
    if custodian_name:
        if len(custodian_name) > 200:
            fail(422, "CUSTODIAN_INVALID", "Custodian names must be at most 200 characters.")
        custodian = Custodian(tenant_id=user.tenant_id, case_id=case_id, display_name=custodian_name)
        db.add(custodian)
        db.flush()
    source = Source(tenant_id=user.tenant_id, case_id=case_id, label=(source_label or "Uploaded evidence")[:200], custodian_id=custodian.id if custodian else None, kind="file-upload", operator_id=user.id)
    db.add(source)
    db.flush()
    return source


def enqueue(db, user, case_id, source, files, request_id, idempotency_key=None):
    batch = ImportBatch(tenant_id=user.tenant_id, case_id=case_id, source_id=source.id, submitted_by=user.id, counts=empty_counts(), files=files, checkpoint={"file_index": 0, "mbox_offset": 0, "policy_version": "rbac-v1"}, idempotency_key=idempotency_key, parser_version="extract-local-v2")
    db.add(batch)
    db.flush()
    audit.record(db, user, case_id, "import.submitted", "import", batch.id, {"file_count": len(files), "source_id": source.id}, request_id)
    db.commit()
    return batch


def original_storage_delta(db, tenant_id, case_id, value, size):
    existing = db.scalar(select(Original.id).where(Original.tenant_id == tenant_id, Original.case_id == case_id, Original.sha256 == value, Original.byte_size == size))
    return 0 if existing else size


@router.get("/cases/{case_id}/imports/adapters")
def adapters(case_id: str, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    from .ocr import availability

    authorize_case(db, actor.user, case_id)
    settings = request.app.state.settings
    items = []
    for identifier, formats, pdf in [("pdf-ocr", ["pdf"], True), ("image-ocr", ["jpg", "jpeg", "png", "tif", "tiff"], False)]:
        status, detail = availability(settings, pdf=pdf)
        items.append({"id": identifier, "formats": formats, "status": status, "engine": "tesseract" if not pdf else "pypdfium2+tesseract", "detail": detail, "limits": {"max_pages": settings.ocr_max_pages if pdf else 1, "max_pixels": settings.ocr_max_pixels, "timeout_seconds_per_page": settings.ocr_timeout_seconds, "language": settings.ocr_language}})
    items.extend([
        {"id": "pdf-text", "formats": ["pdf"], "status": "available", "engine": "pypdf", "detail": "Native PDF text and page anchors; original bytes are preserved.", "limits": {"max_pages": settings.ocr_max_pages, "max_text_chars": settings.max_extracted_chars}},
        {"id": "msg", "formats": ["msg"], "status": "available", "engine": "isolated-ms-oxmsg+olefile", "detail": "Email MSG bodies, recipients and binary file attachments. RTF-only, embedded messages, external/OLE attachments and other Outlook item classes remain partial or unsupported.", "limits": {"attachments": 200, "attachment_bytes": min(settings.max_archive_expanded_bytes, 64 * 1024 * 1024), "timeout_seconds": 60}},
        {"id": "pst-ost", "formats": ["pst", "ost"], "status": "unsupported", "engine": None, "detail": "No tested local PST/OST adapter is configured. Export authorized EML/MBOX/MSG first; raw originals remain preserved.", "limits": {}},
        {"id": "media", "formats": ["wav", "mp3", "m4a", "mp4", "mov"], "status": "unsupported", "engine": None, "detail": "No tested local speech model/runtime is configured; no transcript is fabricated.", "limits": {}},
    ])
    return {"items": items, "connectors": [{"id": identifier, "mode": "cli", "read_only": True, "requires_explicit_scope": True, "status": "available"} for identifier in ("local-folder", "maildir", "imap")], "remote_oauth_connectors": "not-configured"}


@router.get("/cases/{case_id}/imports")
def imports(case_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    rows = db.scalars(select(ImportBatch).where(ImportBatch.case_id == case_id, ImportBatch.tenant_id == actor.user.tenant_id).order_by(ImportBatch.created_at.desc()).limit(200))
    return {"items": [batch_json(batch) for batch in rows]}


@router.post("/cases/{case_id}/imports", status_code=202)
async def submit_import(case_id: str, request: Request, files: list[UploadFile] = File(...), source_id: str | None = Form(None), source_label: str = Form("Uploaded evidence"), custodian_name: str | None = Form(None), source_paths: str | None = Form(None), actor: Actor = Depends(current_actor), db=Depends(get_db)):
    case, _ = authorize_case(db, actor.user, case_id, "import")
    settings, storage = request.app.state.settings, request.app.state.storage
    if not files or len(files) > settings.max_batch_files:
        fail(422, "FILE_COUNT_LIMIT", f"Upload between 1 and {settings.max_batch_files} files per batch.")
    paths = {}
    if source_paths:
        try:
            if len(source_paths) > settings.max_batch_files * 4200:
                raise ValueError
            paths = json.loads(source_paths)
            if not isinstance(paths, dict) or len(paths) > len(files) or set(paths) - {file.filename for file in files}:
                raise ValueError
            for value in paths.values():
                if not isinstance(value, str):
                    raise ValueError
                upload_identity(value)
        except (ValueError, TypeError):
            fail(422, "SOURCE_PATHS_INVALID", "Source paths must map uploaded filenames to bounded provenance labels.")
    idempotency = request.headers.get("idempotency-key")
    if idempotency and len(idempotency) > 100:
        fail(422, "IDEMPOTENCY_KEY_INVALID", "Use an idempotency key of at most 100 characters.")
    if idempotency:
        existing = db.scalar(select(ImportBatch).where(ImportBatch.case_id == case_id, ImportBatch.tenant_id == actor.user.tenant_id, ImportBatch.idempotency_key == idempotency))
        if existing:
            return batch_json(existing)
    source = ensure_source(db, actor.user, case_id, source_id, source_label, custodian_name)
    used = db.scalar(select(func.coalesce(func.sum(Original.byte_size), 0)).where(Original.case_id == case_id, Original.tenant_id == actor.user.tenant_id)) or 0
    uploaded, unique_bytes, seen_hashes = [], 0, set()
    for file in files:
        filename, original_path = upload_identity(file.filename)
        original_path = paths.get(file.filename, original_path)
        temporary = storage.path(f"staging/{new_id()}.upload")
        temporary.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        try:
            with temporary.open("xb") as stream:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        fail(413, "UPLOAD_LIMIT", "This file exceeds its configured upload limit.")
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if not size:
                fail(422, "EMPTY_FILE", "Empty files are not accepted for evidence import.")
            value, byte_size = file_hash(temporary)
            delta = 0 if value in seen_hashes else original_storage_delta(db, actor.user.tenant_id, case_id, value, byte_size)
            if delta and used + unique_bytes + delta > settings.max_case_bytes:
                fail(413, "UPLOAD_LIMIT", "This matter exceeds its configured storage limit.")
            unique_bytes += delta
            seen_hashes.add(value)
            # Publication rechecks the unique-byte quota under the worker's case lock.
            key, value, byte_size = storage.store_file(actor.user.tenant_id, case_id, temporary)
            uploaded.append({"filename": filename, "original_path": original_path, "storage_key": key, "sha256": value, "byte_size": byte_size})
        finally:
            temporary.unlink(missing_ok=True)
            await file.close()
    case.updated_at = now()
    batch = enqueue(db, actor.user, case_id, source, uploaded, request.state.request_id, idempotency)
    return batch_json(batch)


@router.get("/cases/{case_id}/imports/{batch_id}")
def import_status(case_id: str, batch_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    return batch_json(get_batch(db, actor.user, case_id, batch_id))


@router.get("/cases/{case_id}/imports/{batch_id}/errors")
def import_errors(case_id: str, batch_id: str, limit: int = Query(100, ge=1, le=200), actor: Actor = Depends(current_actor), db=Depends(get_db)):
    batch = get_batch(db, actor.user, case_id, batch_id)
    return {"items": batch.errors[:limit], "truncated": len(batch.errors) > limit, "total": sum(batch.counts.get(key, 0) for key in ("failed", "unsupported", "partial", "locked", "quarantined"))}


def transition_import(db, actor, case_id, batch_id, action, request, reason=None):
    batch = get_batch(db, actor.user, case_id, batch_id, "import")
    transitions = {"pause": ({"pending", "running"}, "paused"), "resume": ({"paused"}, "pending"), "retry": ({"failed", "partial"}, "pending"), "cancel": ({"pending", "running", "paused", "failed"}, "cancelled")}
    valid, state = transitions[action]
    if batch.state not in valid:
        fail(409, "IMPORT_STATE_CONFLICT", "This action is not allowed in the current import state.")
    batch.state, batch.lease_until = state, None
    if action == "retry":
        unpublished = int(batch.checkpoint.get("unpublished_quota_count", 0))
        if unpublished:
            batch.counts = {**batch.counts, "discovered": max(0, batch.counts.get("discovered", 0) - unpublished), "failed": max(0, batch.counts.get("failed", 0) - unpublished)}
            batch.errors = [entry for entry in batch.errors if entry.get("code") != "CASE_STORAGE_LIMIT"]
        batch.checkpoint = {"file_index": 0, "mbox_offset": 0, "policy_version": "rbac-v1", "reprocess": True, "reprocess_generation": int(batch.checkpoint.get("reprocess_generation", 0)) + 1}
        batch.parser_version = "extract-local-v2"
    batch.updated_at = now()
    audit.record(db, actor.user, case_id, f"import.{action}", "import", batch.id, {"reason": reason} if reason else {}, request.state.request_id)
    db.commit()
    return batch_json(batch)


@router.post("/cases/{case_id}/imports/{batch_id}/pause")
def pause(case_id: str, batch_id: str, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    return transition_import(db, actor, case_id, batch_id, "pause", request)


@router.post("/cases/{case_id}/imports/{batch_id}/resume")
def resume(case_id: str, batch_id: str, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    return transition_import(db, actor, case_id, batch_id, "resume", request)


@router.post("/cases/{case_id}/imports/{batch_id}/retry")
def retry(case_id: str, batch_id: str, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    return transition_import(db, actor, case_id, batch_id, "retry", request)


@router.post("/cases/{case_id}/imports/{batch_id}/cancel")
def cancel(case_id: str, batch_id: str, body: Reason, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    return transition_import(db, actor, case_id, batch_id, "cancel", request, body.reason)


def get_upload(db, actor, case_id, upload_id):
    authorize_case(db, actor.user, case_id, "import")
    upload = db.scalar(select(UploadSession).where(UploadSession.id == upload_id, UploadSession.case_id == case_id, UploadSession.tenant_id == actor.user.tenant_id, UploadSession.user_id == actor.user.id))
    if not upload:
        fail(404, "NOT_FOUND", "This upload session is unavailable.")
    if utc(upload.expires_at) <= now():
        fail(409, "UPLOAD_EXPIRED", "Start a new upload session.")
    return upload


def upload_json(upload):
    return {"id": upload.id, "filename": upload.filename, "byte_size": upload.byte_size, "part_size": upload.part_size, "part_count": math.ceil(upload.byte_size / upload.part_size), "received_parts": sorted(int(part) for part in upload.parts), "state": upload.state, "expires_at": utc(upload.expires_at).isoformat(), "batch_id": upload.batch_id}


@router.post("/cases/{case_id}/upload-sessions", status_code=201)
def begin_upload(case_id: str, body: UploadInput, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    authorize_case(db, actor.user, case_id, "import")
    _filename, original_path = upload_identity(body.filename)
    if body.byte_size > request.app.state.settings.max_upload_bytes:
        fail(413, "UPLOAD_LIMIT", "The file exceeds the configured upload limit.")
    source = ensure_source(db, actor.user, case_id, body.source_id, body.source_label)
    upload = UploadSession(tenant_id=actor.user.tenant_id, case_id=case_id, user_id=actor.user.id, filename=original_path, byte_size=body.byte_size, sha256=body.sha256.lower() if body.sha256 else None, part_size=body.part_size, source_id=source.id, expires_at=now() + timedelta(days=1))
    db.add(upload)
    db.flush()
    audit.record(db, actor.user, case_id, "upload.started", "upload", upload.id, {"byte_size": body.byte_size}, request.state.request_id)
    db.commit()
    return upload_json(upload)


@router.get("/cases/{case_id}/upload-sessions/{upload_id}")
def upload_status(case_id: str, upload_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    return upload_json(get_upload(db, actor, case_id, upload_id))


@router.put("/cases/{case_id}/upload-sessions/{upload_id}/parts/{part}")
async def upload_part(case_id: str, upload_id: str, part: int, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    upload = get_upload(db, actor, case_id, upload_id)
    if upload.state != "open" or part < 0 or part >= math.ceil(upload.byte_size / upload.part_size):
        fail(409, "UPLOAD_PART_INVALID", "This upload part is not valid for the current session.")
    expected_size = min(upload.part_size, upload.byte_size - part * upload.part_size)
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > expected_size:
            fail(413, "UPLOAD_PART_LIMIT", "This upload part exceeds its expected size.")
    if len(content) != expected_size:
        fail(422, "UPLOAD_PART_SIZE", "This upload part does not match its expected size.")
    value = hashlib.sha256(content).hexdigest()
    provided = request.headers.get("x-chunk-sha256")
    if provided and provided.lower() != value:
        fail(422, "UPLOAD_HASH_MISMATCH", "This upload part failed its supplied hash check.")
    existing = upload.parts.get(str(part))
    if existing and existing["sha256"] != value:
        fail(409, "UPLOAD_PART_CONFLICT", "A different part was already accepted at this position.")
    key, _, size = request.app.state.storage.store_bytes(actor.user.tenant_id, case_id, bytes(content), "derived")
    upload.parts = {**upload.parts, str(part): {"storage_key": key, "sha256": value, "byte_size": size}}
    db.commit()
    return upload_json(upload)


@router.post("/cases/{case_id}/upload-sessions/{upload_id}/complete", status_code=202)
def complete_upload(case_id: str, upload_id: str, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    upload = get_upload(db, actor, case_id, upload_id)
    if upload.state == "complete" and upload.batch_id:
        return batch_json(get_batch(db, actor.user, case_id, upload.batch_id))
    count = math.ceil(upload.byte_size / upload.part_size)
    if set(upload.parts) != {str(part) for part in range(count)}:
        fail(409, "UPLOAD_INCOMPLETE", "Some upload parts are missing.")
    storage = request.app.state.storage
    temporary = storage.path(f"staging/{new_id()}.complete")
    temporary.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporary.open("xb") as output:
            for index in range(count):
                part = upload.parts[str(index)]
                path = storage.path(part["storage_key"])
                if file_hash(path) != (part["sha256"], part["byte_size"]):
                    fail(409, "INTEGRITY_FAILED", "An upload part failed integrity verification.")
                with path.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        output.write(chunk)
        value, size = file_hash(temporary)
        if size != upload.byte_size or (upload.sha256 and value != upload.sha256):
            fail(422, "UPLOAD_HASH_MISMATCH", "The assembled file failed its size or hash check.")
        used = db.scalar(select(func.coalesce(func.sum(Original.byte_size), 0)).where(Original.case_id == case_id, Original.tenant_id == actor.user.tenant_id)) or 0
        delta = original_storage_delta(db, actor.user.tenant_id, case_id, value, size)
        if delta and used + delta > request.app.state.settings.max_case_bytes:
            fail(413, "CASE_QUOTA_EXCEEDED", "This matter exceeds its configured storage quota.")
        key, _, _ = storage.store_file(actor.user.tenant_id, case_id, temporary)
        filename, original_path = upload_identity(upload.filename)
        batch = enqueue(db, actor.user, case_id, db.get(Source, upload.source_id), [{"filename": filename, "original_path": original_path, "storage_key": key, "sha256": value, "byte_size": size}], request.state.request_id, f"upload:{upload.id}")
        upload.state, upload.batch_id = "complete", batch.id
        db.commit()
        return batch_json(batch)
    finally:
        temporary.unlink(missing_ok=True)
