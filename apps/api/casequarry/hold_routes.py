"""Versioned staff records of custodian notices, without delivery or identity claims."""

import hashlib
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, field_validator
from sqlalchemy import and_, case, func, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import audit
from .case_domain import lock_case_action
from .governance_routes import _visible_case_query
from .hold_models import HoldNotice
from .models import Audit, Custodian, Hold, now
from .schemas import DateOnly, Reason
from .security import Actor, authorize_case, current_actor, fail, get_db, utc
from .time_zones import local_today

router = APIRouter(prefix="/api/v1")
BASE = "/cases/{case_id}/holds/{hold_id}/notices"
_META = tuple(column.name for column in HoldNotice.__table__.columns if column.name != "notice_text")


class NoticeCreate(Reason):
    custodian_id: str = Field(min_length=1, max_length=36)
    notice_text: str = Field(min_length=1, max_length=20000)
    next_reminder_date: DateOnly | None = None

    @field_validator("notice_text")
    @classmethod
    def meaningful_text(cls, value):
        if not value.strip():
            raise ValueError("Provide meaningful notice text.")
        return value


class NoticeAction(Reason):
    expected_version: int = Field(ge=1, strict=True)


class NoticePatch(NoticeAction):
    notice_text: str | None = Field(default=None, min_length=1, max_length=20000)
    next_reminder_date: DateOnly | None = None

    @field_validator("notice_text")
    @classmethod
    def meaningful_text(cls, value):
        if value is None or not value.strip():
            raise ValueError("Provide meaningful notice text.")
        return value


class NoticeAcknowledge(NoticeAction):
    acknowledgement_name: str = Field(min_length=1, max_length=200)

    @field_validator("acknowledgement_name")
    @classmethod
    def meaningful_name(cls, value):
        if not value.strip():
            raise ValueError("Record the name supplied for this acknowledgement.")
        return value.strip()


class NoticeReminder(NoticeAction):
    next_reminder_date: DateOnly | None = None


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clock(user):
    return {"server_today": local_today(user.time_zone, now()).isoformat(), "time_zone": user.time_zone}


def _json(values):
    return {key: utc(value).isoformat() if isinstance(value, datetime) else value.isoformat() if isinstance(value, date) else value for key, value in values.items()}


def _parent_query(user, case_id, hold_id):
    visible = _visible_case_query(user, case_id).cte("notice_visible_matter")
    return select(Hold.id, Hold.state).join(visible, visible.c.id == Hold.case_id).where(Hold.tenant_id == user.tenant_id, Hold.case_id == case_id, Hold.id == hold_id)


def _scope(user, case_id, hold_id, parent):
    return select(*[getattr(HoldNotice, name) for name in _META], Custodian.display_name.label("custodian_name")).join(parent, parent.c.id == HoldNotice.hold_id).join(Custodian, and_(Custodian.id == HoldNotice.custodian_id, Custodian.tenant_id == HoldNotice.tenant_id, Custodian.case_id == HoldNotice.case_id)).where(HoldNotice.tenant_id == user.tenant_id, HoldNotice.case_id == case_id, HoldNotice.hold_id == hold_id)


def _detail(db, user, case_id, hold_id, notice_id):
    parent = _parent_query(user, case_id, hold_id).cte("notice_parent")
    row = db.execute(_scope(user, case_id, hold_id, parent).add_columns(HoldNotice.notice_text, parent.c.state.label("hold_state")).where(HoldNotice.id == notice_id)).mappings().first()
    if row is None:
        fail(404, "NOT_FOUND", "The hold notice is unavailable.")
    result = _json(dict(row))
    result.update(_clock(user), manual_recording=True, identity_verified=False)
    return result


def _locked_parent(db, actor, case_id, hold_id):
    lock_case_action(db, actor.user, case_id, "hold")
    hold = db.scalar(select(Hold).where(Hold.id == hold_id, Hold.tenant_id == actor.user.tenant_id, Hold.case_id == case_id))
    if hold is None:
        fail(404, "NOT_FOUND", "The preservation hold is unavailable.")
    if hold.state != "active":
        fail(409, "HOLD_INACTIVE", "Only an active preservation hold accepts notice changes.")
    return hold


def _locked_notice(db, actor, case_id, hold_id, notice_id, expected_version):
    _locked_parent(db, actor, case_id, hold_id)
    row = db.scalar(select(HoldNotice).where(HoldNotice.id == notice_id, HoldNotice.tenant_id == actor.user.tenant_id, HoldNotice.case_id == case_id, HoldNotice.hold_id == hold_id))
    if row is None:
        fail(404, "NOT_FOUND", "The hold notice is unavailable.")
    if row.version != expected_version:
        fail(409, "HOLD_NOTICE_CONFLICT", "The notice changed. Reload it before applying this action.")
    return row


def _record(db, actor, request, case_id, notice_id, event, metadata):
    audit.record(db, actor.user, case_id, f"hold_notice.{event}", "hold_notice", notice_id, metadata, getattr(request.state, "request_id", ""))
    db.commit()


