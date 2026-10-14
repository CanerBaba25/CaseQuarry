"""Reviewed derived productions with distinct approvals and immutable Bates ranges."""

import csv
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import Field, model_validator
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from . import audit
from .evidence_routes import checked_text
from .exports import _check_items, _rows, _select_ids, _snapshot, canonical_json
from .manifest_signing import (
    SIGNATURE_NAME,
    SigningKeyError,
    load_private_signing_key,
    sign_manifest,
    signing_metadata,
)
from .models import Hold, User, new_id, now
from .production_models import BatesCounter, Production, ProductionItem, Redaction
from .production_render import clean_pdf, clean_pdf_images, stamped_images
from .schemas import ExportInput, Input, Reason, SearchInput
from .security import Actor, authorize_case, current_actor, fail, get_db, utc
from .storage import file_hash

router = APIRouter(prefix="/api/v1")
MAX_ITEMS = 200
MAX_TEXT_BYTES = 2_000_000
MAX_PACKAGE_BYTES = 250_000_000
MAX_JOB_PIXELS = 60_000_000
FIELDS = ("BEGBATES", "ENDBATES", "EVIDENCE_ID", "PARENT_ID", "SOURCE_ID", "ORIGINAL_SHA256", "PRODUCED_SHA256", "PAGE_COUNT", "REDACTED", "DERIVED_PATH", "TEXT_PATH")


