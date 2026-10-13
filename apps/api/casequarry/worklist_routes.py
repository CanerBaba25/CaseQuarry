"""Current-user work across explicitly accessible, active matters."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .models import Case, Member, Task, User
from .search import cursor_decode, cursor_encode
from .security import PERMISSIONS, Actor, current_actor, fail, get_db, utc

router = APIRouter(prefix="/api/v1")


@router.get("/worklist")
def my_work(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1024),
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    tenant_id, user_id = actor.user.tenant_id, actor.user.id
    query = (
        select(Task, Case, Member.role)
        .join(Case, and_(Case.id == Task.case_id, Case.tenant_id == Task.tenant_id))
        .join(
            Member,
            and_(
                Member.case_id == Case.id,
                Member.tenant_id == Case.tenant_id,
                Member.user_id == user_id,
            ),
        )
        .join(User, and_(User.id == Member.user_id, User.tenant_id == Member.tenant_id))
        .where(
            Task.tenant_id == tenant_id,
            Case.tenant_id == tenant_id,
            Member.tenant_id == tenant_id,
            User.tenant_id == tenant_id,
            User.id == user_id,
            User.active.is_(True),
            Member.role.in_(PERMISSIONS["view"]),
            Case.archived_at.is_(None),
            Task.assigned_to == user_id,
            Task.state.in_(("open", "in_progress")),
        )
    )
    if cursor:
        payload = cursor_decode(cursor, request.app.state.cursor_secret)
        if (
            not isinstance(payload, dict)
            or payload.get("scope") != "my-work-v1"
            or payload.get("tenant_id") != tenant_id
            or payload.get("user_id") != user_id
            or not isinstance(payload.get("after"), list)
            or len(payload["after"]) != 2
            or any(not isinstance(value, str) or not 1 <= len(value) <= 36 for value in payload["after"])
        ):
            fail(
                422,
                "WORKLIST_CURSOR_INVALID",
                "Start your work list again; this page cursor belongs to another scope.",
            )
        case_after, task_after = payload["after"]
        query = query.where(or_(Case.id > case_after, and_(Case.id == case_after, Task.id > task_after)))
    rows = list(db.execute(query.order_by(Case.id, Task.id).limit(limit + 1)))
    items = [
        {
            "id": task.id,
            "title": task.title,
            "state": task.state,
            "created_at": utc(task.created_at).isoformat(),
            "matter": {
                "id": matter.id,
                "matter_number": matter.matter_number,
                "title": matter.title,
                "role": role,
            },
        }
        for task, matter, role in rows[:limit]
    ]
    next_cursor = None
    if len(rows) > limit:
        task, matter, _ = rows[limit - 1]
        next_cursor = cursor_encode(
            {
                "scope": "my-work-v1",
                "tenant_id": tenant_id,
                "user_id": user_id,
                "after": [matter.id, task.id],
            },
            request.app.state.cursor_secret,
        )
    return {"user_id": user_id, "items": items, "next_cursor": next_cursor, "limit": limit}