def _apply(db, actor, request, case_id, hold_id, row, body, event, values):
    before = {name: getattr(row, name) for name in values}
    old_version = row.version
    result = db.execute(update(HoldNotice).where(HoldNotice.id == row.id, HoldNotice.tenant_id == actor.user.tenant_id, HoldNotice.case_id == case_id, HoldNotice.hold_id == hold_id, HoldNotice.version == body.expected_version).values(**values, version=old_version + 1, updated_at=now()))
    if result.rowcount != 1:
        fail(409, "HOLD_NOTICE_CONFLICT", "The notice changed. Reload it before applying this action.")
    # Keep the audit bounded; the exact text is stored once on the notice, not copied into events.
    before.pop("notice_text", None)
    after = {name: value for name, value in values.items() if name != "notice_text"}
    _record(db, actor, request, case_id, row.id, event, {"reason": body.reason, "previous_version": old_version, "version": old_version + 1, "before": _json(before), "after": _json(after)})
    return _detail(db, actor.user, case_id, hold_id, row.id)


@router.get(BASE)
def list_notices(case_id: str, hold_id: str, limit: int = Query(default=50, ge=1, le=200), cursor: str | None = Query(default=None, max_length=36), actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    clock = _clock(actor.user)
    parent = _parent_query(actor.user, case_id, hold_id).cte("notice_parent")
    scoped = _scope(actor.user, case_id, hold_id, parent).cte("notice_items")
    def count(condition):
        return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)
    totals = select(func.count().label("total"), count(scoped.c.state == "draft").label("draft"), count(scoped.c.state == "issued").label("issued"), count(scoped.c.state == "acknowledged").label("acknowledged"), count(and_(scoped.c.state == "issued", scoped.c.next_reminder_date < date.fromisoformat(clock["server_today"]))).label("overdue"), func.coalesce(func.sum(scoped.c.reminder_count), 0).label("reminders")).select_from(scoped).cte("notice_totals")
    page_query = select(scoped)
    if cursor:
        page_query = page_query.where(scoped.c.id > cursor)
    page = page_query.order_by(scoped.c.id).limit(limit + 1).cte("notice_page")
    anchor_valid = select(scoped.c.id).where(scoped.c.id == cursor).exists() if cursor else true()
    rows = list(db.execute(select(parent.c.state.label("hold_state"), *totals.c, anchor_valid.label("anchor_valid"), *page.c).select_from(parent).join(totals, true()).outerjoin(page, true()).order_by(page.c.id)).mappings())
    if not rows:
        fail(404, "NOT_FOUND", "The preservation hold is unavailable.")
    if not rows[0]["anchor_valid"]:
        fail(422, "HOLD_NOTICE_CURSOR_INVALID", "Restart the notice list with its current preservation hold.")
    items = [_json({name: row[name] for name in (*_META, "custodian_name")}) for row in rows if row["id"] is not None]
    summary = {name: rows[0][name] for name in ("total", "draft", "issued", "acknowledged", "overdue", "reminders")}
    summary["pending_acknowledgement"] = summary["issued"]
    return {"items": items[:limit], "next_cursor": items[limit - 1]["id"] if len(items) > limit else None, "summary": summary, "hold_state": rows[0]["hold_state"], **clock}


