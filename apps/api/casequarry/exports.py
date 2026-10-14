"""Permissioned, snapshot-based evidence exports with source and package verification."""

import csv
import hashlib
import json
import re
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session, load_only

from . import audit
from .manifest_signing import (
    SIGNATURE_NAME,
    SigningKeyError,
    load_private_signing_key,
    sign_manifest,
    signing_metadata,
)
from .models import Evidence, Export, Occurrence, Original, ReviewSet, ReviewSetItem, Source, User, now
from .schemas import ExportInput
from .search import search_conditions
from .security import Actor, authorize_case, current_actor, fail, get_db, utc
from .storage import file_hash

router = APIRouter(prefix="/api/v1")
MAX_EXPORT_ITEMS = 20_000
METADATA_FIELDS = (
    "evidence_id", "type", "title", "filename", "source_id", "custodian_id", "occurrence_id", "parent_id",
    "date_raw", "date_utc", "timezone_source", "sender", "recipients", "tags", "review_status",
    "privilege_status", "review_version", "parser_state", "sha256", "byte_size",
)


def canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def export_json(job: Export):
    counts = {key: value for key, value in job.counts.items() if key != "manifest_storage_key"}
    if job.state == "completed":
        counts.setdefault("manifest_signing", signing_metadata(None))
    return {
        "id": job.id, "job_id": job.id, "case_id": job.case_id, "format": job.format, "state": job.state,
        "counts": counts, "sha256": job.sha256, "byte_size": job.byte_size,
        "created_at": utc(job.created_at).isoformat(), "requested_by": job.requested_by,
        "download_url": f"/api/v1/cases/{job.case_id}/exports/{job.id}/download" if job.state == "completed" else None,
        "manifest_url": f"/api/v1/cases/{job.case_id}/exports/{job.id}/manifest" if job.state == "completed" else None,
        "error_code": counts.get("error_code"), "error": counts.get("error"),
    }


def _get_export(db, user, case_id, export_id):
    authorize_case(db, user, case_id, "export")
    job = db.scalar(select(Export).where(Export.id == export_id, Export.tenant_id == user.tenant_id, Export.case_id == case_id))
    if job is None:
        fail(404, "NOT_FOUND", "The export is unavailable.")
    return job


def _select_ids(db, user, case_id, body: ExportInput):
    if sum(value is not None for value in (body.query_spec, body.evidence_ids, body.review_set_id)) > 1:
        fail(422, "EXPORT_SCOPE_INVALID", "Choose one search, review set, or evidence selection.")
    if body.evidence_ids is not None:
        ids = sorted(set(body.evidence_ids))
        scope = {"kind": "selection"}
    elif body.review_set_id is not None:
        review_set = db.scalar(select(ReviewSet).where(ReviewSet.id == body.review_set_id, ReviewSet.tenant_id == user.tenant_id, ReviewSet.case_id == case_id))
        if review_set is None:
            fail(404, "NOT_FOUND", "The review set is unavailable.")
        ids = list(db.scalars(select(ReviewSetItem.evidence_id).where(ReviewSetItem.set_id == review_set.id, ReviewSetItem.tenant_id == user.tenant_id, ReviewSetItem.case_id == case_id).order_by(ReviewSetItem.evidence_id).limit(MAX_EXPORT_ITEMS + 1)))
        scope = {"kind": "review_set", "review_set_id": review_set.id}
    else:
        from .schemas import SearchInput

        spec = body.query_spec or SearchInput()
        if spec.cursor:
            fail(422, "EXPORT_SCOPE_INVALID", "Export a query scope without a pagination cursor.")
        ids = list(db.scalars(select(Evidence.id).where(*search_conditions(user.tenant_id, case_id, spec)).order_by(Evidence.id).limit(MAX_EXPORT_ITEMS + 1)))
        scope = {"kind": "query", "query_spec": spec.model_dump(exclude={"cursor", "page_size"})}
    if not ids:
        fail(422, "EXPORT_EMPTY", "Select at least one evidence item for export.")
    if len(ids) > MAX_EXPORT_ITEMS:
        fail(413, "EXPORT_SCOPE_TOO_LARGE", "This release exports up to 20,000 items per job. Refine the scope.")
    return ids, scope


