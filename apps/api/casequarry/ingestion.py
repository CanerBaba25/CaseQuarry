import hashlib
import stat
import subprocess
import zipfile
from datetime import timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath

from sqlalchemy import select, update

from . import audit
from .models import (
    Artifact,
    Evidence,
    ImportBatch,
    Occurrence,
    Original,
    Participant,
    Person,
    Source,
    Span,
    User,
    now,
)
from .parsers import Parsed, parse_document
from .security import authorize_case

COUNTERS = (
    "discovered",
    "accepted",
    "stored",
    "indexed",
    "failed",
    "unsupported",
    "partial",
    "quarantined",
    "locked",
    "duplicates",
)


class ArchiveError(ValueError):
    pass


def empty_counts():
    return dict.fromkeys(COUNTERS, 0)


def safe_zip_entries(archive: zipfile.ZipFile, settings):
    entries = archive.infolist()
    if len(entries) > settings.max_archive_entries:
        raise ArchiveError("ARCHIVE_ENTRY_LIMIT")
    seen, expanded = set(), 0
    for entry in entries:
        normalized = entry.filename.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            "\x00" in normalized
            or path.is_absolute()
            or PureWindowsPath(normalized).drive
            or ".." in path.parts
            or not path.parts
        ):
            raise ArchiveError("ARCHIVE_PATH_UNSAFE")
        if stat.S_ISLNK(entry.external_attr >> 16):
            raise ArchiveError("ARCHIVE_SYMLINK_UNSAFE")
        if normalized.casefold() in seen:
            raise ArchiveError("ARCHIVE_DUPLICATE_PATH")
        seen.add(normalized.casefold())
        if entry.flag_bits & 1:
            raise ArchiveError("ARCHIVE_PASSWORD_REQUIRED")
        expanded += entry.file_size
        if entry.file_size > settings.max_upload_bytes or expanded > settings.max_archive_expanded_bytes:
            raise ArchiveError("ARCHIVE_SIZE_LIMIT")
        if entry.file_size > max(1, entry.compress_size) * settings.max_archive_expansion_ratio:
            raise ArchiveError("ARCHIVE_EXPANSION_LIMIT")
    return [entry for entry in entries if not entry.is_dir()]


def iter_mbox(path: Path, offset: int = 0, max_message_bytes: int = 256 * 1024 * 1024):
    with path.open("rb") as stream:
        stream.seek(offset)
        current, start, size = [], None, 0
        while True:
            position = stream.tell()
            line = stream.readline(max_message_bytes + 1)
            if not line:
                if current:
                    yield start, stream.tell(), b"".join(current)
                break
            if line.startswith(b"From "):
                if current:
                    yield start, position, b"".join(current)
                start, current, size = position, [], 0
                continue
            if start is None:
                start = position
            size += len(line)
            if size > max_message_bytes:
                raise ArchiveError("MBOX_MESSAGE_TOO_LARGE")
            current.append(line)


def add_error(batch, filename, code, evidence_id=None):
    errors = list(batch.errors or [])
    if len(errors) < 1000:
        errors.append(
            {"filename": filename, "code": code, "message": error_message(code), "evidence_id": evidence_id}
        )
    batch.errors = errors


def error_message(code):
    messages = {
        "PARSER_UNAVAILABLE": "No tested parser is configured for this format. The original is preserved.",
        "OCR_REQUIRED": "No readable PDF text was found. OCR is required; the original is preserved.",
        "OCR_DEPENDENCY_MISSING": "Install Tesseract to extract image text. The original is preserved.",
        "PASSWORD_REQUIRED": "This document is locked. The original is preserved.",
        "ARCHIVE_PASSWORD_REQUIRED": "Archive is encrypted; an approved password adapter is required.",
        "WORKER_PERMISSION_REVOKED": "Import permissions were removed. No further items were processed.",
    }
    return messages.get(
        code,
        "Processing stopped or completed partially. The original is preserved; inspect this item before retrying.",
    )