@router.post(BASE, status_code=201)
def create_notice(case_id: str, hold_id: str, body: NoticeCreate, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    _locked_parent(db, actor, case_id, hold_id)
    custodian = db.scalar(select(Custodian.id).where(Custodian.id == body.custodian_id, Custodian.tenant_id == actor.user.tenant_id, Custodian.case_id == case_id))
    if custodian is None:
        fail(404, "NOT_FOUND", "The custodian is unavailable.")
    if db.scalar(select(HoldNotice.id).where(HoldNotice.hold_id == hold_id, HoldNotice.custodian_id == custodian)):
        fail(409, "HOLD_NOTICE_EXISTS", "This preservation hold already has a notice for this custodian.")
    row = HoldNotice(tenant_id=actor.user.tenant_id, case_id=case_id, hold_id=hold_id, custodian_id=custodian, notice_text=body.notice_text, notice_text_sha256=_hash(body.notice_text), created_by=actor.user.id, next_reminder_date=body.next_reminder_date)
    tenant_id = actor.user.tenant_id
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        duplicate = db.scalar(select(HoldNotice.id).where(HoldNotice.tenant_id == tenant_id, HoldNotice.case_id == case_id, HoldNotice.hold_id == hold_id, HoldNotice.custodian_id == custodian))
        if duplicate is not None:
            fail(409, "HOLD_NOTICE_EXISTS", "This preservation hold already has a notice for this custodian.")
        raise
    _record(db, actor, request, case_id, row.id, "created", {"reason": body.reason, "version": row.version, "state": row.state, "custodian_id": row.custodian_id, "notice_text_sha256": row.notice_text_sha256, "next_reminder_date": body.next_reminder_date.isoformat() if body.next_reminder_date else None})
    return _detail(db, actor.user, case_id, hold_id, row.id)


@router.get(BASE + "/{notice_id}")
def get_notice(case_id: str, hold_id: str, notice_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    return _detail(db, actor.user, case_id, hold_id, notice_id)


@router.patch(BASE + "/{notice_id}")
def patch_notice(case_id: str, hold_id: str, notice_id: str, body: NoticePatch, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    row = _locked_notice(db, actor, case_id, hold_id, notice_id, body.expected_version)
    if row.state == "acknowledged":
        fail(409, "HOLD_NOTICE_TRANSITION_INVALID", "An acknowledged notice cannot be edited.")
    values = body.model_dump(exclude_unset=True, exclude={"expected_version", "reason"})
    if not values:
        fail(422, "VALIDATION_ERROR", "Provide notice text or a reminder date to change.")
    if "notice_text" in values:
        if row.state != "draft":
            fail(409, "HOLD_NOTICE_TEXT_FROZEN", "Issued notice text is permanently frozen. Create a new preservation hold for different text.")
        values["notice_text_sha256"] = _hash(values["notice_text"])
    return _apply(db, actor, request, case_id, hold_id, row, body, "updated", values)


@router.post(BASE + "/{notice_id}/issue")
def issue_notice(case_id: str, hold_id: str, notice_id: str, body: NoticeAction, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    row = _locked_notice(db, actor, case_id, hold_id, notice_id, body.expected_version)
    if row.state != "draft":
        fail(409, "HOLD_NOTICE_TRANSITION_INVALID", "Only a draft notice can have issuance recorded.")
    return _apply(db, actor, request, case_id, hold_id, row, body, "issued", {"state": "issued", "issued_by": actor.user.id, "issued_at": now()})


@router.post(BASE + "/{notice_id}/acknowledge")
def acknowledge_notice(case_id: str, hold_id: str, notice_id: str, body: NoticeAcknowledge, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    row = _locked_notice(db, actor, case_id, hold_id, notice_id, body.expected_version)
    if row.state != "issued":
        fail(409, "HOLD_NOTICE_TRANSITION_INVALID", "Only an issued notice can have acknowledgement recorded.")
    return _apply(db, actor, request, case_id, hold_id, row, body, "acknowledged", {"state": "acknowledged", "acknowledgement_name": body.acknowledgement_name, "acknowledged_by": actor.user.id, "acknowledged_at": now(), "next_reminder_date": None})


@router.post(BASE + "/{notice_id}/remind")
def remind_notice(case_id: str, hold_id: str, notice_id: str, body: NoticeReminder, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    row = _locked_notice(db, actor, case_id, hold_id, notice_id, body.expected_version)
    if row.state != "issued":
        fail(409, "HOLD_NOTICE_TRANSITION_INVALID", "Only an issued notice can have a reminder recorded.")
    values = {"reminder_count": row.reminder_count + 1, "last_reminded_by": actor.user.id, "last_reminded_at": now()}
    if "next_reminder_date" in body.model_fields_set:
        values["next_reminder_date"] = body.next_reminder_date
    return _apply(db, actor, request, case_id, hold_id, row, body, "reminded", values)


@router.get(BASE + "/{notice_id}/history")
def notice_history(case_id: str, hold_id: str, notice_id: str, limit: int = Query(default=50, ge=1, le=200), cursor: str | None = Query(default=None, max_length=36), actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    parent = _parent_query(actor.user, case_id, hold_id).cte("notice_parent")
    notice = select(HoldNotice.id).join(parent, parent.c.id == HoldNotice.hold_id).where(HoldNotice.id == notice_id, HoldNotice.tenant_id == actor.user.tenant_id, HoldNotice.case_id == case_id).cte("history_notice")
    events = select(Audit).join(notice, notice.c.id == Audit.target_id).where(Audit.tenant_id == actor.user.tenant_id, Audit.case_id == case_id, Audit.target_type == "hold_notice").cte("notice_events")
    page_query = select(events)
    if cursor:
        anchor = select(events.c.sequence).where(events.c.id == cursor).scalar_subquery()
        page_query = page_query.where(events.c.sequence < anchor)
    page = page_query.order_by(events.c.sequence.desc()).limit(limit + 1).cte("history_page")
    anchor_valid = select(events.c.id).where(events.c.id == cursor).exists() if cursor else true()
    rows = list(db.execute(select(anchor_valid.label("anchor_valid"), *page.c).select_from(notice).outerjoin(page, true()).order_by(page.c.sequence.desc())).mappings())
    if not rows:
        fail(404, "NOT_FOUND", "The hold notice is unavailable.")
    if not rows[0]["anchor_valid"]:
        fail(422, "HOLD_NOTICE_CURSOR_INVALID", "Restart the notice history with its current notice.")
    items = [{"id": row["id"], "event_type": row["event_type"], "actor_id": row["actor_id"], "created_at": utc(row["created_at"]).isoformat(), "version": row["metadata_json"].get("version"), "reason": row["metadata_json"].get("reason", ""), "metadata": row["metadata_json"]} for row in rows if row["id"] is not None]
    return {"items": items[:limit], "next_cursor": items[limit - 1]["id"] if len(items) > limit else None}