def _rows(db, tenant_id, case_id, ids):
    fields = (
        Evidence.id, Evidence.tenant_id, Evidence.case_id, Evidence.original_id, Evidence.occurrence_id,
        Evidence.source_id, Evidence.custodian_id, Evidence.parent_id, Evidence.item_type, Evidence.title,
        Evidence.filename, Evidence.date_raw, Evidence.date_utc, Evidence.timezone_source, Evidence.sender,
        Evidence.recipients, Evidence.tags, Evidence.review_status, Evidence.privilege_status, Evidence.review_version,
        Evidence.parser_state,
    )
    query = (
        select(Evidence, Original, Occurrence, Source)
        .options(load_only(*fields))
        .join(Original, Evidence.original_id == Original.id)
        .join(Occurrence, Evidence.occurrence_id == Occurrence.id)
        .join(Source, Evidence.source_id == Source.id)
        .where(
            Evidence.tenant_id == tenant_id, Evidence.case_id == case_id, Evidence.id.in_(ids),
            Original.tenant_id == tenant_id, Original.case_id == case_id,
            Occurrence.tenant_id == tenant_id, Occurrence.case_id == case_id,
            Source.tenant_id == tenant_id, Source.case_id == case_id,
            Occurrence.original_id == Original.id, Occurrence.source_id == Source.id,
        ).order_by(Evidence.id)
    )
    rows = list(db.execute(query))
    if len(rows) != len(ids):
        fail(404, "NOT_FOUND", "One or more selected evidence items are unavailable.")
    return rows


def _snapshot(item, original):
    return {
        "version": item.review_version, "review_status": item.review_status, "privilege_status": item.privilege_status,
        "original_id": original.id, "sha256": original.sha256, "storage_key": original.storage_key, "parent_id": item.parent_id,
        "parser_state": item.parser_state,
    }


def _security_rows(db, tenant_id, case_id, ids, format):
    if format != "zip":
        return _rows(db, tenant_id, case_id, ids)
    seen, frontier = set(ids), set(ids)
    while frontier:
        descendants = set(db.scalars(select(Evidence.id).where(Evidence.tenant_id == tenant_id, Evidence.case_id == case_id, Evidence.parent_id.in_(frontier)))) - seen
        seen.update(descendants)
        if len(seen) > MAX_EXPORT_ITEMS:
            fail(413, "EXPORT_FAMILY_TOO_LARGE", "Contained evidence families exceed the 20,000-item verification limit.")
        frontier = descendants
    return _rows(db, tenant_id, case_id, sorted(seen))


def _validate_job(db, job, storage):
    rows = _rows(db, job.tenant_id, job.case_id, job.evidence_ids)
    security_rows = _security_rows(db, job.tenant_id, job.case_id, job.evidence_ids, job.format) if job.format == "zip" else rows
    if set(job.reviews_snapshot) != {item.id for item, _original, _occurrence, _source in security_rows}:
        fail(409, "EXPORT_FAMILY_CHANGED", "The contained evidence family changed. Request a new export.")
    _check_items(security_rows, job.format, storage, job.reviews_snapshot)
    return rows


def _check_items(rows, format, storage, snapshot=None):
    verified = set()
    for item, original, _occurrence, _source in rows:
        if item.privilege_status in {"suspected", "confirmed"}:
            fail(409, "PRIVILEGE_HOLDBACK", "Privilege review must clear restricted evidence before export.")
        if format == "zip" and item.review_status not in {"responsive", "non_responsive"}:
            fail(409, "REVIEW_REQUIRED", "Native export requires a completed human review for every included item.")
        if format == "zip" and item.parser_state == "quarantined":
            fail(409, "EVIDENCE_QUARANTINED", "Quarantined evidence cannot be included in a native export.")
        if snapshot is not None and snapshot.get(item.id) != _snapshot(item, original):
            fail(409, "EXPORT_SNAPSHOT_CHANGED", "Evidence review or source state changed. Request a new export.")
        if original.id not in verified:
            if not storage.verify(original)["valid"]:
                fail(409, "INTEGRITY_FAILED", "Original evidence failed verification. Export is blocked.")
            verified.add(original.id)