def index_participants(db, item, email):
    if item.item_type != "email" or not email:
        return
    people, participants, seen = {}, [], set()
    for role in ("from", "to", "cc", "bcc", "reply_to"):
        for address in email.get(role, []):
            normalized = str(address.get("email", "")).strip().lower()
            if not normalized or len(normalized) > 320 or (normalized, role) in seen:
                continue
            seen.add((normalized, role))
            person_id = hashlib.sha256(f"{item.case_id}:{normalized}".encode()).hexdigest()[:32]
            people.setdefault(
                person_id,
                {
                    "id": person_id,
                    "tenant_id": item.tenant_id,
                    "case_id": item.case_id,
                    "email": normalized,
                    "name": str(address.get("name", ""))[:200],
                    "state": "header-address",
                },
            )
            participants.append(
                {
                    "tenant_id": item.tenant_id,
                    "case_id": item.case_id,
                    "evidence_id": item.id,
                    "person_id": person_id,
                    "role": role,
                }
            )
    if not participants:
        return
    dialect = db.bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        raise ValueError("Unsupported participant index database")
    # Batches stay bounded even if an individual source contains an unusually large header.
    rows = list(people.values())
    for offset in range(0, len(rows), 200):
        db.execute(
            insert(Person).on_conflict_do_nothing(index_elements=["case_id", "email"]),
            rows[offset : offset + 200],
        )
    for offset in range(0, len(participants), 200):
        db.execute(
            insert(Participant).on_conflict_do_nothing(index_elements=["evidence_id", "person_id", "role"]),
            participants[offset : offset + 200],
        )


def put_record(db, settings, storage, batch, path, filename, record_key, parent_id=None, source_offset=""):
    key = hashlib.sha256(f"{batch.id}:{record_key}".encode()).hexdigest()
    existing = db.scalar(
        select(Occurrence).where(Occurrence.case_id == batch.case_id, Occurrence.occurrence_key == key)
    )
    if existing:
        item = db.scalar(select(Evidence).where(Evidence.occurrence_id == existing.id))
        return item, parse_document(path, filename, settings)
    user = db.get(User, batch.submitted_by)
    authorize_case(db, user, batch.case_id, "import")
    storage_key, digest, byte_size = storage.store_file(batch.tenant_id, batch.case_id, path)
    original = db.scalar(
        select(Original).where(
            Original.tenant_id == batch.tenant_id,
            Original.case_id == batch.case_id,
            Original.sha256 == digest,
        )
    )
    duplicate = original is not None
    if original is None:
        original = Original(
            tenant_id=batch.tenant_id,
            case_id=batch.case_id,
            sha256=digest,
            byte_size=byte_size,
            storage_key=storage_key,
        )
        db.add(original)
        db.flush()
    parsed = parse_document(storage.path(storage_key), filename, settings)
    if settings.antivirus_command:
        try:
            scan = subprocess.run(
                [settings.antivirus_command, str(storage.path(storage_key))],
                capture_output=True,
                timeout=60,
                check=False,
            )
            if scan.returncode == 1:
                parsed = Parsed(parsed.item_type, parsed.title, state="quarantined", error="MALWARE_DETECTED")
            elif scan.returncode != 0:
                parsed = Parsed(parsed.item_type, parsed.title, state="partial", error="SCANNER_UNAVAILABLE")
        except (OSError, subprocess.TimeoutExpired):
            parsed = Parsed(parsed.item_type, parsed.title, state="partial", error="SCANNER_UNAVAILABLE")
    parsed.metadata["scan_status"] = "configured" if settings.antivirus_command else "not-configured"
    occurrence = Occurrence(
        tenant_id=batch.tenant_id,
        case_id=batch.case_id,
        original_id=original.id,
        source_id=batch.source_id,
        batch_id=batch.id,
        original_name=filename[:500],
        original_path=filename,
        source_offset=str(source_offset),
        occurrence_key=key,
    )
    db.add(occurrence)
    db.flush()
    source = db.get(Source, batch.source_id)
    text_hash = hashlib.sha256(parsed.text.encode("utf-8")).hexdigest()
    normalized = " ".join(parsed.text.lower().split())
    thread_root = (
        parsed.email.get("references")
        or [parsed.email.get("in_reply_to") or parsed.email.get("message_id") or ""]
    )[0]
    thread_id = (
        hashlib.sha256(f"{batch.case_id}:{thread_root}".encode()).hexdigest()[:32] if thread_root else None
    )
    item = Evidence(
        tenant_id=batch.tenant_id,
        case_id=batch.case_id,
        original_id=original.id,
        occurrence_id=occurrence.id,
        source_id=batch.source_id,
        custodian_id=source.custodian_id,
        parent_id=parent_id,
        item_type=parsed.item_type,
        title=parsed.title[:1000],
        filename=filename[:500],
        text=parsed.text,
        text_hash=text_hash,
        date_raw=parsed.date_raw,
        date_utc=parsed.date_utc,
        timezone_source=parsed.timezone_source,
        sender=parsed.sender,
        recipients=parsed.recipients,
        email_metadata=parsed.email,
        metadata_json=parsed.metadata,
        has_attachments=bool(parsed.attachments),
        parser_state=parsed.state,
        parser_error=parsed.error,
        thread_id=thread_id,
        body_fingerprint=hashlib.sha256(normalized.encode()).hexdigest(),
    )
    db.add(item)
    db.flush()
    index_participants(db, item, parsed.email)
    if parsed.text:
        artifact_key, artifact_hash, _ = storage.store_bytes(
            batch.tenant_id, batch.case_id, parsed.text.encode("utf-8"), "derived"
        )
        artifact = Artifact(
            tenant_id=batch.tenant_id,
            case_id=batch.case_id,
            evidence_id=item.id,
            storage_key=artifact_key,
            sha256=artifact_hash,
        )
        db.add(artifact)
        db.flush()
        locations = parsed.pages or [
            (None, start, min(start + 1600, len(parsed.text))) for start in range(0, len(parsed.text), 1600)
        ]
        for page, start, end in locations:
            if end > start:
                db.add(
                    Span(
                        tenant_id=batch.tenant_id,
                        case_id=batch.case_id,
                        evidence_id=item.id,
                        artifact_id=artifact.id,
                        page=page,
                        char_start=start,
                        char_end=end,
                        text_hash=hashlib.sha256(parsed.text[start:end].encode()).hexdigest(),
                    )
                )
    counts = {**empty_counts(), **(batch.counts or {})}
    counts["discovered"] += 1
    counts["accepted"] += 1
    counts["stored"] += 1
    if parsed.state in counts and parsed.state != "stored":
        counts[parsed.state] += 1
    if duplicate:
        counts["duplicates"] += 1
    batch.counts = counts
    if parsed.error:
        add_error(batch, filename, parsed.error, item.id)
    batch.updated_at, batch.lease_until = now(), now() + timedelta(minutes=2)
    audit.record(
        db,
        user,
        batch.case_id,
        "evidence.ingested",
        "evidence",
        item.id,
        {
            "original_sha256": digest,
            "source_id": batch.source_id,
            "occurrence_id": occurrence.id,
            "state": parsed.state,
        },
    )
    db.commit()
    return item, parsed


