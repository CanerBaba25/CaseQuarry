"""Current-user assigned work and date-only planning across accessible matters."""

from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, case, func, or_, select, true
from sqlalchemy.orm import Session

from .models import Case, Member, Task, User, now
from .search import cursor_decode, cursor_encode
from .security import PERMISSIONS, Actor, current_actor, fail, get_db, utc
from .task_order import revision_expression
from .time_zones import local_today

router = APIRouter(prefix="/api/v1")


def _visible(statement, tenant_id, user_id):
    return (
        statement
        .join(Case, and_(Case.id == Task.case_id, Case.tenant_id == Task.tenant_id))
        .join(Member, and_(Member.case_id == Case.id, Member.tenant_id == Case.tenant_id, Member.user_id == user_id))
        .join(User, and_(User.id == Member.user_id, User.tenant_id == Member.tenant_id))
        .where(
            Task.tenant_id == tenant_id, Case.tenant_id == tenant_id,
            Member.tenant_id == tenant_id, User.tenant_id == tenant_id,
            User.id == user_id, User.active.is_(True),
            Member.role.in_(PERMISSIONS["view"]), Case.archived_at.is_(None), Task.assigned_to == user_id,
        )
    )


@router.get("/worklist")
def my_work(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None, max_length=4096),
    due: Literal["all", "overdue", "upcoming", "no_due"] = "all",
    actor: Actor = Depends(current_actor),
    db: Session = Depends(get_db),
):
    tenant_id, user_id = actor.user.tenant_id, actor.user.id
    current = now()
    today, snapshot = local_today(actor.user.time_zone, current), current
    scope = {"kind": "my-work-v2", "tenant_id": tenant_id, "user_id": user_id, "due": due, "today": today.isoformat(), "time_zone": actor.user.time_zone, "order": "due-matter-id"}
    after = None
    expected_revision = None
    if cursor:
        payload = cursor_decode(cursor, request.app.state.cursor_secret)
        try:
            if not isinstance(payload, dict) or payload.get("scope") != scope:
                raise ValueError()
            snapshot = utc(datetime.fromisoformat(payload["snapshot"]))
            after = payload["after"]
            expected_revision = payload["revision"]
            if (
                not isinstance(after, list) or len(after) != 3
                or any(not isinstance(value, str) or not 1 <= len(value) <= 36 for value in after[1:])
                or after[0] is not None and (not isinstance(after[0], str) or len(after[0]) != 10)
                or snapshot > current
                or not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0
            ):
                raise ValueError()
            after = [date.fromisoformat(after[0]) if after[0] else None, after[1], after[2]]
        except (KeyError, ValueError, TypeError):
            fail(422, "WORKLIST_CURSOR_INVALID", "Start your work list again; this page cursor belongs to another account, filter or date window.")
    # Summaries and page rows use one SQL snapshot of current authorization.
    # Summaries include every currently visible open task, independent of page/filter.
    visible = _visible(
        select(
            Task.id, Task.title, Task.state, Task.created_at, Task.due_date,
            Task.assigned_to, Task.created_by, Case.id.label("matter_id"),
            Case.matter_number, Case.title.label("matter_title"), Member.role,
        ).select_from(Task), tenant_id, user_id,
    ).where(Task.state.in_(("open", "in_progress"))).cte("visible_work")
    upcoming_end = today + timedelta(days=7)
    overdue = visible.c.due_date < today
    upcoming = visible.c.due_date.between(today, upcoming_end)
    undated = visible.c.due_date.is_(None)
    summary = select(
        func.count().label("total"),
        func.coalesce(func.sum(case((overdue, 1), else_=0)), 0).label("overdue"),
        func.coalesce(func.sum(case((upcoming, 1), else_=0)), 0).label("upcoming"),
        func.coalesce(func.sum(case((undated, 1), else_=0)), 0).label("no_due"),
    ).select_from(visible).cte("work_summary")
    page_query = select(visible).where(visible.c.created_at <= snapshot)
    if due != "all":
        page_query = page_query.where({"overdue": overdue, "upcoming": upcoming, "no_due": undated}[due])
    if after:
        deadline, matter_id, task_id = after
        after_id = or_(visible.c.matter_id > matter_id, and_(visible.c.matter_id == matter_id, visible.c.id > task_id))
        if deadline is None:
            page_query = page_query.where(undated, after_id)
        else:
            page_query = page_query.where(or_(visible.c.due_date > deadline, undated, and_(visible.c.due_date == deadline, after_id)))
    page = page_query.order_by(visible.c.due_date.asc().nulls_last(), visible.c.matter_id, visible.c.id).limit(limit + 1).cte("work_page")
    # A committed edit may have an earlier timestamp than page one. Capture its
    # transactional revision with the rows, rather than relying on wall-clock order.
    statement = select(summary, page, revision_expression(tenant_id, user_id).label("order_revision")).select_from(summary.outerjoin(page, true()))
    statement = statement.order_by(page.c.due_date.asc().nulls_last(), page.c.matter_id, page.c.id)
    rows = db.execute(statement).mappings().all()
    if cursor and rows[0]["order_revision"] != expected_revision:
        fail(409, "WORKLIST_CHANGED", "Task deadlines, assignments or access changed while paging. Refresh your work list to use the current order.")
    counts = {key: rows[0][key] for key in ("total", "overdue", "upcoming", "no_due")}
    page_rows = [row for row in rows if row["id"] is not None]
    items = [
        {
            "id": row["id"], "title": row["title"], "state": row["state"],
            "created_at": utc(row["created_at"]).isoformat(),
            "due_date": row["due_date"].isoformat() if row["due_date"] else None,
            "assigned_to": row["assigned_to"], "created_by": row["created_by"],
            "matter": {"id": row["matter_id"], "matter_number": row["matter_number"], "title": row["matter_title"], "role": row["role"]},
        }
        for row in page_rows[:limit]
    ]
    next_cursor = None
    if len(page_rows) > limit:
        row = page_rows[limit - 1]
        next_cursor = cursor_encode(
            {"scope": scope, "snapshot": snapshot.isoformat(), "revision": rows[0]["order_revision"], "after": [row["due_date"].isoformat() if row["due_date"] else None, row["matter_id"], row["id"]]},
            request.app.state.cursor_secret,
        )
    return {"user_id": user_id, "items": items, "next_cursor": next_cursor, "limit": limit, "due": due, "server_today": today.isoformat(), "time_zone": actor.user.time_zone, "summary": counts}