def _requester(db, job):
    user = db.scalar(select(User).where(User.id == job.requested_by, User.tenant_id == job.tenant_id))
    if user is None or not user.active:
        fail(403, "EXPORT_PERMISSION_REVOKED", "The export requester is no longer authorized.")
    authorize_case(db, user, job.case_id, "export")
    return user


def _metadata(item, original):
    return {
        "evidence_id": item.id, "type": item.item_type, "title": item.title, "filename": item.filename,
        "source_id": item.source_id, "custodian_id": item.custodian_id, "occurrence_id": item.occurrence_id,
        "parent_id": item.parent_id, "date_raw": item.date_raw,
        "date_utc": utc(item.date_utc).isoformat() if item.date_utc else None,
        "timezone_source": item.timezone_source, "sender": item.sender,
        "recipients": [value.strip() for value in item.recipients.split(",") if value.strip()],
        "tags": item.tags, "review_status": item.review_status, "privilege_status": item.privilege_status,
        "review_version": item.review_version, "parser_state": item.parser_state, "sha256": original.sha256, "byte_size": original.byte_size,
    }


def _native_name(item):
    name = re.sub(r"[^\w .()-]", "_", re.split(r"[/\\]", item.filename)[-1]).strip(". ")[:160] or "evidence.bin"
    if name.partition(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return f"native/{item.id}/{name}"


def _manifest(job, rows):
    items = []
    selected_ids = set(job.evidence_ids)
    for item, original, occurrence, source in rows:
        entry = {
            **_metadata(item, original), "original_name": occurrence.original_name,
            "original_path": occurrence.original_path, "source_offset": occurrence.source_offset,
            "source_label": source.label, "source_operator_id": source.operator_id,
        }
        if job.format == "zip":
            entry["package_path"] = _native_name(item)
        items.append(entry)
    return {
        "schema_version": "casequarry-hash-manifest-v1", "export_id": job.id, "case_id": job.case_id,
        "created_at": utc(job.created_at).isoformat(), "algorithm": "SHA-256", "item_count": len(items),
        "items": items, "scope": job.counts.get("scope", {}),
        "contained_family_review": [
            {"evidence_id": evidence_id, "parent_id": snapshot["parent_id"], "review_version": snapshot["version"], "review_status": snapshot["review_status"], "privilege_status": snapshot["privilege_status"], "parser_state": snapshot["parser_state"], "sha256": snapshot["sha256"]}
            for evidence_id, snapshot in sorted(job.reviews_snapshot.items()) if evidence_id not in selected_ids
        ],
        "assurance": "Original hashes verified at generation and download; application preservation, without a signed external anchor.",
    }


def _csv_value(value):
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False)
    value = "" if value is None else str(value)
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r")):
        value = "'" + value
    return value