def assert_active(db, batch):
    db.refresh(batch)
    if batch.state not in {"running", "pending"}:
        return False
    user = db.get(User, batch.submitted_by)
    if user is None or not user.active or user.tenant_id != batch.tenant_id:
        raise PermissionError("WORKER_PERMISSION_REVOKED")
    try:
        authorize_case(db, user, batch.case_id, "import")
    except Exception as error:
        raise PermissionError("WORKER_PERMISSION_REVOKED") from error
    return True


def ingest_tree(
    db, settings, storage, batch, path, filename, record_key, parent_id=None, depth=0, budget=None
):
    if not assert_active(db, batch):
        return None
    item, parsed = put_record(db, settings, storage, batch, path, filename, record_key, parent_id)
    if parsed.state in {"quarantined", "failed", "locked"}:
        return item
    budget = budget if budget is not None else {"entries": 0, "bytes": 0}
    if depth >= settings.max_archive_depth and (parsed.attachments or filename.lower().endswith(".zip")):
        add_error(batch, filename, "NESTING_LIMIT", item.id)
        item.parser_state, item.parser_error = "partial", "NESTING_LIMIT"
        db.commit()
        return item
    children = parsed.attachments
    if filename.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as archive:
                entries = safe_zip_entries(archive, settings)
                for index, entry in enumerate(entries):
                    if not assert_active(db, batch):
                        return item
                    budget["entries"] += 1
                    budget["bytes"] += entry.file_size
                    if (
                        budget["entries"] > settings.max_archive_entries
                        or budget["bytes"] > settings.max_archive_expanded_bytes
                    ):
                        raise ArchiveError("ARCHIVE_SIZE_LIMIT")
                    with archive.open(entry) as stream:
                        content = stream.read(settings.max_upload_bytes + 1)
                    if len(content) != entry.file_size or len(content) > settings.max_upload_bytes:
                        raise ArchiveError("ARCHIVE_SIZE_LIMIT")
                    child_key, _, _ = storage.store_bytes(batch.tenant_id, batch.case_id, content)
                    ingest_tree(
                        db,
                        settings,
                        storage,
                        batch,
                        storage.path(child_key),
                        entry.filename,
                        f"{record_key}/zip/{index}",
                        item.id,
                        depth + 1,
                        budget,
                    )
        except (ArchiveError, zipfile.BadZipFile, RuntimeError) as error:
            code = str(error) if isinstance(error, ArchiveError) else "ARCHIVE_PARSE_FAILED"
            item.parser_state, item.parser_error = "quarantined", code
            batch.counts = {**batch.counts, "quarantined": batch.counts.get("quarantined", 0) + 1}
            add_error(batch, filename, code, item.id)
            db.commit()
    for index, (name, data) in enumerate(children):
        if not assert_active(db, batch):
            return item
        budget["entries"] += 1
        budget["bytes"] += len(data)
        if (
            len(data) > settings.max_upload_bytes
            or budget["bytes"] > settings.max_archive_expanded_bytes
            or budget["entries"] > settings.max_archive_entries
        ):
            add_error(batch, name, "ATTACHMENT_SIZE_LIMIT", item.id)
            batch.counts = {**batch.counts, "partial": batch.counts.get("partial", 0) + 1}
            item.parser_state, item.parser_error = "partial", "ATTACHMENT_SIZE_LIMIT"
            db.commit()
            break
        child_key, _, _ = storage.store_bytes(batch.tenant_id, batch.case_id, data)
        ingest_tree(
            db,
            settings,
            storage,
            batch,
            storage.path(child_key),
            name,
            f"{record_key}/attachment/{index}",
            item.id,
            depth + 1,
            budget,
        )
    return item


