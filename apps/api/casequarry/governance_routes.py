"""Audited matter preservation, issue mapping and task workflows."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import and_, select, update
from sqlalchemy.orm import Session, load_only

from . import audit
from .case_domain import lock_case_action
from .models import Case, Evidence, Hold, Issue, IssueLink, Member, Task, User, now
from .production_models import IssueReview
from .schemas import (
    DateOnly,
    HoldInput,
    Input,
    IssueInput,
    IssueLinkInput,
    Reason,
    TaskInput,
    TaskPriority,
    TaskText,
)
from .search import cursor_decode, cursor_encode
from .security import PERMISSIONS, Actor, authorize_case, current_actor, fail, get_db, utc
from .task_order import bump_created, bump_visible, creation_revision
from .time_zones import local_today

router = APIRouter(prefix="/api/v1")


class TaskPatch(Input):
    expected_version: int | None = Field(default=None, ge=1, strict=True)
    title: TaskText | None = Field(default=None, min_length=1, max_length=300)
    description: TaskText | None = Field(default=None, max_length=10000)
    priority: TaskPriority | None = None
    state: Literal["open", "in_progress", "done", "cancelled"] | None = None
    assigned_to: str | None = None
    due_date: DateOnly | None = None


class IssueReviewInput(Reason):
    expected_version: int = Field(ge=0)
    state: Literal["reviewed", "disputed", "needs_review"]


def _scoped(db, model, user, case_id, identifier):
    row = db.scalar(_visible_items(model, user, case_id).where(model.id == identifier))
    if row is None:
        fail(404, "NOT_FOUND", "The matter item is unavailable.")
    return row


def _page(db, model, user, case_id, limit, cursor):
    if not 1 <= limit <= 200:
        fail(422, "PAGE_SIZE_INVALID", "Choose a page size between 1 and 200.")
    query = _visible_items(model, user, case_id)
    if cursor:
        _scoped(db, model, user, case_id, cursor)
        query = query.where(model.id > cursor)
    rows = list(db.scalars(query.order_by(model.id).limit(limit + 1)))
    return rows[:limit], rows[limit - 1].id if len(rows) > limit else None


def _record(db, actor, request, case_id, event, model, row, metadata=None):
    audit.record(db, actor.user, case_id, event, model, row.id, metadata, getattr(request.state, "request_id", ""))
    db.commit()


def _reason(value):
    if len(value.strip()) < 3:
        fail(422, "REASON_REQUIRED", "Provide a meaningful reason for this action.")
    return value.strip()


def hold_json(row):
    return {"id": row.id, "name": row.name, "reason": row.reason, "state": row.state, "created_by": row.created_by, "released_by": row.released_by, "created_at": utc(row.created_at).isoformat()}


@router.get("/cases/{case_id}/holds")
def list_holds(case_id: str, limit: int = 50, cursor: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    rows, cursor = _page(db, Hold, actor.user, case_id, limit, cursor)
    return {"items": [hold_json(row) for row in rows], "next_cursor": cursor}


@router.post("/cases/{case_id}/holds", status_code=201)
def create_hold(case_id: str, body: HoldInput, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    lock_case_action(db, actor.user, case_id, "hold")
    row = Hold(tenant_id=actor.user.tenant_id, case_id=case_id, name=body.name.strip(), reason=_reason(body.reason), state="active", created_by=actor.user.id)
    if not row.name:
        fail(422, "HOLD_NAME_REQUIRED", "Provide a name for the preservation hold.")
    db.add(row)
    db.flush()
    _record(db, actor, request, case_id, "hold.activated", "hold", row)
    return hold_json(row)


@router.post("/cases/{case_id}/holds/{hold_id}/activate")
def activate_hold(case_id: str, hold_id: str, body: Reason, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    lock_case_action(db, actor.user, case_id, "hold")
    row = _scoped(db, Hold, actor.user, case_id, hold_id)
    reason = _reason(body.reason)
    if row.state == "active":
        _record(db, actor, request, case_id, "hold.activation_confirmed", "hold", row, {"reason": reason})
        return hold_json(row)
    if row.state != "draft":
        fail(409, "HOLD_TRANSITION_INVALID", "Only a draft hold can be activated. Create a new hold after release.")
    row.state = "active"
    _record(db, actor, request, case_id, "hold.activated", "hold", row, {"reason": reason})
    return hold_json(row)


@router.post("/cases/{case_id}/holds/{hold_id}/release")
def release_hold(case_id: str, hold_id: str, body: Reason, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    lock_case_action(db, actor.user, case_id, "hold")
    row = _scoped(db, Hold, actor.user, case_id, hold_id)
    reason = _reason(body.reason)
    if row.state != "active":
        fail(409, "HOLD_TRANSITION_INVALID", "Only an active hold can be released.")
    row.state, row.released_by = "released", actor.user.id
    _record(db, actor, request, case_id, "hold.released", "hold", row, {"reason": reason})
    return hold_json(row)


def _issue_evidence_snapshot(db, issue, require_limit=True, user=None):
    query = select(IssueLink, Evidence).options(load_only(Evidence.id, Evidence.review_version, Evidence.text_hash, Evidence.text_version)).join(Evidence, IssueLink.evidence_id == Evidence.id).where(IssueLink.issue_id == issue.id, IssueLink.tenant_id == issue.tenant_id, IssueLink.case_id == issue.case_id, Evidence.tenant_id == issue.tenant_id, Evidence.case_id == issue.case_id)
    if user is not None:
        authorized = _visible_case_query(user, issue.case_id).cte("authorized_issue_case")
        query = query.join(authorized, authorized.c.id == IssueLink.case_id)
    links = list(db.execute(query.order_by(IssueLink.id).limit(1001)))
    if len(links) > 1000:
        if require_limit:
            fail(413, "ISSUE_REVIEW_SCOPE_LIMIT", "Issue review supports at most 1,000 linked evidence items.")
        return {"_scope_exceeds_review_limit": True}
    return {link.id: {"evidence_id": item.id, "side": link.side, "note": link.note, "review_version": item.review_version, "text_hash": item.text_hash, "text_version": item.text_version} for link, item in links}


def issue_json(row, db=None, user=None):
    result = {"id": row.id, "title": row.title, "description": row.description, "created_by": row.created_by, "created_at": utc(row.created_at).isoformat()}
    if db is not None:
        query = select(IssueReview).where(IssueReview.issue_id == row.id, IssueReview.tenant_id == row.tenant_id, IssueReview.case_id == row.case_id)
        if user is not None:
            authorized = _visible_case_query(user, row.case_id).cte("authorized_issue_case")
            query = query.join(authorized, authorized.c.id == IssueReview.case_id)
        review = db.scalar(query)
        result["review"] = {"state": review.state, "version": review.version, "reviewed_by": review.reviewed_by, "reason": review.reason, "stale": review.evidence_snapshot != _issue_evidence_snapshot(db, row, require_limit=False, user=user)} if review else {"state": "needs_review", "version": 0, "stale": False}
    return result


@router.get("/cases/{case_id}/issues")
def list_issues(case_id: str, limit: int = 50, cursor: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    rows, cursor = _page(db, Issue, actor.user, case_id, limit, cursor)
    return {"items": [issue_json(row, db, actor.user) for row in rows], "next_cursor": cursor}


@router.post("/cases/{case_id}/issues", status_code=201)
def create_issue(case_id: str, body: IssueInput, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    lock_case_action(db, actor.user, case_id, "review")
    row = Issue(tenant_id=actor.user.tenant_id, case_id=case_id, title=body.title.strip(), description=body.description, created_by=actor.user.id)
    if not row.title:
        fail(422, "ISSUE_TITLE_REQUIRED", "Provide an issue title.")
    db.add(row)
    db.flush()
    _record(db, actor, request, case_id, "issue.created", "issue", row)
    return issue_json(row)


@router.get("/cases/{case_id}/issues/{issue_id}")
def get_issue(case_id: str, issue_id: str, limit: int = 100, cursor: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    row = _scoped(db, Issue, actor.user, case_id, issue_id)
    if not 1 <= limit <= 200:
        fail(422, "PAGE_SIZE_INVALID", "Choose a page size between 1 and 200.")
    query = select(IssueLink, Evidence.title).join(Evidence, IssueLink.evidence_id == Evidence.id).where(IssueLink.issue_id == row.id, IssueLink.tenant_id == actor.user.tenant_id, IssueLink.case_id == case_id, Evidence.tenant_id == actor.user.tenant_id, Evidence.case_id == case_id)
    authorized = _visible_case_query(actor.user, case_id).cte("authorized_issue_case")
    query = query.join(authorized, authorized.c.id == IssueLink.case_id)
    if cursor:
        anchor = _scoped(db, IssueLink, actor.user, case_id, cursor)
        if anchor.issue_id != issue_id:
            fail(422, "CURSOR_SCOPE_MISMATCH", "The cursor belongs to a different issue.")
        query = query.where(IssueLink.id > cursor)
    links = list(db.execute(query.order_by(IssueLink.id).limit(limit + 1)))
    return {**issue_json(row, db, actor.user), "evidence": [{"id": link.id, "evidence_id": link.evidence_id, "title": title, "side": link.side, "note": link.note, "created_by": link.created_by} for link, title in links[:limit]], "next_cursor": links[limit - 1][0].id if len(links) > limit else None}


@router.post("/cases/{case_id}/issues/{issue_id}/evidence", status_code=201)
def add_issue_evidence(case_id: str, issue_id: str, body: IssueLinkInput, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    lock_case_action(db, actor.user, case_id, "review")
    _scoped(db, Issue, actor.user, case_id, issue_id)
    _scoped(db, Evidence, actor.user, case_id, body.evidence_id)
    row = db.scalar(select(IssueLink).where(IssueLink.issue_id == issue_id, IssueLink.evidence_id == body.evidence_id, IssueLink.side == body.side, IssueLink.tenant_id == actor.user.tenant_id, IssueLink.case_id == case_id))
    if row is None:
        row = IssueLink(tenant_id=actor.user.tenant_id, case_id=case_id, issue_id=issue_id, evidence_id=body.evidence_id, side=body.side, note=body.note, created_by=actor.user.id)
        db.add(row)
        db.flush()
        _record(db, actor, request, case_id, "issue.evidence_added", "issue", row, {"evidence_id": body.evidence_id, "side": body.side})
    return {"id": row.id, "issue_id": issue_id, "evidence_id": row.evidence_id, "side": row.side, "note": row.note}


def task_json(row, *, detail=False):
    value = {"id": row.id, "case_id": row.case_id, "title": row.title, "state": row.state, "priority": row.priority, "assigned_to": row.assigned_to, "created_by": row.created_by, "created_at": utc(row.created_at).isoformat(), "updated_at": utc(row.updated_at).isoformat(), "version": row.version, "due_date": row.due_date.isoformat() if row.due_date else None}
    if detail:
        value["description"] = row.description
    return value


def task_detail_json(row, user):
    return {**task_json(row, detail=True), "server_today": local_today(user.time_zone, now()).isoformat(), "time_zone": user.time_zone}


def _visible_case_query(user, case_id):
    # Membership and account authority must remain true in the data statement,
    # including when they change after the preliminary authorize_case call.
    return select(Case.id).join(Member, and_(Member.case_id == Case.id, Member.tenant_id == Case.tenant_id, Member.user_id == user.id)).join(User, and_(User.id == Member.user_id, User.tenant_id == Member.tenant_id)).where(
        Case.id == case_id,
        Case.tenant_id == user.tenant_id, Member.tenant_id == user.tenant_id, User.tenant_id == user.tenant_id,
        User.active.is_(True), Member.role.in_(PERMISSIONS["view"]),
    )


def _visible_items(model, user, case_id):
    authorized = _visible_case_query(user, case_id).cte("authorized_matter")
    return select(model).join(authorized, authorized.c.id == model.case_id).where(model.tenant_id == user.tenant_id, model.case_id == case_id)


def _assignee(db, user, case_id, user_id):
    if user_id is None:
        return
    member = db.scalar(select(Member).join(User, Member.user_id == User.id).where(Member.tenant_id == user.tenant_id, Member.case_id == case_id, Member.user_id == user_id, Member.role.in_(PERMISSIONS["view"]), User.tenant_id == user.tenant_id, User.active.is_(True)).with_for_update(of=User, key_share=True))
    if member is None:
        fail(404, "NOT_FOUND", "The assigned matter member is unavailable.")


@router.get("/cases/{case_id}/tasks")
def list_tasks(case_id: str, request: Request, limit: int = Query(50, ge=1, le=200), cursor: str | None = Query(None, max_length=4096), actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    current, after, expected_revision = now(), None, None
    snapshot = current
    today = local_today(actor.user.time_zone, snapshot)
    scope = {"kind": "matter-tasks-v3", "tenant_id": actor.user.tenant_id, "user_id": actor.user.id, "case_id": case_id, "time_zone": actor.user.time_zone, "today": today.isoformat()}
    if cursor:
        payload = cursor_decode(cursor, request.app.state.cursor_secret)
        try:
            if not isinstance(payload, dict) or payload.get("scope") != scope:
                raise ValueError()
            snapshot = utc(datetime.fromisoformat(payload["snapshot"]))
            after = payload["after"]
            expected_revision = payload["revision"]
            if not isinstance(after, str) or not 1 <= len(after) <= 36 or snapshot > current or not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            fail(422, "TASK_CURSOR_INVALID", "Start the task list again; this cursor belongs to another scope.")
    authorized = _visible_case_query(actor.user, case_id).cte("authorized_task_case")
    query = select(Task.id, Task.case_id, Task.title, Task.state, Task.priority, Task.assigned_to, Task.created_by, Task.created_at, Task.updated_at, Task.version, Task.due_date).join(authorized, authorized.c.id == Task.case_id).where(Task.tenant_id == actor.user.tenant_id, Task.case_id == case_id, Task.created_at <= snapshot)
    if after:
        query = query.where(Task.id > after)
    page = query.order_by(Task.id).limit(limit + 1).cte("task_page")
    rows = db.execute(select(page, creation_revision(actor.user.tenant_id, case_id).label("creation_revision")).select_from(authorized.outerjoin(page, page.c.case_id == authorized.c.id)).order_by(page.c.id)).all()
    if cursor and rows and rows[0].creation_revision != expected_revision:
        fail(409, "TASK_LIST_CHANGED", "A task was created while paging. Restart the matter task list to include every task.")
    page_rows = [row for row in rows if row.id is not None]
    next_cursor = cursor_encode({"scope": scope, "snapshot": snapshot.isoformat(), "revision": rows[0].creation_revision, "after": page_rows[limit - 1].id}, request.app.state.cursor_secret) if len(page_rows) > limit else None
    return {"items": [task_json(row) for row in page_rows[:limit]], "next_cursor": next_cursor, "server_today": today.isoformat(), "time_zone": actor.user.time_zone}


@router.get("/cases/{case_id}/tasks/{task_id}")
def get_task(case_id: str, task_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    row = db.scalar(_visible_items(Task, actor.user, case_id).where(Task.id == task_id))
    if row is None:
        fail(404, "NOT_FOUND", "The matter task is unavailable.")
    return task_detail_json(row, actor.user)


@router.post("/cases/{case_id}/tasks", status_code=201)
def create_task(case_id: str, body: TaskInput, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    lock_case_action(db, actor.user, case_id, "review", (body.assigned_to,))
    _assignee(db, actor.user, case_id, body.assigned_to)
    created_at = now()
    row = Task(tenant_id=actor.user.tenant_id, case_id=case_id, title=body.title.strip(), description=body.description, priority=body.priority, assigned_to=body.assigned_to, created_by=actor.user.id, due_date=body.due_date, created_at=created_at, updated_at=created_at)
    if not row.title:
        fail(422, "TASK_TITLE_REQUIRED", "Provide a task title.")
    db.add(row)
    db.flush()
    bump_created(db, actor.user.tenant_id, case_id)
    bump_visible(db, actor.user.tenant_id, case_id, {row.assigned_to})
    _record(db, actor, request, case_id, "task.created", "task", row, {"assigned_to": row.assigned_to, "due_date": row.due_date.isoformat() if row.due_date else None, "priority": row.priority, "version": row.version})
    return task_detail_json(row, actor.user)


@router.patch("/cases/{case_id}/tasks/{task_id}")
def update_task(case_id: str, task_id: str, body: TaskPatch, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    lock_case_action(db, actor.user, case_id, "review", (body.assigned_to,))
    row = _scoped(db, Task, actor.user, case_id, task_id)
    if body.expected_version is None:
        fail(409, "TASK_VERSION_REQUIRED", "Reload the task and send its expected_version before editing.")
    if body.expected_version != row.version:
        fail(409, "TASK_VERSION_CONFLICT", "This task changed. Reload its current version before applying your draft.")
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    if not changes:
        fail(422, "TASK_CHANGE_REQUIRED", "Choose at least one task field to update.")
    before = {key: getattr(row, key) for key in changes}
    old_assignee, old_state, old_version = row.assigned_to, row.state, row.version
    if "assigned_to" in changes:
        _assignee(db, actor.user, case_id, changes["assigned_to"])
    for key, value in changes.items():
        if key in {"title", "state", "description", "priority"} and value is None:
            fail(422, "TASK_VALUE_INVALID", "Task title, state, description and priority cannot be null.")
        if key == "title":
            value = value.strip()
            if not value:
                fail(422, "TASK_TITLE_REQUIRED", "Provide a task title.")
        changes[key] = value
    if not db.execute(update(Task).where(Task.id == task_id, Task.tenant_id == actor.user.tenant_id, Task.case_id == case_id, Task.version == body.expected_version).values(**changes, version=old_version + 1, updated_at=now())).rowcount:
        fail(409, "TASK_VERSION_CONFLICT", "This task changed. Reload its current version before applying your draft.")
    db.refresh(row)
    def audit_value(value):
        return value.isoformat() if hasattr(value, "isoformat") else value

    after = {key: audit_value(getattr(row, key)) for key in changes}
    due_changed = "due_date" in changes and before["due_date"] != row.due_date
    triage_changed = any(key in changes and before[key] != getattr(row, key) for key in ("title", "priority"))
    entered_open_work = old_state not in {"open", "in_progress"} and row.state in {"open", "in_progress"}
    if (due_changed or triage_changed or old_assignee != row.assigned_to or entered_open_work) and (old_state in {"open", "in_progress"} or row.state in {"open", "in_progress"}):
        bump_visible(db, actor.user.tenant_id, case_id, {old_assignee, row.assigned_to})
    elif old_state != row.state and (old_state in {"open", "in_progress"} or row.state in {"open", "in_progress"}):
        bump_visible(db, actor.user.tenant_id, case_id, {old_assignee, row.assigned_to}, state_only=True)
    _record(db, actor, request, case_id, "task.updated", "task", row, {"fields": sorted(changes), "before": {key: audit_value(value) for key, value in before.items()}, "after": after, "due_date_changed": due_changed, "previous_version": old_version, "version": row.version})
    return task_detail_json(row, actor.user)


@router.post("/cases/{case_id}/issues/{issue_id}/review")
def review_issue(case_id: str, issue_id: str, body: IssueReviewInput, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    lock_case_action(db, actor.user, case_id, "review")
    if body.state == "reviewed":
        authorize_case(db, actor.user, case_id, "privilege")
    issue = _scoped(db, Issue, actor.user, case_id, issue_id)
    reason = _reason(body.reason)
    snapshot = _issue_evidence_snapshot(db, issue)
    if body.state == "reviewed" and not snapshot:
        fail(409, "ISSUE_EVIDENCE_REQUIRED", "Link supporting, contradicting or unclear evidence before marking the issue reviewed.")
    review = db.scalar(select(IssueReview).where(IssueReview.issue_id == issue.id, IssueReview.tenant_id == actor.user.tenant_id, IssueReview.case_id == case_id))
    if review is None:
        if body.expected_version != 0:
            fail(409, "ISSUE_REVIEW_CONFLICT", "The issue review changed; reload its current version.")
        review = IssueReview(tenant_id=actor.user.tenant_id, case_id=case_id, issue_id=issue.id, reviewed_by=actor.user.id, reason=reason, state=body.state, version=1, evidence_snapshot=snapshot)
        db.add(review)
        db.flush()
    elif not db.execute(update(IssueReview).where(IssueReview.id == review.id, IssueReview.version == body.expected_version).values(state=body.state, version=body.expected_version + 1, reviewed_by=actor.user.id, reason=reason, evidence_snapshot=snapshot)).rowcount:
        fail(409, "ISSUE_REVIEW_CONFLICT", "The issue review changed; reload its current version.")
    audit.record(db, actor.user, case_id, "issue.reviewed", "issue", issue.id, {"state": body.state, "version": body.expected_version + 1})
    db.commit()
    return issue_json(issue, db, actor.user)
