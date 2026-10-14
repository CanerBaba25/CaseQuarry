import hashlib
import logging
import secrets
import stat
import subprocess
import threading
import zipfile
from datetime import timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath

from sqlalchemy import delete, func, select, update

from . import audit
from .models import (
    Artifact,
    Case,
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
from .storage import file_hash

LOGGER = logging.getLogger("casequarry.ingestion")
_THREAD_CLAIMS = threading.local()


class LeaseLost(RuntimeError):
    pass


class BatchYield(RuntimeError):
    pass


class ImportClaim(str):
    def __new__(cls, value, owner):
        claim = super().__new__(cls, value)
        claim.lease_owner = owner
        return claim


class LeaseHeartbeat:
    def __init__(self, database, batch_id, owner):
        self.database, self.batch_id, self.owner = database, batch_id, owner
        self.stop, self.lost = threading.Event(), threading.Event()
        self.thread = threading.Thread(target=self.run, name="casequarry-import-lease", daemon=True)

    def run(self):
        while not self.stop.wait(15):
            try:
                with self.database.sessions() as db:
                    changed = db.execute(update(ImportBatch).where(ImportBatch.id == self.batch_id, ImportBatch.state == "running", ImportBatch.checkpoint["lease_owner"].as_string() == self.owner).values(lease_until=now() + timedelta(minutes=2))).rowcount
                    db.commit()
                    if not changed:
                        self.lost.set()
                        return
            except Exception as error:
                LOGGER.warning("import_lease_renewal_failed error_type=%s", type(error).__name__)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=2)


def fence_claim(db, batch):
    owner = db.info.get("lease_owner")
    if owner:
        changed = db.execute(update(ImportBatch).where(ImportBatch.id == batch.id, ImportBatch.state == "running", ImportBatch.checkpoint["lease_owner"].as_string() == owner).values(lease_until=now() + timedelta(minutes=2))).rowcount
        if not changed:
            raise LeaseLost("The import lease belongs to another worker or the job was stopped.")

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


class CaseStorageLimit(ArchiveError):
    def __init__(self, filename, parent_id=None, used_bytes=0, byte_size=0):
        super().__init__("CASE_STORAGE_LIMIT")
        self.filename, self.parent_id = filename, parent_id
        self.used_bytes, self.byte_size = int(used_bytes), int(byte_size)


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
        "OCR_DISABLED": "Local OCR is disabled by administrator policy. The original is preserved.",
        "OCR_TIMEOUT": "Local recognition reached its page timeout. Inspect and retry this page; the original is preserved.",
        "OCR_PIXEL_LIMIT": "The image exceeds the configured OCR pixel limit. The original is preserved.",
        "EXTRACTION_TIME_LIMIT": "Extraction reached its isolated document time budget. The original is preserved; narrow or split an approved working copy before retrying.",
        "PDF_PAGE_LIMIT": "The PDF exceeds its configured page limit; remaining pages were not extracted.",
        "MSG_BODY_UNSUPPORTED": "Compressed-RTF-only MSG body extraction is unavailable. The original MSG is preserved.",
        "MSG_EMBEDDED_MESSAGE_UNSUPPORTED": "Embedded Outlook message attachments are not decoded by this adapter; the containing original MSG is preserved.",
        "CASE_STORAGE_LIMIT": "The case's unique-original byte quota was reached. This record was not published; increase the approved quota or narrow the import before retrying.",
        "PASSWORD_REQUIRED": "This document is locked. The original is preserved.",
        "ARCHIVE_PASSWORD_REQUIRED": "Archive is encrypted; an approved password adapter is required.",
        "WORKER_PERMISSION_REVOKED": "Import permissions were removed. No further items were processed.",
    }
    return messages.get(
        code,
        "Processing stopped or completed partially. The original is preserved; inspect this item before retrying.",
    )


def set_record_state(batch, item, state, error):
    previous = item.parser_state
    counts = {**empty_counts(), **(batch.counts or {})}
    if previous != state:
        if previous in counts and previous != "stored":
            counts[previous] = max(0, counts[previous] - 1)
        if state in counts and state != "stored":
            counts[state] += 1
    batch.counts = counts
    item.parser_state, item.parser_error = state, error


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