def run_batch(database, settings, storage, batch_id):
    with database.sessions() as db:
        batch = db.get(ImportBatch, batch_id)
        if batch is None:
            return
        try:
            if not assert_active(db, batch):
                return
            batch.state, batch.lease_until = "running", now() + timedelta(minutes=2)
            db.commit()
            start_index = int((batch.checkpoint or {}).get("file_index", 0))
            for index in range(start_index, len(batch.files)):
                if not assert_active(db, batch):
                    return
                file = batch.files[index]
                path = storage.path(file["storage_key"])
                name = file["filename"]
                parent = ingest_tree(db, settings, storage, batch, path, name, f"file/{index}")
                if parent is None:
                    return
                if name.lower().endswith(".mbox"):
                    offset = int(batch.checkpoint.get("mbox_offset", 0)) if index == start_index else 0
                    for source_offset, next_offset, data in iter_mbox(
                        path, offset, settings.max_upload_bytes
                    ):
                        if not assert_active(db, batch):
                            return
                        message_key, _, _ = storage.store_bytes(batch.tenant_id, batch.case_id, data)
                        ingest_tree(
                            db,
                            settings,
                            storage,
                            batch,
                            storage.path(message_key),
                            f"{Path(name).stem}-{source_offset}.eml",
                            f"file/{index}/mbox/{source_offset}",
                            parent.id,
                        )
                        batch.checkpoint = {
                            "file_index": index,
                            "mbox_offset": next_offset,
                            "policy_version": "rbac-v1",
                        }
                        db.commit()
                batch.checkpoint = {"file_index": index + 1, "mbox_offset": 0, "policy_version": "rbac-v1"}
                db.commit()
            if not assert_active(db, batch):
                return
            batch.state = (
                "partial"
                if any(
                    batch.counts.get(key, 0)
                    for key in ("failed", "unsupported", "partial", "quarantined", "locked")
                )
                else "completed"
            )
            batch.lease_until, batch.updated_at = None, now()
            user = db.get(User, batch.submitted_by)
            audit.record(
                db,
                user,
                batch.case_id,
                "import.completed",
                "import",
                batch.id,
                {"counts": batch.counts, "state": batch.state},
            )
            db.commit()
        except Exception as error:
            db.rollback()
            batch = db.get(ImportBatch, batch_id)
            if batch:
                batch.state, batch.lease_until = "failed", None
                code = (
                    str(error)
                    if isinstance(error, (ArchiveError, PermissionError))
                    else f"IMPORT_FAILED:{type(error).__name__}"
                )
                add_error(batch, "import", code)
                db.commit()


def claim_import(database):
    with database.sessions() as db:
        candidates = (
            select(ImportBatch.id)
            .where(
                (ImportBatch.state == "pending")
                | ((ImportBatch.state == "running") & (ImportBatch.lease_until < now()))
            )
            .order_by(ImportBatch.created_at)
            .limit(1)
        )
        candidate = db.scalar(candidates)
        if not candidate:
            return None
        changed = db.execute(
            update(ImportBatch)
            .where(
                ImportBatch.id == candidate,
                (ImportBatch.state == "pending")
                | ((ImportBatch.state == "running") & (ImportBatch.lease_until < now())),
            )
            .values(state="running", lease_until=now() + timedelta(minutes=2))
        ).rowcount
        db.commit()
        return candidate if changed else None