def _write_package(job, rows, storage, destination: Path, manifest_bytes, signature=None):
    if job.format == "json":
        with destination.open("wb") as output:
            output.write(canonical_json({"items": [_metadata(item, original) for item, original, _occurrence, _source in rows], "manifest": json.loads(manifest_bytes), "scope": job.counts.get("scope", {})}))
    elif job.format == "csv":
        with destination.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=METADATA_FIELDS)
            writer.writeheader()
            for item, original, _occurrence, _source in rows:
                writer.writerow({key: _csv_value(value) for key, value in _metadata(item, original).items()})
    else:
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            archive.writestr("manifest.json", manifest_bytes)
            if signature is not None:
                archive.writestr(SIGNATURE_NAME, canonical_json(signature))
            for item, original, _occurrence, _source in rows:
                digest, size = hashlib.sha256(), 0
                with storage.path(original.storage_key).open("rb") as incoming, archive.open(_native_name(item), "w", force_zip64=True) as outgoing:
                    while chunk := incoming.read(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                        outgoing.write(chunk)
                if digest.hexdigest() != original.sha256 or size != original.byte_size:
                    fail(409, "INTEGRITY_FAILED", "Original evidence changed while packaging. Export is blocked.")


def process_pending_exports(database, settings, storage):
    """Claim and process one durable export job; return whether a job was claimed."""
    with database.sessions() as db:
        candidate = db.scalar(select(Export.id).where(Export.state == "pending").order_by(Export.created_at, Export.id).limit(1))
        if candidate is None:
            return False
        claimed = db.execute(update(Export).where(Export.id == candidate, Export.state == "pending").values(state="running").returning(Export.id)).scalar_one_or_none()
        db.commit()
        if claimed is None:
            return False
    with database.sessions() as db:
        job = db.get(Export, claimed)
        try:
            user = _requester(db, job)
            rows = _validate_job(db, job, storage)
            try:
                signing_key = load_private_signing_key(getattr(settings, "export_signing_key_file", None)) if job.format == "zip" else None
            except SigningKeyError:
                fail(503, "EXPORT_SIGNING_KEY_INVALID", "Configured export signing key is invalid or unavailable. No unsigned package was generated.")
            manifest = _manifest(job, rows)
            if signing_key is not None:
                manifest["schema_version"] = "casequarry-hash-manifest-v2"
                manifest["package_files"] = {_native_name(item): {"sha256": original.sha256, "byte_size": original.byte_size} for item, original, _occurrence, _source in rows}
                manifest["assurance"] = "Exact manifest bytes and complete package inventory signed with Ed25519; verification requires an independently trusted public key and does not establish an independent timestamp."
            manifest_bytes = canonical_json(manifest)
            signature = sign_manifest(manifest_bytes, signing_key) if signing_key is not None else None
            temporary = storage.root / "temporary-exports"
            temporary.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=temporary, delete=False) as created:
                path = Path(created.name)
            try:
                _write_package(job, rows, storage, path, manifest_bytes, signature=signature)
                # Start a fresh transaction after potentially lengthy file generation.
                db.rollback()
                job = db.get(Export, claimed)
                user = _requester(db, job)
                rows = _validate_job(db, job, storage)
                key, digest, size = storage.store_file(job.tenant_id, job.case_id, path, kind="exports")
                manifest_key, manifest_hash, _manifest_size = storage.store_bytes(job.tenant_id, job.case_id, manifest_bytes, kind="exports")
            finally:
                path.unlink(missing_ok=True)
            job.storage_key, job.sha256, job.byte_size, job.state = key, digest, size, "completed"
            job.counts = {**job.counts, "processed": len(rows), "failed": 0, "manifest_sha256": manifest_hash, "manifest_storage_key": manifest_key, "completed_at": now().isoformat(), "manifest_signing": signing_metadata(signing_key)}
            audit.record(db, user, job.case_id, "export.completed", "export", job.id, {"format": job.format, "count": len(rows), "sha256": digest})
            db.commit()
        except Exception as error:
            db.rollback()
            job = db.get(Export, claimed)
            details = error.detail if isinstance(error, HTTPException) and isinstance(error.detail, dict) else {}
            code = details.get("error_code", "EXPORT_FAILED")
            message = details.get("message", "The export could not be generated. Review the source integrity and retry with a new export.")
            job.state = "failed"
            job.counts = {**job.counts, "processed": 0, "failed": len(job.evidence_ids), "error_code": code, "error": message}
            user = db.get(User, job.requested_by)
            if user is not None:
                audit.record(db, user, job.case_id, "export.failed", "export", job.id, {"error_code": code})
            db.commit()
    return True


