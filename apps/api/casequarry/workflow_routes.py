"""Bounded, versioned review assignments with exclusive active allocations."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from . import audit
from .evidence_routes import apply_review
from .models import Evidence, Member, Original, ReviewSet, ReviewSetItem, User, now
from .schemas import Reason, ReviewInput
from .search import evidence_json
from .security import PERMISSIONS, Actor, authorize_case, current_actor, fail, get_db, utc
from .workflow_models import ActiveAllocation, AssignmentItem, ReviewAssignment

router = APIRouter(prefix="/api/v1")
REVIEWED = {"responsive", "non_responsive"}


class AssignmentInput(Reason):
    title: str = Field(min_length=1, max_length=200)
    assignee_id: str | None = Field(default=None, max_length=36)
    review_set_id: str | None = Field(default=None, max_length=36)
    evidence_ids: list[str] | None = Field(default=None, min_length=1, max_length=500)


class AssignmentAction(Reason):
    expected_version: int = Field(ge=0)


def get_assignment(db, user, case_id, assignment_id):
    authorize_case(db, user, case_id)
    row = db.scalar(
        select(ReviewAssignment).where(
            ReviewAssignment.id == assignment_id,
            ReviewAssignment.tenant_id == user.tenant_id,
            ReviewAssignment.case_id == case_id,
        )
    )
    if row is None:
        fail(404, "NOT_FOUND", "This review assignment is unavailable.")
    return row


def counts(db, row):
    scope = select(AssignmentItem.evidence_id).where(
        AssignmentItem.assignment_id == row.id,
        AssignmentItem.tenant_id == row.tenant_id,
        AssignmentItem.case_id == row.case_id,
    )
    condition = (Evidence.id.in_(scope), Evidence.tenant_id == row.tenant_id, Evidence.case_id == row.case_id)
    total = db.scalar(select(func.count()).select_from(Evidence).where(*condition)) or 0
    reviewed = (
        db.scalar(
            select(func.count()).select_from(Evidence).where(*condition, Evidence.review_status.in_(REVIEWED))
        )
        or 0
    )
    return {"total": total, "reviewed": reviewed, "pending": total - reviewed}


def assignment_json(db, row):
    user = db.get(User, row.assignee_id) if row.assignee_id else None
    return {
        "id": row.id,
        "title": row.title,
        "case_id": row.case_id,
        "state": row.state,
        "version": row.version,
        "assignee_id": row.assignee_id,
        "assignee": {"id": user.id, "name": user.name, "active": user.active}
        if user and user.tenant_id == row.tenant_id
        else None,
        "created_by": row.created_by,
        "review_set_id": row.review_set_id,
        "counts": counts(db, row),
        "reason": row.reason,
        "created_at": utc(row.created_at).isoformat(),
        "updated_at": utc(row.updated_at).isoformat(),
        "completed_at": utc(row.completed_at).isoformat() if row.completed_at else None,
        "scope_type": "snapshot",
    }


def reviewer(db, user, case_id, identifier):
    person = db.scalar(
        select(User)
        .join(Member, Member.user_id == User.id)
        .where(
            User.id == identifier,
            User.active.is_(True),
            User.tenant_id == user.tenant_id,
            Member.tenant_id == user.tenant_id,
            Member.case_id == case_id,
            Member.role.in_(PERMISSIONS["review"]),
        )
    )
    if person is None:
        fail(404, "ASSIGNEE_UNAVAILABLE", "Choose an active matter member with review permission.")
    return person


def assignment_items(db, row):
    scope = select(AssignmentItem.evidence_id).where(
        AssignmentItem.assignment_id == row.id,
        AssignmentItem.tenant_id == row.tenant_id,
        AssignmentItem.case_id == row.case_id,
    )
    return list(
        db.scalars(
            select(Evidence)
            .where(
                Evidence.id.in_(scope), Evidence.tenant_id == row.tenant_id, Evidence.case_id == row.case_id
            )
            .order_by(Evidence.id)
            .with_for_update()
        )
    )


def set_assignee(db, user, case_id, items, assignee_id, request_id):
    for item in items:
        if assignee_id:
            apply_review(
                db,
                user,
                case_id,
                item,
                ReviewInput(assigned_to=assignee_id, expected_version=item.review_version),
                request_id,
                assignment_authorized=True,
            )
        else:
            # Null is an explicit release, distinct from omitting a review change.
            expected = item.review_version
            result = db.execute(
                update(Evidence)
                .where(
                    Evidence.id == item.id,
                    Evidence.tenant_id == user.tenant_id,
                    Evidence.case_id == case_id,
                    Evidence.review_version == expected,
                )
                .values(assigned_to=None, review_version=expected + 1)
            )
            if result.rowcount != 1:
                fail(
                    409,
                    "REVIEW_VERSION_CONFLICT",
                    "Evidence changed while releasing its allocation. Refresh and retry.",
                )
            audit.record(
                db,
                user,
                case_id,
                "evidence.assignment_released",
                "evidence",
                item.id,
                {"version": expected + 1},
                request_id,
            )


@router.get("/cases/{case_id}/assignments")
def list_assignments(
    case_id: str,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None, max_length=36),
    mine: bool = False,
    open_only: bool = False,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    authorize_case(db, actor.user, case_id)
    query = select(ReviewAssignment).where(
        ReviewAssignment.tenant_id == actor.user.tenant_id, ReviewAssignment.case_id == case_id
    )
    if mine:
        query = query.where(ReviewAssignment.assignee_id == actor.user.id)
    if open_only:
        query = query.where(ReviewAssignment.state.in_({"unassigned", "assigned"}))
    if cursor:
        get_assignment(db, actor.user, case_id, cursor)
        query = query.where(ReviewAssignment.id > cursor)
    rows = list(db.scalars(query.order_by(ReviewAssignment.id).limit(limit + 1)))
    return {
        "items": [assignment_json(db, row) for row in rows[:limit]],
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
        "limit": limit,
    }


@router.post("/cases/{case_id}/assignments", status_code=201)
def create_assignment(
    case_id: str,
    body: AssignmentInput,
    request: Request,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    authorize_case(db, actor.user, case_id, "manage")
    authorize_case(db, actor.user, case_id, "review")
    if bool(body.evidence_ids) == bool(body.review_set_id):
        fail(422, "ASSIGNMENT_SCOPE_REQUIRED", "Choose either evidence IDs or a review set.")
    if not body.title.strip() or len(body.reason.strip()) < 3:
        fail(422, "ASSIGNMENT_DETAILS_REQUIRED", "Provide a title and meaningful reason.")
    if body.assignee_id:
        reviewer(db, actor.user, case_id, body.assignee_id)
    if body.review_set_id:
        scope_set = db.scalar(
            select(ReviewSet).where(
                ReviewSet.id == body.review_set_id,
                ReviewSet.tenant_id == actor.user.tenant_id,
                ReviewSet.case_id == case_id,
            )
        )
        if scope_set is None:
            fail(404, "NOT_FOUND", "This review set is unavailable.")
        ids = list(
            db.scalars(
                select(ReviewSetItem.evidence_id)
                .where(
                    ReviewSetItem.set_id == scope_set.id,
                    ReviewSetItem.tenant_id == actor.user.tenant_id,
                    ReviewSetItem.case_id == case_id,
                )
                .order_by(ReviewSetItem.evidence_id)
                .limit(501)
            )
        )
    else:
        ids = list(dict.fromkeys(body.evidence_ids))
    if not ids or len(ids) > 500:
        fail(
            422,
            "ASSIGNMENT_SIZE_LIMIT",
            "Assignments contain between 1 and 500 items; split larger review sets.",
        )
    items = list(
        db.scalars(
            select(Evidence)
            .where(
                Evidence.id.in_(ids), Evidence.tenant_id == actor.user.tenant_id, Evidence.case_id == case_id
            )
            .order_by(Evidence.id)
            .with_for_update()
        )
    )
    if len(items) != len(ids):
        fail(404, "NOT_FOUND", "Some selected evidence is unavailable in this matter.")
    if db.scalar(select(ActiveAllocation.evidence_id).where(ActiveAllocation.evidence_id.in_(ids)).limit(1)):
        fail(409, "ASSIGNMENT_OVERLAP", "Some selected items already belong to an active assignment.")
    row = ReviewAssignment(
        tenant_id=actor.user.tenant_id,
        case_id=case_id,
        title=body.title.strip(),
        assignee_id=body.assignee_id,
        created_by=actor.user.id,
        review_set_id=body.review_set_id,
        state="assigned" if body.assignee_id else "unassigned",
        reason=body.reason.strip(),
    )
    db.add(row)
    db.flush()
    db.add_all(
        [
            AssignmentItem(
                tenant_id=row.tenant_id, case_id=case_id, assignment_id=row.id, evidence_id=item.id
            )
            for item in items
        ]
    )
    db.add_all(
        [
            ActiveAllocation(
                tenant_id=row.tenant_id, case_id=case_id, assignment_id=row.id, evidence_id=item.id
            )
            for item in items
        ]
    )
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        fail(409, "ASSIGNMENT_OVERLAP", "Another manager allocated this evidence. Refresh and retry.")
    set_assignee(db, actor.user, case_id, items, body.assignee_id, request.state.request_id)
    audit.record(
        db,
        actor.user,
        case_id,
        "assignment.created",
        "assignment",
        row.id,
        {"count": len(ids), "assignee_id": body.assignee_id, "review_set_id": body.review_set_id},
        request.state.request_id,
    )
    db.commit()
    return assignment_json(db, row)


@router.get("/cases/{case_id}/assignments/{assignment_id}")
def assignment_detail(
    case_id: str, assignment_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)
):
    return assignment_json(db, get_assignment(db, actor.user, case_id, assignment_id))


@router.get("/cases/{case_id}/assignments/{assignment_id}/items")
def items_page(
    case_id: str,
    assignment_id: str,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None, max_length=36),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    row = get_assignment(db, actor.user, case_id, assignment_id)
    scope = select(AssignmentItem.evidence_id).where(
        AssignmentItem.assignment_id == row.id,
        AssignmentItem.tenant_id == row.tenant_id,
        AssignmentItem.case_id == case_id,
    )
    query = (
        select(Evidence, Original)
        .join(Original, Original.id == Evidence.original_id)
        .where(Evidence.id.in_(scope), Evidence.tenant_id == row.tenant_id, Evidence.case_id == case_id)
    )
    if cursor:
        if not db.scalar(
            select(AssignmentItem.evidence_id).where(
                AssignmentItem.assignment_id == row.id, AssignmentItem.evidence_id == cursor
            )
        ):
            fail(404, "NOT_FOUND", "This assignment cursor is unavailable.")
        query = query.where(Evidence.id > cursor)
    rows = list(db.execute(query.order_by(Evidence.id).limit(limit + 1)))
    return {
        "items": [evidence_json(item, original) for item, original in rows[:limit]],
        "next_cursor": rows[limit - 1][0].id if len(rows) > limit else None,
        "assignment_id": row.id,
    }


@router.post("/cases/{case_id}/assignments/{assignment_id}/{action}")
def transition(
    case_id: str,
    assignment_id: str,
    action: Literal["claim", "release", "complete", "cancel"],
    body: AssignmentAction,
    request: Request,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    _case, member = authorize_case(db, actor.user, case_id, "review")
    row = get_assignment(db, actor.user, case_id, assignment_id)
    if row.version != body.expected_version:
        fail(
            409,
            "ASSIGNMENT_VERSION_CONFLICT",
            "Another reviewer changed this assignment. Refresh before acting.",
        )
    manager = member.role in PERMISSIONS["manage"]
    if row.state not in {"assigned", "unassigned"}:
        fail(409, "ASSIGNMENT_CLOSED", "This assignment is already closed.")
    if action == "claim":
        if row.state != "unassigned" or row.assignee_id:
            fail(409, "ASSIGNMENT_CLAIMED", "Another reviewer owns this assignment.")
        reviewer(db, actor.user, case_id, actor.user.id)
        changes = {"state": "assigned", "assignee_id": actor.user.id}
    else:
        if (
            action == "cancel"
            and not manager
            or action != "cancel"
            and row.assignee_id != actor.user.id
            and not manager
        ):
            fail(
                403, "PERMISSION_DENIED", "Only its assignee or a matter manager may change this allocation."
            )
        if action == "complete" and (row.state != "assigned" or counts(db, row)["pending"]):
            fail(
                409,
                "ASSIGNMENT_REVIEW_INCOMPLETE",
                "Review every selected item before completing its assignment.",
            )
        changes = {"state": {"release": "unassigned", "complete": "completed", "cancel": "cancelled"}[action]}
        if action == "release":
            changes["assignee_id"] = None
        if action == "complete":
            changes["completed_at"] = now()
    result = db.execute(
        update(ReviewAssignment)
        .where(
            ReviewAssignment.id == row.id,
            ReviewAssignment.tenant_id == actor.user.tenant_id,
            ReviewAssignment.case_id == case_id,
            ReviewAssignment.version == body.expected_version,
        )
        .values(**changes, version=body.expected_version + 1, updated_at=now())
    )
    if result.rowcount != 1:
        fail(
            409, "ASSIGNMENT_VERSION_CONFLICT", "Another reviewer changed this assignment. Refresh and retry."
        )
    items = assignment_items(db, row)
    if action == "complete" and any(item.review_status not in REVIEWED for item in items):
        fail(
            409,
            "ASSIGNMENT_REVIEW_INCOMPLETE",
            "Evidence changed before completion. Review the pending items first.",
        )
    if action in {"claim", "release", "cancel"}:
        set_assignee(
            db,
            actor.user,
            case_id,
            items,
            actor.user.id if action == "claim" else None,
            request.state.request_id,
        )
    if action in {"complete", "cancel"}:
        db.execute(
            delete(ActiveAllocation).where(
                ActiveAllocation.assignment_id == row.id,
                ActiveAllocation.tenant_id == row.tenant_id,
                ActiveAllocation.case_id == case_id,
            )
        )
    audit.record(
        db,
        actor.user,
        case_id,
        f"assignment.{action}",
        "assignment",
        row.id,
        {"version": body.expected_version + 1, "reason": body.reason},
        request.state.request_id,
    )
    db.commit()
    db.refresh(row)
    return assignment_json(db, row)
