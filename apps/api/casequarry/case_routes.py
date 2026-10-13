from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.exc import IntegrityError

from . import audit
from .case_domain import lock_case_action
from .models import (
    Audit,
    Case,
    Custodian,
    Evidence,
    Hold,
    ImportBatch,
    Member,
    Occurrence,
    Original,
    Source,
    Task,
    User,
    now,
)
from .schemas import CaseInput, CasePatch, CustodianInput, MemberInput, Reason, SourceInput
from .search import cursor_decode, cursor_encode
from .security import PERMISSIONS, Actor, authorize_case, current_actor, fail, get_db, utc
from .task_order import bump_visible

router = APIRouter(prefix="/api/v1")


def case_json(case, role=None):
    return {"id": case.id, "matter_number": case.matter_number, "title": case.title, "description": case.description, "client": case.client, "jurisdiction": case.jurisdiction, "case_type": case.case_type, "created_at": utc(case.created_at).isoformat(), "updated_at": utc(case.updated_at).isoformat(), "archived_at": utc(case.archived_at).isoformat() if case.archived_at else None, "role": role}


def source_json(source):
    return {"id": source.id, "label": source.label, "kind": source.kind, "custodian_id": source.custodian_id, "operator_id": source.operator_id, "created_at": utc(source.created_at).isoformat()}


@router.get("/cases")
def list_cases(request: Request, archived: bool = False, limit: int = Query(100, ge=1, le=200), q: str = Query("", max_length=200), cursor: str | None = Query(None, max_length=4096), actor: Actor = Depends(current_actor), db=Depends(get_db)):
    statement = select(Case.id, Case.created_at, Member.role).join(Member, and_(Member.case_id == Case.id, Member.tenant_id == Case.tenant_id)).join(User, and_(User.id == Member.user_id, User.tenant_id == Member.tenant_id)).where(Case.tenant_id == actor.user.tenant_id, Member.tenant_id == actor.user.tenant_id, Member.user_id == actor.user.id, Member.role.in_(PERMISSIONS["view"]), User.active.is_(True))
    if not archived:
        statement = statement.where(Case.archived_at.is_(None))
    q = q.strip()
    if q:
        statement = statement.where(or_(Case.title.icontains(q, autoescape=True), Case.matter_number.icontains(q, autoescape=True), Case.client.icontains(q, autoescape=True)))
    scope = {"kind": "matters", "tenant": actor.user.tenant_id, "user": actor.user.id, "archived": archived, "q": q}
    snapshot = now()
    last = None
    if cursor:
        value = cursor_decode(cursor, request.app.state.cursor_secret)
        if not isinstance(value, dict) or value.get("scope") != scope:
            fail(422, "CURSOR_SCOPE_MISMATCH", "This cursor belongs to another account or matter filter. Start a new page.")
        try:
            snapshot = utc(datetime.fromisoformat(value["snapshot"]))
            last = utc(datetime.fromisoformat(value["created_at"]))
            identifier = value["id"]
            if not isinstance(identifier, str) or not 1 <= len(identifier) <= 36:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            fail(422, "INVALID_CURSOR", "The matter cursor is invalid. Start a new page.")
    statement = statement.where(Case.created_at <= snapshot)
    visible = statement.cte("visible_matters")
    counts = select(func.count().label("total")).select_from(visible).cte("matter_count")
    page = select(visible)
    if last:
        page = page.where(or_(visible.c.created_at < last, and_(visible.c.created_at == last, visible.c.id > identifier)))
    page = page.order_by(visible.c.created_at.desc(), visible.c.id).limit(limit + 1).cte("matter_page")
    rows = db.execute(select(Case, page.c.role, counts.c.total).select_from(counts.outerjoin(page, true()).outerjoin(Case, Case.id == page.c.id)).order_by(page.c.created_at.desc(), page.c.id)).all()
    total = rows[0][2]
    rows = [(matter, role) for matter, role, _ in rows if matter is not None]
    items = rows[:limit]
    next_cursor = cursor_encode({"scope": scope, "snapshot": snapshot.isoformat(), "created_at": utc(items[-1][0].created_at).isoformat(), "id": items[-1][0].id}, request.app.state.cursor_secret) if len(rows) > limit else None
    return {"items": [case_json(case, role) for case, role in items], "next_cursor": next_cursor, "truncated": len(rows) > limit, "total": total}