def parse_safely(path, filename, settings):
    """A configured malware scanner runs before any document parser is invoked."""
    scan_status = "not-configured"
    if settings.antivirus_command:
        try:
            scan = subprocess.run([settings.antivirus_command, str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=False)
            if scan.returncode == 1:
                return Parsed("file", filename, state="quarantined", error="MALWARE_DETECTED", metadata={"scan_status": "quarantined"})
            if scan.returncode != 0:
                return Parsed("file", filename, state="partial", error="SCANNER_UNAVAILABLE", metadata={"scan_status": "unavailable"})
            scan_status = "clean"
        except (OSError, subprocess.TimeoutExpired):
            return Parsed("file", filename, state="partial", error="SCANNER_UNAVAILABLE", metadata={"scan_status": "unavailable"})
    parsed = parse_document(path, filename, settings)
    parsed.metadata["scan_status"] = scan_status
    parsed.metadata["parser_version"] = "extract-local-v2"
    return parsed


def append_reprocessing(db, settings, storage, batch, item, parsed, expected_version, attempt):
    fence_claim(db, batch)
    if not assert_active(db, batch):
        raise LeaseLost("The import is no longer active.")
    old_state, old_hash = item.parser_state, item.text_hash
    version = expected_version + 1
    text_hash = hashlib.sha256(parsed.text.encode("utf-8")).hexdigest()
    metadata = {**item.metadata_json, **parsed.metadata, "reprocess_attempt": attempt, "reprocessing_notice": "Extraction changed; verify the current derived text before relying on prior review."}
    if not parsed.error:
        metadata.pop("family_error", None)
    thread_root = (parsed.email.get("references") or [parsed.email.get("in_reply_to") or parsed.email.get("message_id") or ""])[0]
    thread_id = hashlib.sha256(f"{batch.case_id}:{thread_root}".encode()).hexdigest()[:32] if thread_root else None
    changed = db.execute(update(Evidence).where(Evidence.id == item.id, Evidence.case_id == batch.case_id, Evidence.tenant_id == batch.tenant_id, Evidence.text_version == expected_version).values(text=parsed.text, text_hash=text_hash, text_version=version, item_type=parsed.item_type, title=parsed.title[:1000], sender=parsed.sender, recipients=parsed.recipients, email_metadata=parsed.email, metadata_json=metadata, date_raw=parsed.date_raw, date_utc=parsed.date_utc, timezone_source=parsed.timezone_source, parser_state=parsed.state, parser_error=parsed.error, has_attachments=bool(parsed.attachments), thread_id=thread_id, body_fingerprint=hashlib.sha256(" ".join(parsed.text.lower().split()).encode()).hexdigest()).execution_options(synchronize_session=False)).rowcount
    if not changed:
        raise ArchiveError("EXTRACTION_VERSION_CONFLICT")
    db.refresh(item)
    if parsed.text:
        key, digest, _ = storage.store_bytes(batch.tenant_id, batch.case_id, parsed.text.encode("utf-8"), "derived")
        artifact = Artifact(tenant_id=batch.tenant_id, case_id=batch.case_id, evidence_id=item.id, storage_key=key, sha256=digest, version=version, parser_version="extract-local-v2")
        db.add(artifact)
        db.flush()
        for page, start, end in parsed.pages or [(None, start, min(start + 1600, len(parsed.text))) for start in range(0, len(parsed.text), 1600)]:
            if end > start:
                db.add(Span(tenant_id=batch.tenant_id, case_id=batch.case_id, evidence_id=item.id, artifact_id=artifact.id, page=page, char_start=start, char_end=end, text_hash=hashlib.sha256(parsed.text[start:end].encode()).hexdigest()))
    counts = {**empty_counts(), **batch.counts}
    if old_state in counts and old_state != "stored":
        counts[old_state] = max(0, counts[old_state] - 1)
    if parsed.state in counts and parsed.state != "stored":
        counts[parsed.state] += 1
    batch.counts = counts
    batch.errors = [entry for entry in batch.errors if entry.get("evidence_id") != item.id]
    if parsed.error:
        add_error(batch, item.filename, parsed.error, item.id)
    db.execute(delete(Participant).where(Participant.tenant_id == batch.tenant_id, Participant.case_id == batch.case_id, Participant.evidence_id == item.id))
    index_participants(db, item, parsed.email)
    user = db.get(User, batch.submitted_by, populate_existing=True)
    audit.record(db, user, batch.case_id, "evidence.reprocessed", "evidence", item.id, {"old_text_version": expected_version, "text_version": version, "old_text_sha256": old_hash, "text_sha256": text_hash, "state": parsed.state})
    db.commit()
    db.info["tick_processed"] = db.info.get("tick_processed", 0) + 1


def put_record(db, settings, storage, batch, path, filename, record_key, parent_id=None, source_offset="", original_path=None):
    key = hashlib.sha256(f"{batch.id}:{record_key}".encode()).hexdigest()
    existing = db.scalar(
        select(Occurrence).where(Occurrence.case_id == batch.case_id, Occurrence.occurrence_key == key)
    )
    if existing:
        item = db.scalar(select(Evidence).where(Evidence.occurrence_id == existing.id))
        if item.parser_state == "quarantined":
            return item, Parsed(item.item_type, item.title, state="quarantined", error=item.parser_error)
        original = db.get(Original, item.original_id)
        if not storage.verify(original)["valid"] or file_hash(path) != (original.sha256, original.byte_size):
            raise ArchiveError("INTEGRITY_FAILED")
        generation = int(batch.checkpoint.get("reprocess_generation", 0))
        attempt = f"{batch.id}/{generation}"
        reprocess = bool(batch.checkpoint.get("reprocess")) and item.parser_state in {"partial", "failed", "unsupported"} and item.metadata_json.get("reprocess_attempt") != attempt
        expected_version = item.text_version
        db.commit()
        parsed = parse_safely(path, filename, settings)
        if not assert_active(db, batch):
            raise LeaseLost("The import is no longer active.")
        if reprocess:
            append_reprocessing(db, settings, storage, batch, item, parsed, expected_version, attempt)
        return item, parsed
    user = db.get(User, batch.submitted_by)
    authorize_case(db, user, batch.case_id, "import")
    storage_key, digest, byte_size = storage.store_file(batch.tenant_id, batch.case_id, path)
    # Release the read transaction before slow parsers/OCR; acquire a fenced writer only afterward.
    db.commit()
    parsed = parse_safely(storage.path(storage_key), filename, settings)
    fence_claim(db, batch)
    if not assert_active(db, batch):
        raise LeaseLost("The import is no longer active.")
    user = db.get(User, batch.submitted_by, populate_existing=True)
    authorize_case(db, user, batch.case_id, "import")
    # Serialize quota and exact-dedup publication across distinct batches/workers.
    # A real row write gives SQLite a writer lock and PostgreSQL a case-row lock.
    case_locked = db.execute(update(Case).where(Case.id == batch.case_id, Case.tenant_id == batch.tenant_id).values(updated_at=Case.updated_at).execution_options(synchronize_session=False)).rowcount
    if case_locked != 1:
        raise PermissionError("WORKER_PERMISSION_REVOKED")
    original = db.scalar(
        select(Original).where(
            Original.tenant_id == batch.tenant_id,
            Original.case_id == batch.case_id,
            Original.sha256 == digest,
        )
    )
    duplicate = original is not None
    if original is None:
        used = db.scalar(select(func.coalesce(func.sum(Original.byte_size), 0)).where(Original.case_id == batch.case_id, Original.tenant_id == batch.tenant_id)) or 0
        if used + byte_size > settings.max_case_bytes:
            raise CaseStorageLimit(filename, parent_id, used, byte_size)
        original = Original(
            tenant_id=batch.tenant_id,
            case_id=batch.case_id,
            sha256=digest,
            byte_size=byte_size,
            storage_key=storage_key,
        )
        db.add(original)
        db.flush()
    occurrence = Occurrence(
        tenant_id=batch.tenant_id,
        case_id=batch.case_id,
        original_id=original.id,
        source_id=batch.source_id,
        batch_id=batch.id,
        original_name=filename[:500],
        original_path=original_path if original_path is not None else filename,
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
            parser_version="extract-local-v2",
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
    db.info["tick_processed"] = db.info.get("tick_processed", 0) + 1
    return item, parsed


def assert_active(db, batch):
    stop = db.info.get("stop_event")
    if stop is not None and stop.is_set():
        raise BatchYield("Worker shutdown requested.")
    lost = db.info.get("lease_lost")
    if lost is not None and lost.is_set():
        raise LeaseLost("The import lease was lost.")
    db.refresh(batch)
    owner = db.info.get("lease_owner")
    if owner and batch.checkpoint.get("lease_owner") != owner:
        raise LeaseLost("The import lease belongs to another worker.")
    if batch.state not in {"running", "pending"}:
        return False
    user = db.get(User, batch.submitted_by, populate_existing=True)
    if user is None or not user.active or user.tenant_id != batch.tenant_id:
        raise PermissionError("WORKER_PERMISSION_REVOKED")
    try:
        authorize_case(db, user, batch.case_id, "import")
    except Exception as error:
        raise PermissionError("WORKER_PERMISSION_REVOKED") from error
    return True


def ingest_tree(
    db, settings, storage, batch, path, filename, record_key, parent_id=None, depth=0, budget=None,
    *, original_path=None, source_offset=""
):
    if not assert_active(db, batch):
        return None
    budget = budget if budget is not None else {"entries": 0, "bytes": 0}
    quota = budget.get("quota")
    if quota and quota["remaining"] == 0:
        raise BatchYield("The import tick reached its record quota.")
    processed_before = db.info.get("tick_processed", 0)
    item, parsed = put_record(db, settings, storage, batch, path, filename, record_key, parent_id, source_offset, original_path)
    if quota and quota["remaining"] is not None:
        quota["remaining"] -= db.info.get("tick_processed", 0) - processed_before
    if parsed.state in {"quarantined", "failed", "locked"} or parsed.error == "SCANNER_UNAVAILABLE":
        return item
    if depth >= settings.max_archive_depth and (parsed.attachments or filename.lower().endswith(".zip")):
        add_error(batch, filename, "NESTING_LIMIT", item.id)
        set_record_state(batch, item, "partial", "NESTING_LIMIT")
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
        except (CaseStorageLimit, BatchYield, LeaseLost):
            raise
        except (ArchiveError, zipfile.BadZipFile, RuntimeError) as error:
            code = str(error) if isinstance(error, ArchiveError) else "ARCHIVE_PARSE_FAILED"
            set_record_state(batch, item, "quarantined", code)
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
            set_record_state(batch, item, "partial", "ATTACHMENT_SIZE_LIMIT")
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


def run_batch(database, settings, storage, batch_id, max_records=None, lease_owner=None, stop_event=None):
    local_claims = getattr(_THREAD_CLAIMS, "claims", {})
    claim_key = (id(database), str(batch_id))
    owner = lease_owner or getattr(batch_id, "lease_owner", None) or local_claims.get(claim_key)
    if local_claims.get(claim_key) == owner:
        local_claims.pop(claim_key, None)
    if not owner:
        claim = claim_import(database, batch_id=str(batch_id), remember=False)
        if claim is None:
            return
        owner = claim.lease_owner
    with LeaseHeartbeat(database, str(batch_id), owner) as heartbeat:
        _run_batch_owned(database, settings, storage, str(batch_id), owner, heartbeat, max_records, stop_event)


def _run_batch_owned(database, settings, storage, batch_id, owner, heartbeat, max_records, stop_event):
    with database.sessions() as db:
        db.info.update(lease_owner=owner, lease_lost=heartbeat.lost, stop_event=stop_event)
        quota = {"remaining": max_records}
        batch = db.get(ImportBatch, batch_id)
        if batch is None:
            return
        try:
            if not assert_active(db, batch):
                return
            fence_claim(db, batch)
            batch.state, batch.lease_until = "running", now() + timedelta(minutes=2)
            db.commit()
            start_index = int((batch.checkpoint or {}).get("file_index", 0))
            for index in range(start_index, len(batch.files)):
                if not assert_active(db, batch):
                    return
                file = batch.files[index]
                path = storage.path(file["storage_key"])
                name = file["filename"]
                parent = ingest_tree(db, settings, storage, batch, path, name, f"file/{index}", budget={"entries": 0, "bytes": 0, "quota": quota}, original_path=file.get("original_path", name))
                if parent is None:
                    return
                if name.lower().endswith(".mbox") and parent.parser_state not in {"quarantined", "failed", "locked"} and parent.parser_error != "SCANNER_UNAVAILABLE":
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
                            budget={"entries": 0, "bytes": 0, "quota": quota},
                            source_offset=str(source_offset),
                        )
                        batch.checkpoint = {
                            **batch.checkpoint,
                            "file_index": index,
                            "mbox_offset": next_offset,
                            "policy_version": "rbac-v1",
                        }
                        db.commit()
                batch.checkpoint = {**batch.checkpoint, "file_index": index + 1, "mbox_offset": 0, "policy_version": "rbac-v1"}
                db.commit()
            if not assert_active(db, batch):
                return
            fence_claim(db, batch)
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
        except (BatchYield, LeaseLost) as error:
            db.rollback()
            batch = db.get(ImportBatch, batch_id, populate_existing=True)
            if isinstance(error, BatchYield) and batch and batch.state == "running" and batch.checkpoint.get("lease_owner") == owner:
                fence_claim(db, batch)
                batch.state, batch.lease_until, batch.updated_at = "pending", None, now()
                db.commit()
        except Exception as error:
            db.rollback()
            batch = db.get(ImportBatch, batch_id, populate_existing=True)
            if batch and batch.state == "running" and batch.checkpoint.get("lease_owner") == owner:
                fence_claim(db, batch)
                batch.state, batch.lease_until = "failed", None
                if isinstance(error, CaseStorageLimit):
                    counts = {**empty_counts(), **batch.counts}
                    counts["discovered"] += 1
                    counts["failed"] += 1
                    if error.parent_id:
                        parent = db.scalar(select(Evidence).where(Evidence.id == error.parent_id, Evidence.case_id == batch.case_id, Evidence.tenant_id == batch.tenant_id))
                        if parent and parent.parser_state != "partial":
                            if parent.parser_state in counts and parent.parser_state != "stored":
                                counts[parent.parser_state] = max(0, counts[parent.parser_state] - 1)
                            counts["partial"] += 1
                            parent.parser_state, parent.parser_error = "partial", "CASE_STORAGE_LIMIT"
                            parent.metadata_json = {**parent.metadata_json, "family_error": "CASE_STORAGE_LIMIT"}
                    batch.counts = counts
                    batch.checkpoint = {**batch.checkpoint, "unpublished_quota_count": int(batch.checkpoint.get("unpublished_quota_count", 0)) + 1}
                    if counts["stored"]:
                        batch.state = "partial"
                    user = db.get(User, batch.submitted_by, populate_existing=True)
                    audit.record(db, user, batch.case_id, "import.quota_blocked", "import", batch.id, {"filename": error.filename, "parent_id": error.parent_id, "limit_bytes": settings.max_case_bytes, "used_bytes": error.used_bytes, "candidate_bytes": error.byte_size})
                code = (
                    str(error)
                    if isinstance(error, (ArchiveError, PermissionError))
                    else f"IMPORT_FAILED:{type(error).__name__}"
                )
                add_error(batch, error.filename if isinstance(error, CaseStorageLimit) else "import", code, error.parent_id if isinstance(error, CaseStorageLimit) else None)
                db.commit()


def claim_import(database, batch_id=None, remember=True):
    with database.sessions() as db:
        candidates = (
            select(ImportBatch)
            .where(
                (ImportBatch.state == "pending")
                | ((ImportBatch.state == "running") & (ImportBatch.lease_until < now()))
            )
            .order_by(ImportBatch.updated_at, ImportBatch.created_at, ImportBatch.id)
            .limit(1)
        )
        if batch_id:
            candidates = candidates.where(ImportBatch.id == batch_id)
        candidate = db.scalar(candidates)
        if not candidate:
            return None
        owner = secrets.token_hex(24)
        changed = db.execute(
            update(ImportBatch)
            .where(
                ImportBatch.id == candidate.id,
                (ImportBatch.state == "pending")
                | ((ImportBatch.state == "running") & (ImportBatch.lease_until < now())),
            )
            .values(state="running", lease_until=now() + timedelta(minutes=2), checkpoint={**candidate.checkpoint, "lease_owner": owner})
            .execution_options(synchronize_session=False)
        ).rowcount
        db.commit()
        if changed:
            if remember:
                if not hasattr(_THREAD_CLAIMS, "claims"):
                    _THREAD_CLAIMS.claims = {}
                _THREAD_CLAIMS.claims[(id(database), candidate.id)] = owner
            return ImportClaim(candidate.id, owner)
        return None