class Region(Input):
    page: int = Field(ge=1, le=50)
    x: float = Field(ge=0, lt=1, allow_inf_nan=False)
    y: float = Field(ge=0, lt=1, allow_inf_nan=False)
    width: float = Field(gt=0, le=1, allow_inf_nan=False)
    height: float = Field(gt=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def bounds(self):
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("Regions must stay inside the page.")
        return self


class TextRange(Input):
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def bounds(self):
        if self.end <= self.start:
            raise ValueError("Range end must follow start.")
        return self


class RedactionInput(Reason):
    evidence_id: str
    kind: Literal["pdf", "text"]
    regions: list[Region] = Field(default_factory=list, max_length=200)
    ranges: list[TextRange] = Field(default_factory=list, max_length=200)
    expected_text_version: int | None = Field(default=None, ge=1)


class Confirm(Reason):
    confirmed: bool = False


class ProductionInput(Confirm):
    evidence_ids: list[str] | None = Field(default=None, max_length=MAX_ITEMS)
    review_set_id: str | None = None
    query_spec: SearchInput | None = None
    redactions: dict[str, str] = Field(default_factory=dict, max_length=MAX_ITEMS)
    bates_prefix: str = Field(default="CQ", pattern=r"^[A-Z][A-Z0-9_-]{0,15}$")


def _confirmation(body):
    if not body.confirmed or len(body.reason.strip()) < 3:
        fail(422, "CONFIRMATION_REQUIRED", "Confirm this action and provide a meaningful reason.")


def _item(db, tenant_id, case_id, identifier):
    return _rows(db, tenant_id, case_id, [identifier])[0][:2]


def _scoped(db, model, user, case_id, identifier):
    row = db.scalar(select(model).where(model.id == identifier, model.tenant_id == user.tenant_id, model.case_id == case_id))
    if row is None:
        fail(404, "NOT_FOUND", "The matter item is unavailable.")
    return row


def _person(db, tenant_id, case_id, identifier, permission):
    user = db.scalar(select(User).where(User.id == identifier, User.tenant_id == tenant_id, User.active.is_(True)))
    if user is None:
        fail(403, "APPROVAL_PERMISSION_REVOKED", "A requester or approver is no longer authorized.")
    authorize_case(db, user, case_id, permission)
    return user


def _approver(db, user, case_id, requester):
    _case, member = authorize_case(db, user, case_id, "privilege")
    if requester == user.id or member.role not in {"matter_lead", "attorney"}:
        fail(403, "DISTINCT_APPROVER_REQUIRED", "A different current matter lead or attorney must approve this disclosure.")


def _source_snapshot(db, item, original, storage, text=False):
    snapshot = {**_snapshot(item, original), "text_version": item.text_version, "text_hash": item.text_hash}
    if text:
        if item.parser_state != "indexed" or not item.text.strip() or len(item.text.encode()) > MAX_TEXT_BYTES:
            fail(409, "PRODUCTION_TEXT_UNAVAILABLE", "Production requires complete indexed text of at most two megabytes, or a supported PDF original.")
        artifact = checked_text(db, item, storage)
        if artifact is None or artifact.sha256 != item.text_hash:
            fail(409, "DERIVED_INTEGRITY_FAILED", "A verified immutable extracted-text artifact is required.")
        snapshot.update(artifact_id=artifact.id, artifact_sha256=artifact.sha256)
    if not storage.verify(original)["valid"]:
        fail(409, "INTEGRITY_FAILED", "The original failed verification; disclosure is blocked.")
    return snapshot


def _is_pdf(item, original, storage):
    if original.byte_size > 50_000_000:
        fail(413, "PRODUCTION_SOURCE_LIMIT", "Derived production supports original files up to 50 megabytes each.")
    with storage.path(original.storage_key).open("rb") as stream:
        return stream.read(5) == b"%PDF-"


def _validated_redaction(db, row, storage, *, require_approved=False):
    user = _person(db, row.tenant_id, row.case_id, row.requested_by, "review")
    item, original = _item(db, row.tenant_id, row.case_id, row.evidence_id)
    if _source_snapshot(db, item, original, storage, text=row.kind == "text") != row.snapshot:
        fail(409, "REDACTION_SNAPSHOT_CHANGED", "The source or review changed; create a new redaction.")
    if require_approved:
        if row.state != "approved" or row.approved_by is None:
            fail(409, "REDACTION_APPROVAL_REQUIRED", "Select a redaction approved by a distinct matter lead or attorney.")
        signer = _person(db, row.tenant_id, row.case_id, row.approved_by, "privilege")
        _approver(db, signer, row.case_id, row.requested_by)
    if row.state in {"ready_for_review", "approved"} and not storage.verify(row)["valid"]:
        fail(409, "REDACTION_INTEGRITY_FAILED", "The redacted derivative failed verification.")
    return user, item, original


def redaction_json(row):
    return {"id": row.id, "case_id": row.case_id, "evidence_id": row.evidence_id, "kind": row.kind, "state": row.state, "requested_by": row.requested_by, "approved_by": row.approved_by, "created_at": utc(row.created_at).isoformat(), "approved_at": utc(row.approved_at).isoformat() if row.approved_at else None, "reason": row.reason, "selection": row.selection, "sha256": row.sha256, "byte_size": row.byte_size, "verification": row.verification, "error_code": row.error_code, "error": row.error, "preview_url": f"/api/v1/cases/{row.case_id}/redactions/{row.id}/preview" if row.state in {"ready_for_review", "approved"} else None}


def production_json(row, db=None):
    counts = {key: value for key, value in row.counts.items() if key != "manifest_storage_key"}
    if row.state == "completed":
        counts.setdefault("manifest_signing", signing_metadata(None))
    result = {"id": row.id, "case_id": row.case_id, "state": row.state, "requested_by": row.requested_by, "approved_by": row.approved_by, "approved_at": utc(row.approved_at).isoformat() if row.approved_at else None, "created_at": utc(row.created_at).isoformat(), "bates_prefix": row.bates_prefix, "evidence_ids": row.evidence_ids, "redactions": row.redactions, "reason": row.reason, "counts": counts, "sha256": row.sha256, "byte_size": row.byte_size, "download_url": f"/api/v1/cases/{row.case_id}/productions/{row.id}/download" if row.state == "completed" else None}
    if db is not None:
        ledger = list(db.scalars(select(ProductionItem).where(ProductionItem.production_id == row.id, ProductionItem.tenant_id == row.tenant_id, ProductionItem.case_id == row.case_id).order_by(ProductionItem.start_number)))
        result["items"] = [{"evidence_id": item.evidence_id, "begin_bates": _label(item.prefix, item.start_number), "end_bates": _label(item.prefix, item.end_number), "page_count": item.page_count, "produced_sha256": item.produced_sha256} for item in ledger]
    return result


def _list(db, model, user, case_id, limit, cursor):
    if not 1 <= limit <= 100:
        fail(422, "PAGE_SIZE_INVALID", "Choose a page size between 1 and 100.")
    query = select(model).where(model.tenant_id == user.tenant_id, model.case_id == case_id)
    if cursor:
        _scoped(db, model, user, case_id, cursor)
        query = query.where(model.id > cursor)
    rows = list(db.scalars(query.order_by(model.id).limit(limit + 1)))
    return rows[:limit], rows[limit - 1].id if len(rows) > limit else None


@router.get("/cases/{case_id}/redactions")
def list_redactions(case_id: str, limit: int = 50, cursor: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id, "review")
    rows, cursor = _list(db, Redaction, actor.user, case_id, limit, cursor)
    return {"items": [redaction_json(row) for row in rows], "next_cursor": cursor}


@router.post("/cases/{case_id}/redactions", status_code=202)
def request_redaction(case_id: str, body: RedactionInput, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id, "review")
    if len(body.reason.strip()) < 3:
        fail(422, "REASON_REQUIRED", "Provide a meaningful reason for the redaction.")
    item, original = _item(db, actor.user.tenant_id, case_id, body.evidence_id)
    selection = {"regions": [region.model_dump() for region in body.regions], "ranges": [value.model_dump() for value in body.ranges]}
    if body.kind == "pdf":
        if not body.regions or body.ranges or not _is_pdf(item, original, request.app.state.storage):
            fail(422, "REDACTION_SELECTION_INVALID", "PDF redaction needs normalized page regions and a PDF original.")
    else:
        if not body.ranges or body.regions or body.expected_text_version != item.text_version:
            fail(409, "REDACTION_SELECTION_INVALID", "Text redaction needs ranges and the current extracted-text version.")
        ranges = sorted(body.ranges, key=lambda value: value.start)
        if any(value.end > len(item.text) for value in ranges) or any(left.end > right.start for left, right in zip(ranges, ranges[1:], strict=False)):
            fail(422, "REDACTION_SELECTION_INVALID", "Select non-overlapping ranges inside the extracted text.")
    snapshot = _source_snapshot(db, item, original, request.app.state.storage, text=body.kind == "text")
    row = Redaction(tenant_id=actor.user.tenant_id, case_id=case_id, evidence_id=item.id, requested_by=actor.user.id, kind=body.kind, reason=body.reason.strip(), selection=selection, snapshot=snapshot)
    db.add(row)
    db.flush()
    audit.record(db, actor.user, case_id, "redaction.requested", "redaction", row.id, {"kind": body.kind, "evidence_id": item.id})
    db.commit()
    return redaction_json(row)


@router.get("/cases/{case_id}/redactions/{redaction_id}")
def get_redaction(case_id: str, redaction_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id, "review")
    return redaction_json(_scoped(db, Redaction, actor.user, case_id, redaction_id))


@router.get("/cases/{case_id}/redactions/{redaction_id}/preview")
def preview_redaction(case_id: str, redaction_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id, "review")
    row = _scoped(db, Redaction, actor.user, case_id, redaction_id)
    if row.state not in {"ready_for_review", "approved"}:
        fail(409, "REDACTION_NOT_READY", "The redacted derivative is not ready for human review.")
    _validated_redaction(db, row, request.app.state.storage)
    audit.record(db, actor.user, case_id, "redaction.previewed", "redaction", row.id, {"sha256": row.sha256})
    db.commit()
    extension = "pdf" if row.kind == "pdf" else "txt"
    return FileResponse(request.app.state.storage.path(row.storage_key), filename=f"redacted-{row.id}.{extension}", media_type="application/pdf" if extension == "pdf" else "text/plain; charset=utf-8", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Content-SHA256": row.sha256})


@router.post("/cases/{case_id}/redactions/{redaction_id}/approve")
def approve_redaction(case_id: str, redaction_id: str, body: Confirm, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    _confirmation(body)
    row = _scoped(db, Redaction, actor.user, case_id, redaction_id)
    _approver(db, actor.user, case_id, row.requested_by)
    _validated_redaction(db, row, request.app.state.storage)
    changed = db.execute(update(Redaction).where(Redaction.id == row.id, Redaction.state == "ready_for_review").values(state="approved", approved_by=actor.user.id, approved_at=now())).rowcount
    if not changed:
        fail(409, "REDACTION_TRANSITION_INVALID", "Only an unapproved ready derivative can be approved.")
    audit.record(db, actor.user, case_id, "redaction.approved", "redaction", row.id, {"reason": body.reason.strip(), "sha256": row.sha256})
    db.commit()
    db.refresh(row)
    return redaction_json(row)


@router.post("/cases/{case_id}/redactions/{redaction_id}/reject")
def reject_redaction(case_id: str, redaction_id: str, body: Reason, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id, "review")
    row = _scoped(db, Redaction, actor.user, case_id, redaction_id)
    if len(body.reason.strip()) < 3 or row.state != "ready_for_review":
        fail(409, "REDACTION_TRANSITION_INVALID", "Reject only a ready derivative with a meaningful reason.")
    changed = db.execute(update(Redaction).where(Redaction.id == row.id, Redaction.state == "ready_for_review").values(state="rejected")).rowcount
    if not changed:
        fail(409, "REDACTION_TRANSITION_INVALID", "The derivative was already reviewed.")
    audit.record(db, actor.user, case_id, "redaction.rejected", "redaction", row.id, {"reason": body.reason.strip()})
    db.commit()
    return redaction_json(row)


def _production_sources(db, job, storage, approved=False):
    user = _person(db, job.tenant_id, job.case_id, job.requested_by, "export")
    if approved:
        signer = _person(db, job.tenant_id, job.case_id, job.approved_by, "privilege")
        _approver(db, signer, job.case_id, job.requested_by)
    rows = _rows(db, job.tenant_id, job.case_id, job.evidence_ids)
    _check_items(rows, "zip", storage)
    for item, original, _occurrence, _source in rows:
        snapshot = _source_snapshot(db, item, original, storage, text=not _is_pdf(item, original, storage) or item.id in job.redactions and job.snapshot[item.id].get("redaction_kind") == "text")
        redaction_id = job.redactions.get(item.id)
        if redaction_id:
            redaction = _scoped(db, Redaction, user, job.case_id, redaction_id)
            if redaction.evidence_id != item.id:
                fail(422, "REDACTION_SCOPE_INVALID", "The redaction belongs to a different evidence item.")
            _validated_redaction(db, redaction, storage, require_approved=True)
            snapshot.update(redaction_id=redaction.id, redaction_sha256=redaction.sha256, redaction_kind=redaction.kind, redaction_approved_by=redaction.approved_by)
        if snapshot != job.snapshot.get(item.id):
            fail(409, "PRODUCTION_SNAPSHOT_CHANGED", "Source, review or approved redaction changed; propose a new production.")
    return user, rows


@router.post("/cases/{case_id}/productions", status_code=201)
def request_production(case_id: str, body: ProductionInput, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    _confirmation(body)
    authorize_case(db, actor.user, case_id, "export")
    scope_input = ExportInput(format="zip", reason=body.reason, confirmed=True, evidence_ids=body.evidence_ids, query_spec=body.query_spec, review_set_id=body.review_set_id)
    ids, scope = _select_ids(db, actor.user, case_id, scope_input)
    if len(ids) > MAX_ITEMS or set(body.redactions) - set(ids):
        fail(422, "PRODUCTION_SCOPE_INVALID", "Choose at most 200 items and attach redactions only to selected evidence.")
    rows = _rows(db, actor.user.tenant_id, case_id, ids)
    _check_items(rows, "zip", request.app.state.storage)
    snapshot = {}
    for item, original, _occurrence, _source in rows:
        redaction = None
        if item.id in body.redactions:
            redaction = _scoped(db, Redaction, actor.user, case_id, body.redactions[item.id])
            if redaction.evidence_id != item.id:
                fail(422, "REDACTION_SCOPE_INVALID", "The redaction belongs to a different evidence item.")
            _validated_redaction(db, redaction, request.app.state.storage, require_approved=True)
        text = redaction.kind == "text" if redaction else not _is_pdf(item, original, request.app.state.storage)
        value = _source_snapshot(db, item, original, request.app.state.storage, text=text)
        if redaction:
            value.update(redaction_id=redaction.id, redaction_sha256=redaction.sha256, redaction_kind=redaction.kind, redaction_approved_by=redaction.approved_by)
        snapshot[item.id] = value
    original_groups = {}
    for value in snapshot.values():
        original_groups.setdefault(value["original_id"], []).append(value.get("redaction_sha256"))
    if any(any(values) and len(set(values)) > 1 for values in original_groups.values()):
        fail(409, "REDACTION_DUPLICATE_HOLDBACK", "Identical original occurrences must use the same approved redacted bytes; do not include an unredacted or differently redacted duplicate in this production.")
    active_holds = list(db.scalars(select(Hold.id).where(Hold.tenant_id == actor.user.tenant_id, Hold.case_id == case_id, Hold.state == "active")))
    job = Production(tenant_id=actor.user.tenant_id, case_id=case_id, requested_by=actor.user.id, reason=body.reason.strip(), bates_prefix=body.bates_prefix, evidence_ids=ids, redactions=body.redactions, snapshot=snapshot, counts={"requested": len(ids), "processed": 0, "scope": scope, "active_hold_ids": active_holds, "delivery": "derived_only", "omitted": "Original natives, attachments outside selected IDs, source titles, filenames, participants and paths are excluded. Text outputs reflect complete indexed extraction; PDF outputs flatten visible pages without a text layer."})
    db.add(job)
    db.flush()
    audit.record(db, actor.user, case_id, "production.proposed", "production", job.id, {"count": len(ids), "redacted": len(body.redactions), "active_holds": len(active_holds)})
    db.commit()
    return production_json(job, db)


@router.get("/cases/{case_id}/productions")
def list_productions(case_id: str, limit: int = 50, cursor: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id, "export")
    rows, cursor = _list(db, Production, actor.user, case_id, limit, cursor)
    return {"items": [production_json(row) for row in rows], "next_cursor": cursor}


@router.get("/cases/{case_id}/productions/{production_id}")
def get_production(case_id: str, production_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id, "export")
    return production_json(_scoped(db, Production, actor.user, case_id, production_id), db)


@router.post("/cases/{case_id}/productions/{production_id}/approve")
def approve_production(case_id: str, production_id: str, body: Confirm, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    _confirmation(body)
    job = _scoped(db, Production, actor.user, case_id, production_id)
    _approver(db, actor.user, case_id, job.requested_by)
    _production_sources(db, job, request.app.state.storage)
    changed = db.execute(update(Production).where(Production.id == job.id, Production.state == "proposed").values(state="pending", approved_by=actor.user.id, approved_at=now(), approval_reason=body.reason.strip())).rowcount
    if not changed:
        fail(409, "PRODUCTION_TRANSITION_INVALID", "Only a proposed production can receive its separate approval.")
    audit.record(db, actor.user, case_id, "production.approved", "production", job.id, {"reason": body.reason.strip()})
    db.commit()
    db.refresh(job)
    return production_json(job, db)


@router.post("/cases/{case_id}/productions/{production_id}/reject")
def reject_production(case_id: str, production_id: str, body: Reason, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    row = _scoped(db, Production, actor.user, case_id, production_id)
    _approver(db, actor.user, case_id, row.requested_by)
    if len(body.reason.strip()) < 3 or not db.execute(update(Production).where(Production.id == row.id, Production.state == "proposed").values(state="rejected", approval_reason=body.reason.strip())).rowcount:
        fail(409, "PRODUCTION_TRANSITION_INVALID", "Reject only a proposed production with a meaningful reason.")
    audit.record(db, actor.user, case_id, "production.rejected", "production", row.id, {"reason": body.reason.strip()})
    db.commit()
    return production_json(row, db)


def _label(prefix, number):
    return f"{prefix}{number:08d}"


def _claim(database, model):
    token = new_id()
    with database.sessions() as db:
        eligible = or_(model.state == "pending", (model.state == "running") & (model.lease_until < now()))
        identifier = db.scalar(select(model.id).where(eligible).order_by(model.created_at, model.id).limit(1))
        if identifier is None:
            return None
        claimed = db.execute(update(model).where(model.id == identifier, eligible).values(state="running", lease_token=token, lease_until=now() + timedelta(minutes=15)).returning(model.id)).scalar_one_or_none()
        db.commit()
        return (claimed, token) if claimed else None


def _still_owned(db, model, identifier, token):
    row = db.scalar(select(model).where(model.id == identifier, model.state == "running", model.lease_token == token, model.lease_until > now()))
    if row is None:
        fail(409, "JOB_LEASE_EXPIRED", "The worker no longer holds this disclosure job.")
    return row


def _heartbeat(database, model, identifier, token):
    with database.sessions() as db:
        changed = db.execute(update(model).where(model.id == identifier, model.state == "running", model.lease_token == token, model.lease_until > now()).values(lease_until=now() + timedelta(minutes=15))).rowcount
        db.commit()
        if not changed:
            fail(409, "JOB_LEASE_EXPIRED", "The worker no longer holds this disclosure job.")


def _copy_verified_source(storage, original, source):
    digest, byte_size = hashlib.sha256(), 0
    with storage.path(original.storage_key).open("rb") as incoming, source.open("wb") as outgoing:
        while chunk := incoming.read(1024 * 1024):
            digest.update(chunk)
            byte_size += len(chunk)
            if byte_size > 50_000_000:
                fail(413, "PRODUCTION_SOURCE_LIMIT", "The original exceeds the bounded PDF source size.")
            outgoing.write(chunk)
    if digest.hexdigest() != original.sha256 or byte_size != original.byte_size:
        fail(409, "INTEGRITY_FAILED", "The original changed while preparing the isolated PDF render.")


def _flatten_pdf(storage, original, regions):
    temporary = storage.root / "temporary-productions"
    temporary.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temporary) as directory:
        selection, output, source = Path(directory) / "regions.json", Path(directory) / "output.pdf", Path(directory) / "source.pdf"
        _copy_verified_source(storage, original, source)
        selection.write_bytes(canonical_json(regions))
        try:
            result = subprocess.run([sys.executable, "-m", "casequarry.production_pdf_worker", str(source), str(selection), str(output)], timeout=90, capture_output=True, check=False)
        except subprocess.TimeoutExpired:
            fail(413, "PDF_RENDER_TIMEOUT", "The source exceeded the bounded PDF rendering deadline.")
        if result.returncode or not output.is_file():
            fail(422, "PDF_RENDER_FAILED", "The PDF could not be safely flattened within the supported page, pixel and runtime limits.")
        if output.stat().st_size > MAX_PACKAGE_BYTES:
            fail(413, "PRODUCTION_SIZE_LIMIT", "The flattened PDF exceeds the production size limit.")
        data = output.read_bytes()
        clean_pdf_images(data)
        return data


def _run_redaction(database, storage, claimed):
    identifier, token = claimed
    with database.sessions() as db:
        row = _still_owned(db, Redaction, identifier, token)
        _user, item, original = _validated_redaction(db, row, storage)
        if row.kind == "pdf":
            data = _flatten_pdf(storage, original, row.selection["regions"])
            verification = {"method": "fresh_lossless_raster_pdf_v1", "pages": len(clean_pdf_images(data)), "selected_regions": len(row.selection["regions"]), "hidden_text": "removed", "source_objects": "not_copied", "selected_regions_burned": True, "human_review_required": True, "limits": "Only the selected visible regions are masked; other visible sensitive content requires human inspection."}
        else:
            ranges = sorted(row.selection["ranges"], key=lambda value: value["start"])
            position, pieces = 0, []
            for value in ranges:
                if not position <= value["start"] < value["end"] <= len(item.text):
                    fail(409, "REDACTION_SELECTION_INVALID", "Stored text redaction ranges are invalid.")
                pieces.extend((item.text[position:value["start"]], "[REDACTED]"))
                position = value["end"]
            pieces.append(item.text[position:])
            data = "".join(pieces).encode("utf-8")
            verification = {"method": "utf8_selected_range_removal_v1", "selected_ranges": len(ranges), "source_text_version": item.text_version, "source_native": "not_included", "human_review_required": True, "limits": "Only selected ranges are removed; repeated words elsewhere remain until separately selected."}
        db.rollback()
        row = _still_owned(db, Redaction, identifier, token)
        user, _item_row, _original = _validated_redaction(db, row, storage)
        key, digest, size = storage.store_bytes(row.tenant_id, row.case_id, data, kind="derived")
        row.storage_key, row.sha256, row.byte_size, row.verification, row.state = key, digest, size, verification, "ready_for_review"
        row.lease_token, row.lease_until = None, None
        audit.record(db, user, row.case_id, "redaction.generated", "redaction", row.id, {"sha256": digest, "kind": row.kind})
        db.commit()


def _reserve(db, job, sizes):
    existing = list(db.scalars(select(ProductionItem).where(ProductionItem.production_id == job.id).order_by(ProductionItem.evidence_id)))
    if existing:
        if {row.evidence_id: row.page_count for row in existing} != sizes:
            fail(409, "BATES_REGISTRY_CHANGED", "The reserved Bates page counts do not match the approved source.")
        return {row.evidence_id: row for row in existing}
    dialect = db.bind.dialect.name
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert
    db.execute(insert(BatesCounter).values(id=new_id(), created_at=now(), tenant_id=job.tenant_id, case_id=job.case_id, prefix=job.bates_prefix, next_number=1).on_conflict_do_nothing(index_elements=["tenant_id", "case_id", "prefix"]))
    count = sum(sizes.values())
    end = db.execute(update(BatesCounter).where(BatesCounter.tenant_id == job.tenant_id, BatesCounter.case_id == job.case_id, BatesCounter.prefix == job.bates_prefix, BatesCounter.next_number + count <= 99_999_999).values(next_number=BatesCounter.next_number + count).returning(BatesCounter.next_number)).scalar_one_or_none()
    if end is None:
        fail(409, "BATES_RANGE_EXHAUSTED", "The eight-digit Bates range is exhausted for this prefix.")
    cursor, result = end - count, {}
    for identifier in sorted(sizes):
        item = ProductionItem(tenant_id=job.tenant_id, case_id=job.case_id, production_id=job.id, evidence_id=identifier, prefix=job.bates_prefix, start_number=cursor, end_number=cursor + sizes[identifier] - 1, page_count=sizes[identifier])
        db.add(item)
        result[identifier] = item
        cursor += sizes[identifier]
    db.flush()
    return result


def _render_sources(db, job, rows, storage, heartbeat=None):
    produced = {}
    total, pixels = 0, 0
    for item, original, _occurrence, _source in rows:
        redaction_id = job.redactions.get(item.id)
        if redaction_id:
            redaction = db.get(Redaction, redaction_id)
            data = storage.path(redaction.storage_key).read_bytes()
            if len(data) != redaction.byte_size or hashlib.sha256(data).hexdigest() != redaction.sha256:
                fail(409, "REDACTION_INTEGRITY_FAILED", "The approved derivative changed while preparing the production.")
            kind = redaction.kind
        elif _is_pdf(item, original, storage):
            data, kind = _flatten_pdf(storage, original, []), "pdf"
        else:
            data, kind = item.text.encode("utf-8"), "text"
        total += len(data)
        if total > MAX_PACKAGE_BYTES:
            fail(413, "PRODUCTION_SIZE_LIMIT", "The selected derivatives exceed the 250-megabyte production limit.")
        value = clean_pdf_images(data) if kind == "pdf" else data
        if kind == "pdf":
            pixels += sum(image.width * image.height for image in value)
            if pixels > MAX_JOB_PIXELS:
                fail(413, "PRODUCTION_PIXEL_LIMIT", "The selected PDFs exceed the 60-million-pixel production memory limit. Split the scope.")
        produced[item.id] = (kind, value)
        if heartbeat:
            heartbeat()
    return produced


def _package(job, rows, produced, ledger, destination, heartbeat=None, signing_key=None):
    entries, opt, total = [], [], 0
    package_files = {}
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        def write_member(name, data):
            archive.writestr(name, data)
            package_files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data)}
        for item, original, _occurrence, _source in rows:
            record = ledger[item.id]
            labels = [_label(record.prefix, number) for number in range(record.start_number, record.end_number + 1)]
            kind, value = produced[item.id]
            path = f"documents/{labels[0]}.{'pdf' if kind == 'pdf' else 'txt'}"
            if kind == "pdf":
                images = stamped_images(value, labels)
                data = clean_pdf(images)
                for number, (image, label) in enumerate(zip(images, labels, strict=True)):
                    page_path = f"images/{label}.pdf"
                    page_bytes = clean_pdf([image])
                    write_member(page_path, page_bytes)
                    total += len(page_bytes)
                    opt.append((label, "CQ", page_path.replace("/", "\\"), "Y" if number == 0 else "", "", "", str(len(images)) if number == 0 else ""))
            else:
                data = value + f"\n\nBates control: {labels[0]}\n".encode("ascii")
            total += len(data)
            if total > MAX_PACKAGE_BYTES:
                fail(413, "PRODUCTION_SIZE_LIMIT", "The complete derived package exceeds 250 megabytes.")
            write_member(path, data)
            digest = hashlib.sha256(data).hexdigest()
            entry = {"BEGBATES": labels[0], "ENDBATES": labels[-1], "EVIDENCE_ID": item.id, "PARENT_ID": item.parent_id or "", "SOURCE_ID": item.source_id, "ORIGINAL_SHA256": original.sha256, "PRODUCED_SHA256": digest, "PAGE_COUNT": record.page_count, "REDACTED": str(item.id in job.redactions).lower(), "DERIVED_PATH": path, "TEXT_PATH": path if kind == "text" else ""}
            entries.append(entry)
            record.produced_sha256 = digest
            if heartbeat:
                heartbeat()
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(entries)
        write_member("loadfile.csv", output.getvalue().encode("utf-8-sig"))
        # Explicit UTF-8 DAT profile: U+0014 columns and U+00FE quoted fields.
        dat = "\r\n".join("\x14".join("þ" + str(value) + "þ" for value in line) for line in [FIELDS, *[[entry[field] for field in FIELDS] for entry in entries]]) + "\r\n"
        write_member("loadfile.dat", dat.encode("utf-8-sig"))
        output = io.StringIO(newline="")
        csv.writer(output, lineterminator="\r\n").writerows(opt)
        write_member("images.opt", output.getvalue().encode("ascii"))
        manifest = {"schema_version": "casequarry-derived-production-v1", "production_id": job.id, "case_id": job.case_id, "delivery": "derived_only", "items": entries, "algorithm": "SHA-256", "assurance": "Application SHA-256 verification without a digital signature or independent time anchor.", "loadfile_profile": {"csv": "UTF-8 BOM, comma, quoted by RFC4180 writer", "dat": "UTF-8 BOM; U+0014 column; U+00FE quote; CRLF rows; no long-text field", "opt": "ASCII seven-column Opticon; relative Windows paths; single-page flattened PDF images; text-only items have a document control and no image entry"}, "limitations": ["No recipient review-platform import was executed; configure this explicit field/delimiter/image profile for the recipient.", "Text derivatives preserve extracted text, not native layout or attachments. PDF derivatives flatten visible pages and add a new Bates footer without hidden text.", "Only explicitly selected IDs are delivered; originals and source names, paths, participants, titles, internal reasons and queries are omitted.", "Selected-region or selected-range redaction requires human visual/content review; this is not automatic detection of all sensitive content."], "approval": {"requested_by": job.requested_by, "approved_by": job.approved_by, "approved_at": utc(job.approved_at).isoformat()}, "preservation": "Originals remain preserved; an active legal hold does not grant disclosure authority."}
        if signing_key is not None:
            manifest["schema_version"] = "casequarry-derived-production-v2"
            manifest["package_files"] = package_files
            manifest["assurance"] = "Exact manifest bytes and complete derived package inventory signed with Ed25519; verification requires an independently trusted public key and does not establish an independent timestamp."
        manifest_bytes = canonical_json(manifest)
        archive.writestr("manifest.json", manifest_bytes)
        if signing_key is not None:
            archive.writestr(SIGNATURE_NAME, canonical_json(sign_manifest(manifest_bytes, signing_key)))
    with zipfile.ZipFile(destination) as archive:
        expected = {"manifest.json", *package_files}
        if signing_key is not None:
            expected.add(SIGNATURE_NAME)
        if archive.testzip() or set(archive.namelist()) != expected:
            fail(409, "PRODUCTION_PACKAGE_INVALID", "The generated production failed its package structure check.")
        for entry in entries:
            if hashlib.sha256(archive.read(entry["DERIVED_PATH"])).hexdigest() != entry["PRODUCED_SHA256"]:
                fail(409, "PRODUCTION_PACKAGE_INVALID", "Produced bytes failed the manifest hash check.")
    return manifest_bytes


def _run_production(database, storage, claimed, signing_key=None):
    identifier, token = claimed
    with database.sessions() as db:
        job = _still_owned(db, Production, identifier, token)
        _user, rows = _production_sources(db, job, storage, approved=True)
        def heartbeat():
            _heartbeat(database, Production, identifier, token)
        produced = _render_sources(db, job, rows, storage, heartbeat=heartbeat)
        db.rollback()
        if db.bind.dialect.name == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        job = _still_owned(db, Production, identifier, token)
        _user, rows = _production_sources(db, job, storage, approved=True)
        ledger = _reserve(db, job, {key: len(value) if kind == "pdf" else 1 for key, (kind, value) in produced.items()})
        db.commit()  # Allocated numbers are never recycled, including failed attempts.
        temporary = storage.root / "temporary-productions"
        temporary.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary) as directory:
            destination = Path(directory) / "production.zip"
            manifest_bytes = _package(job, rows, produced, ledger, destination, heartbeat=heartbeat, signing_key=signing_key)
            hashes = {key: row.produced_sha256 for key, row in ledger.items()}
            db.rollback()
            job = _still_owned(db, Production, identifier, token)
            user, _rows_now = _production_sources(db, job, storage, approved=True)
            for row in db.scalars(select(ProductionItem).where(ProductionItem.production_id == identifier)):
                row.produced_sha256 = hashes[row.evidence_id]
            key, digest, size = storage.store_file(job.tenant_id, job.case_id, destination, kind="exports")
            manifest_key, manifest_hash, _manifest_size = storage.store_bytes(job.tenant_id, job.case_id, manifest_bytes, kind="exports")
        job.storage_key, job.sha256, job.byte_size, job.state = key, digest, size, "completed"
        job.lease_token, job.lease_until = None, None
        job.counts = {**job.counts, "processed": len(job.evidence_ids), "page_controls": sum(row.page_count for row in ledger.values()), "manifest_sha256": manifest_hash, "manifest_storage_key": manifest_key, "manifest_signing": signing_metadata(signing_key)}
        audit.record(db, user, job.case_id, "production.completed", "production", job.id, {"count": len(job.evidence_ids), "sha256": digest})
        db.commit()


def _failed(database, model, claimed, error):
    identifier, token = claimed
    details = error.detail if isinstance(error, HTTPException) and isinstance(error.detail, dict) else {}
    code, message = details.get("error_code", "PRODUCTION_FAILED"), details.get("message", "The derived disclosure failed. Inspect source integrity, supported limits and human approvals before proposing a new job.")
    with database.sessions() as db:
        row = db.scalar(select(model).where(model.id == identifier, model.lease_token == token, model.state == "running"))
        if row is None:
            return
        row.state, row.lease_token, row.lease_until = "failed", None, None
        if model is Redaction:
            row.error_code, row.error = code, message
        else:
            row.counts = {**row.counts, "error_code": code, "error": message, "processed": 0}
        user = db.get(User, row.requested_by)
        if user:
            audit.record(db, user, row.case_id, "disclosure.failed", "redaction" if model is Redaction else "production", row.id, {"error_code": code})
        db.commit()


def process_pending_productions(database, settings, storage):
    for model, callback in ((Redaction, _run_redaction), (Production, _run_production)):
        claimed = _claim(database, model)
        if claimed:
            try:
                if model is Production:
                    try:
                        signing_key = load_private_signing_key(getattr(settings, "export_signing_key_file", None))
                    except SigningKeyError:
                        fail(503, "EXPORT_SIGNING_KEY_INVALID", "Configured export signing key is invalid or unavailable. No unsigned package was generated.")
                    callback(database, storage, claimed, signing_key=signing_key)
                else:
                    callback(database, storage, claimed)
            except Exception as error:
                _failed(database, model, claimed, error)
            return True
    return False


@router.get("/cases/{case_id}/productions/{production_id}/download")
def download_production(case_id: str, production_id: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id, "export")
    row = _scoped(db, Production, actor.user, case_id, production_id)
    if row.state != "completed":
        fail(409, "PRODUCTION_NOT_READY", "The production has not completed its approvals and verification.")
    _production_sources(db, row, request.app.state.storage, approved=True)
    try:
        valid = request.app.state.storage.verify(row)["valid"] and file_hash(request.app.state.storage.path(row.counts["manifest_storage_key"]))[0] == row.counts["manifest_sha256"]
    except (OSError, KeyError):
        valid = False
    if not valid:
        fail(409, "PRODUCTION_INTEGRITY_FAILED", "The produced package or manifest failed verification.")
    audit.record(db, actor.user, case_id, "production.downloaded", "production", row.id, {"sha256": row.sha256})
    db.commit()
    return FileResponse(request.app.state.storage.path(row.storage_key), filename=f"casequarry-production-{row.id}.zip", media_type="application/zip", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Content-SHA256": row.sha256, "X-Manifest-SHA256": row.counts["manifest_sha256"]})


@router.get("/cases/{case_id}/evidence/{evidence_id}/page-preview")
def source_page_preview(case_id: str, evidence_id: str, request: Request, page: int = Query(default=1, ge=1, le=50), actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    storage = request.app.state.storage
    item, original = _item(db, actor.user.tenant_id, case_id, evidence_id)
    if item.parser_state == "quarantined":
        fail(409, "EVIDENCE_QUARANTINED", "Quarantined evidence cannot be previewed.")
    if not _is_pdf(item, original, storage):
        fail(422, "PDF_PREVIEW_UNSUPPORTED", "Raster page preview requires a PDF original.")
    if not storage.verify(original)["valid"]:
        fail(409, "INTEGRITY_FAILED", "The original failed verification; preview is blocked.")
    original_snapshot = (original.id, original.sha256, original.storage_key)
    temporary = storage.root / "temporary-productions"
    temporary.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temporary) as directory:
        source, selection, output = Path(directory) / "source.pdf", Path(directory) / "selection.json", Path(directory) / "page.png"
        _copy_verified_source(storage, original, source)
        selection.write_text("[]", encoding="utf-8")
        try:
            result = subprocess.run([sys.executable, "-m", "casequarry.production_pdf_worker", str(source), str(selection), str(output), "--page-preview", str(page)], capture_output=True, timeout=30, check=False)
        except subprocess.TimeoutExpired:
            fail(413, "PDF_RENDER_TIMEOUT", "The source exceeded the bounded raster preview deadline.")
        if result.returncode or not output.is_file():
            fail(422, "PDF_RENDER_FAILED", "This PDF page could not be safely previewed within the renderer limits.")
        if output.stat().st_size > 50_000_000:
            fail(413, "PDF_PREVIEW_SIZE_LIMIT", "Raster preview exceeds the supported byte limit.")
        data = output.read_bytes()
        information = json.loads(Path(str(output) + ".json").read_text(encoding="utf-8"))
        with Image.open(io.BytesIO(data)) as rendered:
            if rendered.format != "PNG" or rendered.width * rendered.height > 40_000_000:
                fail(409, "PDF_PREVIEW_INVALID", "The raster preview failed output validation.")
            rendered.verify()
    db.rollback()
    authorize_case(db, actor.user, case_id)
    _item_now, original = _item(db, actor.user.tenant_id, case_id, evidence_id)
    active = db.scalar(select(User).where(User.id == actor.user.id, User.active.is_(True)))
    if active is None or (original.id, original.sha256, original.storage_key) != original_snapshot or not storage.verify(original)["valid"]:
        fail(409, "PDF_PREVIEW_SOURCE_CHANGED", "Source integrity or access changed during preview generation.")
    audit.record(db, actor.user, case_id, "evidence.page_previewed", "evidence", evidence_id, {"page": page, "original_sha256": original.sha256})
    db.commit()
    return Response(data, media_type="image/png", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Page-Count": str(information["page_count"]), "X-Page-Number": str(page), "X-Original-SHA256": original.sha256, "X-Content-SHA256": hashlib.sha256(data).hexdigest()})
