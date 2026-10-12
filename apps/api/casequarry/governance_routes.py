"""Audited matter preservation, issue mapping and task workflows."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session, load_only

from . import audit
from .models import Evidence, Hold, Issue, IssueLink, Member, Task, User
from .production_models import IssueReview
from .schemas import HoldInput, Input, IssueInput, IssueLinkInput, Reason, TaskInput
from .security import Actor, authorize_case, current_actor, fail, get_db, utc

router = APIRouter(prefix="/api/v1")


class TaskPatch(Input):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    state: Literal["open", "in_progress", "done", "cancelled"] | None = None
    assigned_to: str | None = None


class IssueReviewInput(Reason):
    expected_version: int = Field(ge=0)
    state: Literal["reviewed", "disputed", "needs_review"]


def _scoped(db, model, user, case_id, identifier):
    row = db.scalar(select(model).where(model.id == identifier, model.tenant_id == user.tenant_id, model.case_id == case_id))
    if row is None:
        fail(404, "NOT_FOUND", "The matter item is unavailable.")
    return row


def _page(db, model, user, case_id, limit, cursor):
    if not 1 <= limit <= 200:
        fail(422, "PAGE_SIZE_INVALID", "Choose a page size between 1 and 200.")
    query = select(model).where(model.tenant_id == user.tenant_id, model.case_id == case_id)
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
    authorize_case(db, actor.user, case_id, "hold")
    row = Hold(tenant_id=actor.user.tenant_id, case_id=case_id, name=body.name.strip(), reason=_reason(body.reason), state="active", created_by=actor.user.id)
    if not row.name:
        fail(422, "HOLD_NAME_REQUIRED", "Provide a name for the preservation hold.")
    db.add(row)
    db.flush()
    _record(db, actor, request, case_id, "hold.activated", "hold", row)
    return hold_json(row)


@router.post("/cases/{case_id}/holds/{hold_id}/activate")
def activate_hold(case_id: str, hold_id: str, body: Reason, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id, "hold")
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
    authorize_case(db, actor.user, case_id, "hold")
    row = _scoped(db, Hold, actor.user, case_id, hold_id)
    reason = _reason(body.reason)
    if row.state != "active":
        fail(409, "HOLD_TRANSITION_INVALID", "Only an active hold can be released.")
    row.state, row.released_by = "released", actor.user.id
    _record(db, actor, request, case_id, "hold.released", "hold", row, {"reason": reason})
    return hold_json(row)


def _issue_evidence_snapshot(db, issue, require_limit=True):
    links = list(db.execute(select(IssueLink, Evidence).options(load_only(Evidence.id, Evidence.review_version, Evidence.text_hash, Evidence.text_version)).join(Evidence, IssueLink.evidence_id == Evidence.id).where(IssueLink.issue_id == issue.id, IssueLink.tenant_id == issue.tenant_id, IssueLink.case_id == issue.case_id, Evidence.tenant_id == issue.tenant_id, Evidence.case_id == issue.case_id).order_by(IssueLink.id).limit(1001)))
    if len(links) > 1000:
        if require_limit:
            fail(413, "ISSUE_REVIEW_SCOPE_LIMIT", "Issue review supports at most 1,000 linked evidence items.")
        return {"_scope_exceeds_review_limit": True}
    return {link.id: {"evidence_id": item.id, "side": link.side, "note": link.note, "review_version": item.review_version, "text_hash": item.text_hash, "text_version": item.text_version} for link, item in links}


def issue_json(row, db=None):
    result = {"id": row.id, "title": row.title, "description": row.description, "created_by": row.created_by, "created_at": utc(row.created_at).isoformat()}
    if db is not None:
        review = db.scalar(select(IssueReview).where(IssueReview.issue_id == row.id, IssueReview.tenant_id == row.tenant_id, IssueReview.case_id == row.case_id))
        result["review"] = {"state": review.state, "version": review.version, "reviewed_by": review.reviewed_by, "reason": review.reason, "stale": review.evidence_snapshot != _issue_evidence_snapshot(db, row, require_limit=False)} if review else {"state": "needs_review", "version": 0, "stale": False}
    return result


@router.get("/cases/{case_id}/issues")
def list_issues(case_id: str, limit: int = 50, cursor: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    rows, cursor = _page(db, Issue, actor.user, case_id, limit, cursor)
    return {"items": [issue_json(row, db) for row in rows], "next_cursor": cursor}


@router.post("/cases/{case_id}/issues", status_code=201)
def create_issue(case_id: str, body: IssueInput, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id, "review")
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
    if cursor:
        anchor = _scoped(db, IssueLink, actor.user, case_id, cursor)
        if anchor.issue_id != issue_id:
            fail(422, "CURSOR_SCOPE_MISMATCH", "The cursor belongs to a different issue.")
        query = query.where(IssueLink.id > cursor)
    links = list(db.execute(query.order_by(IssueLink.id).limit(limit + 1)))
    return {**issue_json(row, db), "evidence": [{"id": link.id, "evidence_id": link.evidence_id, "title": title, "side": link.side, "note": link.note, "created_by": link.created_by} for link, title in links[:limit]], "next_cursor": links[limit - 1][0].id if len(links) > limit else None}


@router.post("/cases/{case_id}/issues/{issue_id}/evidence", status_code=201)
def add_issue_evidence(case_id: str, issue_id: str, body: IssueLinkInput, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id, "review")
    _scoped(db, Issue, actor.user, case_id, issue_id)
    _scoped(db, Evidence, actor.user, case_id, body.evidence_id)
    row = db.scalar(select(IssueLink).where(IssueLink.issue_id == issue_id, IssueLink.evidence_id == body.evidence_id, IssueLink.side == body.side, IssueLink.tenant_id == actor.user.tenant_id, IssueLink.case_id == case_id))
    if row is None:
        row = IssueLink(tenant_id=actor.user.tenant_id, case_id=case_id, issue_id=issue_id, evidence_id=body.evidence_id, side=body.side, note=body.note, created_by=actor.user.id)
        db.add(row)
        db.flush()
        _record(db, actor, request, case_id, "issue.evidence_added", "issue", row, {"evidence_id": body.evidence_id, "side": body.side})
    return {"id": row.id, "issue_id": issue_id, "evidence_id": row.evidence_id, "side": row.side, "note": row.note}


def task_json(row):
    return {"id": row.id, "title": row.title, "state": row.state, "assigned_to": row.assigned_to, "created_by": row.created_by, "created_at": utc(row.created_at).isoformat()}


def _assignee(db, user, case_id, user_id):
    if user_id is None:
        return
    member = db.scalar(select(Member).join(User, Member.user_id == User.id).where(Member.tenant_id == user.tenant_id, Member.case_id == case_id, Member.user_id == user_id, User.tenant_id == user.tenant_id, User.active.is_(True)))
    if member is None:
        fail(404, "NOT_FOUND", "The assigned matter member is unavailable.")


@router.get("/cases/{case_id}/tasks")
def list_tasks(case_id: str, limit: int = 50, cursor: str | None = None, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    rows, cursor = _page(db, Task, actor.user, case_id, limit, cursor)
    return {"items": [task_json(row) for row in rows], "next_cursor": cursor}


@router.post("/cases/{case_id}/tasks", status_code=201)
def create_task(case_id: str, body: TaskInput, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id, "review")
    _assignee(db, actor.user, case_id, body.assigned_to)
    row = Task(tenant_id=actor.user.tenant_id, case_id=case_id, title=body.title.strip(), assigned_to=body.assigned_to, created_by=actor.user.id)
    if not row.title:
        fail(422, "TASK_TITLE_REQUIRED", "Provide a task title.")
    db.add(row)
    db.flush()
    _record(db, actor, request, case_id, "task.created", "task", row, {"assigned_to": row.assigned_to})
    return task_json(row)


@router.patch("/cases/{case_id}/tasks/{task_id}")
def update_task(case_id: str, task_id: str, body: TaskPatch, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id, "review")
    row = _scoped(db, Task, actor.user, case_id, task_id)
    changes = body.model_dump(exclude_unset=True)
    if "assigned_to" in changes:
        _assignee(db, actor.user, case_id, changes["assigned_to"])
    for key, value in changes.items():
        if key in {"title", "state"} and value is None:
            fail(422, "TASK_VALUE_INVALID", "Task title and state cannot be empty.")
        if key == "title":
            value = value.strip()
            if not value:
                fail(422, "TASK_TITLE_REQUIRED", "Provide a task title.")
        setattr(row, key, value)
    _record(db, actor, request, case_id, "task.updated", "task", row, {"fields": sorted(changes)})
    return task_json(row)


@router.post("/cases/{case_id}/issues/{issue_id}/review")
def review_issue(case_id: str, issue_id: str, body: IssueReviewInput, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    authorize_case(db, actor.user, case_id, "privilege" if body.state == "reviewed" else "review")
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
    return issue_json(issue, db)