@router.post("/cases/{case_id}/exports", status_code=202)
def request_export(case_id: str, body: ExportInput, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id, "export")
    if not body.confirmed or len(body.reason.strip()) < 3:
        fail(422, "EXPORT_CONFIRMATION_REQUIRED", "Confirm the export and provide its purpose before continuing.")
    ids, scope = _select_ids(db, actor.user, case_id, body)
    rows = _security_rows(db, actor.user.tenant_id, case_id, ids, body.format)
    _check_items(rows, body.format, request.app.state.storage)
    scope["selected_items"] = len(ids)
    scope["contained_family_items"] = len(rows) - len(ids)
    job = Export(
        tenant_id=actor.user.tenant_id, case_id=case_id, requested_by=actor.user.id, format=body.format,
        state="pending", evidence_ids=ids, reason=body.reason.strip(), counts={"requested": len(ids), "processed": 0, "failed": 0, "scope": scope},
        reviews_snapshot={item.id: _snapshot(item, original) for item, original, _occurrence, _source in rows},
    )
    db.add(job)
    db.flush()
    audit.record(db, actor.user, case_id, "export.requested", "export", job.id, {"format": job.format, "count": len(ids)}, getattr(request.state, "request_id", ""))
    db.commit()
    return export_json(job)


@router.get("/cases/{case_id}/exports")
def list_exports(case_id: str, limit: int = 50, cursor: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id, "export")
    if not 1 <= limit <= 200:
        fail(422, "PAGE_SIZE_INVALID", "Choose a page size between 1 and 200.")
    query = select(Export).where(Export.tenant_id == actor.user.tenant_id, Export.case_id == case_id)
    if cursor:
        anchor = _get_export(db, actor.user, case_id, cursor)
        query = query.where(Export.id < anchor.id)
    jobs = list(db.scalars(query.order_by(Export.id.desc()).limit(limit + 1)))
    return {"items": [export_json(job) for job in jobs[:limit]], "next_cursor": jobs[limit - 1].id if len(jobs) > limit else None}


@router.get("/cases/{case_id}/exports/{export_id}")
def get_export(case_id: str, export_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    return export_json(_get_export(db, actor.user, case_id, export_id))


def _verify_download(db, user, case_id, export_id, storage):
    job = _get_export(db, user, case_id, export_id)
    if job.state != "completed":
        fail(409, "EXPORT_NOT_READY", "The export has not completed successfully.")
    _requester(db, job)
    _validate_job(db, job, storage)
    try:
        valid = file_hash(storage.path(job.storage_key)) == (job.sha256, job.byte_size)
        manifest_key = job.counts["manifest_storage_key"]
        manifest_path = storage.path(manifest_key)
        manifest_valid = file_hash(manifest_path)[0] == job.counts["manifest_sha256"]
    except (OSError, KeyError, TypeError):
        valid = manifest_valid = False
    if not valid or not manifest_valid:
        fail(409, "EXPORT_INTEGRITY_FAILED", "The export package or manifest failed integrity verification.")
    return job, manifest_path


@router.get("/cases/{case_id}/exports/{export_id}/download")
def download_export(case_id: str, export_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    storage = request.app.state.storage
    job, _manifest_path = _verify_download(db, actor.user, case_id, export_id, storage)
    audit.record(db, actor.user, case_id, "export.downloaded", "export", job.id, {"sha256": job.sha256, "count": len(job.evidence_ids)}, getattr(request.state, "request_id", ""))
    db.commit()
    types = {"csv": "text/csv; charset=utf-8", "json": "application/json", "zip": "application/zip"}
    return FileResponse(storage.path(job.storage_key), media_type=types[job.format], filename=f"casequarry-{job.id}.{job.format}", headers={"X-Manifest-SHA256": job.counts["manifest_sha256"], "X-Content-SHA256": job.sha256, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/cases/{case_id}/exports/{export_id}/manifest")
def download_manifest(case_id: str, export_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    job, path = _verify_download(db, actor.user, case_id, export_id, request.app.state.storage)
    audit.record(db, actor.user, case_id, "export.manifest_downloaded", "export", job.id, {"sha256": job.counts["manifest_sha256"]}, getattr(request.state, "request_id", ""))
    db.commit()
    return FileResponse(path, media_type="application/json", filename=f"casequarry-{job.id}-manifest.json", headers={"X-Content-SHA256": job.counts["manifest_sha256"], "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