@router.post("/cases", status_code=201)
def create_case(body: CaseInput, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    db.refresh(actor.user, with_for_update=True)
    if not actor.user.active:
        fail(401, "ACCOUNT_DISABLED", "This account is unavailable.")
    if actor.user.role not in {"firm_admin", "attorney", "review_manager"}:
        fail(403, "PERMISSION_DENIED", "Your firm role does not allow matter creation.")
    case = Case(tenant_id=actor.user.tenant_id, created_by=actor.user.id, **body.model_dump())
    db.add(case)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        fail(409, "MATTER_NUMBER_EXISTS", "This matter number is already in use.")
    db.add(Member(tenant_id=actor.user.tenant_id, case_id=case.id, user_id=actor.user.id, role="matter_lead"))
    audit.record(db, actor.user, case.id, "matter.created", "case", case.id, request_id=request.state.request_id)
    db.commit()
    return case_json(case, "matter_lead")


@router.get("/cases/{case_id}")
def get_case(case_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    case, member = authorize_case(db, actor.user, case_id)
    return case_json(case, member.role)


@router.patch("/cases/{case_id}")
def patch_case(case_id: str, body: CasePatch, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    case, member = lock_case_action(db, actor.user, case_id, "manage")
    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(case, field, value)
    case.updated_at = now()
    audit.record(db, actor.user, case_id, "matter.updated", "case", case_id, {"fields": list(changes)}, request.state.request_id)
    db.commit()
    return case_json(case, member.role)


@router.post("/cases/{case_id}/archive")
def archive_case(case_id: str, body: Reason, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    case, member = lock_case_action(db, actor.user, case_id, "manage")
    if db.scalar(select(Hold.id).where(Hold.case_id == case_id, Hold.tenant_id == actor.user.tenant_id, Hold.state == "active").limit(1)):
        fail(409, "LEGAL_HOLD_ACTIVE", "An active legal hold prevents archiving this matter.")
    if case.archived_at is None:
        bump_visible(db, actor.user.tenant_id, case_id, _open_assignees(db, actor.user.tenant_id, case_id))
    case.archived_at, case.updated_at = now(), now()
    audit.record(db, actor.user, case_id, "matter.archived", "case", case_id, {"reason": body.reason}, request.state.request_id)
    db.commit()
    return case_json(case, member.role)


@router.post("/cases/{case_id}/restore")
def restore_case(case_id: str, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    case, member = lock_case_action(db, actor.user, case_id, "manage")
    was_archived = case.archived_at is not None
    case.archived_at, case.updated_at = None, now()
    if was_archived:
        db.flush()
        bump_visible(db, actor.user.tenant_id, case_id, _open_assignees(db, actor.user.tenant_id, case_id))
    audit.record(db, actor.user, case_id, "matter.restored", "case", case_id, request_id=request.state.request_id)
    db.commit()
    return case_json(case, member.role)


@router.get("/cases/{case_id}/stats")
def stats(case_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    scope = [Evidence.tenant_id == actor.user.tenant_id, Evidence.case_id == case_id]
    states = dict(db.execute(select(Evidence.parser_state, func.count()).where(*scope).group_by(Evidence.parser_state)).all())
    types = db.execute(select(Evidence.item_type, func.count()).where(*scope).group_by(Evidence.item_type)).all()
    reviews = db.execute(select(Evidence.review_status, func.count()).where(*scope).group_by(Evidence.review_status)).all()
    occurrences = db.scalar(select(func.count()).select_from(Occurrence).where(Occurrence.case_id == case_id, Occurrence.tenant_id == actor.user.tenant_id)) or 0
    originals, size = db.execute(select(func.count(), func.coalesce(func.sum(Original.byte_size), 0)).where(Original.case_id == case_id, Original.tenant_id == actor.user.tenant_id)).one()
    batches = dict(db.execute(select(ImportBatch.state, func.count()).where(ImportBatch.case_id == case_id, ImportBatch.tenant_id == actor.user.tenant_id).group_by(ImportBatch.state)).all())
    activity = db.scalars(select(Audit).where(Audit.case_id == case_id, Audit.tenant_id == actor.user.tenant_id).order_by(Audit.sequence.desc()).limit(8)).all()
    return {"evidence_items": sum(states.values()), "source_occurrences": occurrences, "unique_objects": originals, "indexed": states.get("indexed", 0), "reviewed": sum(count for value, count in reviews if value != "unreviewed"), "duplicates": occurrences - originals, "total_bytes": size, "processing": {key: states.get(key, 0) for key in ("pending", "stored", "indexed", "failed", "unsupported", "partial", "quarantined", "locked")}, "imports": batches, "types": [{"key": key, "count": count} for key, count in types], "review_status": [{"key": key, "count": count} for key, count in reviews], "recent_activity": [audit.event_json(event) for event in activity], "scale_validated": False}


@router.get("/cases/{case_id}/members")
def members(case_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    rows = db.execute(select(Member, User).join(User, Member.user_id == User.id).where(Member.case_id == case_id, Member.tenant_id == actor.user.tenant_id, User.tenant_id == actor.user.tenant_id)).all()
    return {"items": [{"id": member.id, "user_id": user.id, "email": user.email, "name": user.name, "role": member.role, "active": user.active} for member, user in rows]}


def _active_leads(db, tenant_id, case_id):
    return db.scalar(select(func.count()).select_from(Member).join(User, and_(User.id == Member.user_id, User.tenant_id == Member.tenant_id)).where(Member.tenant_id == tenant_id, Member.case_id == case_id, Member.role == "matter_lead", User.active.is_(True))) or 0


def _open_assignees(db, tenant_id, case_id):
    return db.scalars(select(Task.assigned_to).where(Task.tenant_id == tenant_id, Task.case_id == case_id, Task.assigned_to.is_not(None), Task.state.in_(("open", "in_progress"))).distinct()).all()


@router.post("/cases/{case_id}/members", status_code=201)
def add_member(case_id: str, body: MemberInput, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    lock_case_action(db, actor.user, case_id, "manage", (body.user_id,))
    user = db.scalar(select(User).where(User.id == body.user_id, User.tenant_id == actor.user.tenant_id, User.active.is_(True)).with_for_update(key_share=True))
    if not user:
        fail(404, "NOT_FOUND", "This team member is unavailable.")
    member = db.scalar(select(Member).where(Member.case_id == case_id, Member.user_id == user.id, Member.tenant_id == actor.user.tenant_id))
    if member and member.role == "matter_lead" and body.role != "matter_lead" and _active_leads(db, actor.user.tenant_id, case_id) <= 1:
        fail(409, "LAST_MATTER_LEAD", "Assign another active matter lead before changing this role.")
    if not member:
        member = Member(tenant_id=actor.user.tenant_id, case_id=case_id, user_id=user.id, role=body.role)
        db.add(member)
    else:
        member.role = body.role
    db.flush()
    bump_visible(db, actor.user.tenant_id, case_id, {user.id})
    audit.record(db, actor.user, case_id, "member.granted", "user", user.id, {"role": body.role}, request.state.request_id)
    db.commit()
    return {"id": member.id, "user_id": user.id, "name": user.name, "email": user.email, "role": member.role}


@router.delete("/cases/{case_id}/members/{user_id}")
def remove_member(case_id: str, user_id: str, body: Reason, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    lock_case_action(db, actor.user, case_id, "manage", (user_id,))
    member = db.scalar(select(Member).where(Member.case_id == case_id, Member.user_id == user_id, Member.tenant_id == actor.user.tenant_id))
    if not member:
        fail(404, "NOT_FOUND", "This team member is unavailable.")
    user = db.scalar(select(User).where(User.id == user_id, User.tenant_id == actor.user.tenant_id).with_for_update(key_share=True))
    if member.role == "matter_lead" and user and user.active and _active_leads(db, actor.user.tenant_id, case_id) <= 1:
        fail(409, "LAST_MATTER_LEAD", "Assign another active matter lead before removing this member.")
    bump_visible(db, actor.user.tenant_id, case_id, {user_id})
    db.delete(member)
    audit.record(db, actor.user, case_id, "member.revoked", "user", user_id, {"reason": body.reason}, request.state.request_id)
    db.commit()
    return {"ok": True}


@router.get("/cases/{case_id}/custodians")
def custodians(case_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    return {"items": [{"id": item.id, "display_name": item.display_name, "organization": item.organization} for item in db.scalars(select(Custodian).where(Custodian.case_id == case_id, Custodian.tenant_id == actor.user.tenant_id).order_by(Custodian.display_name))]}


@router.post("/cases/{case_id}/custodians", status_code=201)
def add_custodian(case_id: str, body: CustodianInput, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    authorize_case(db, actor.user, case_id, "import")
    custodian = Custodian(tenant_id=actor.user.tenant_id, case_id=case_id, **body.model_dump())
    db.add(custodian)
    db.flush()
    audit.record(db, actor.user, case_id, "custodian.created", "custodian", custodian.id, request_id=request.state.request_id)
    db.commit()
    return {"id": custodian.id, "display_name": custodian.display_name, "organization": custodian.organization}


@router.get("/cases/{case_id}/sources")
def sources(case_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    return {"items": [source_json(source) for source in db.scalars(select(Source).where(Source.case_id == case_id, Source.tenant_id == actor.user.tenant_id).order_by(Source.created_at.desc()))]}


@router.post("/cases/{case_id}/sources", status_code=201)
def add_source(case_id: str, body: SourceInput, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    authorize_case(db, actor.user, case_id, "import")
    if body.custodian_id and not db.scalar(select(Custodian.id).where(Custodian.id == body.custodian_id, Custodian.case_id == case_id, Custodian.tenant_id == actor.user.tenant_id)):
        fail(404, "NOT_FOUND", "This custodian is unavailable.")
    source = Source(tenant_id=actor.user.tenant_id, case_id=case_id, operator_id=actor.user.id, **body.model_dump())
    db.add(source)
    db.flush()
    audit.record(db, actor.user, case_id, "source.created", "source", source.id, request_id=request.state.request_id)
    db.commit()
    return source_json(source)
