from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy import case as sql_case
from sqlalchemy.orm import aliased

from . import audit
from .evidence_routes import get_item
from .models import Evidence, Participant, Person, now
from .schemas import Filters, SearchInput, Sort
from .search import cursor_decode, cursor_encode, parse_date, run_search
from .security import Actor, authorize_case, current_actor, fail, get_db, utc

router = APIRouter(prefix="/api/v1")
RECIPIENT_ROLES = ("to", "cc", "bcc")
COUNT_BASIS = "Preserved email source occurrences; unique_messages counts distinct byte-exact original objects. Header addresses are not verified human identities."


def scope(model, user, case_id):
    return [model.tenant_id == user.tenant_id, model.case_id == case_id]


def people_query(user, case_id):
    return (
        select(
            Person.id,
            Person.email,
            Person.name,
            Person.state,
            func.count(func.distinct(sql_case((Participant.role == "from", Evidence.id)))).label(
                "sent_count"
            ),
            func.count(func.distinct(sql_case((Participant.role.in_(RECIPIENT_ROLES), Evidence.id)))).label(
                "received_count"
            ),
            func.count(func.distinct(Evidence.id)).label("total_count"),
            func.count(func.distinct(Evidence.original_id)).label("unique_messages"),
        )
        .select_from(Person)
        .join(Participant, Participant.person_id == Person.id)
        .join(Evidence, Evidence.id == Participant.evidence_id)
        .where(
            *scope(Person, user, case_id),
            *scope(Participant, user, case_id),
            *scope(Evidence, user, case_id),
            Evidence.item_type == "email",
        )
        .group_by(Person.id, Person.email, Person.name, Person.state)
    )


def person_json(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "email",
            "name",
            "state",
            "sent_count",
            "received_count",
            "total_count",
            "unique_messages",
        )
    }


def require_person(db, user, case_id, person_id):
    person = db.scalar(select(Person).where(Person.id == person_id, *scope(Person, user, case_id)))
    if not person:
        fail(404, "NOT_FOUND", "This participant is unavailable.")
    return person


@router.get("/cases/{case_id}/people")
def people(
    case_id: str,
    request: Request,
    limit: int = Query(200, ge=1, le=200),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    authorize_case(db, actor.user, case_id)
    rows = db.execute(
        people_query(actor.user, case_id)
        .order_by(func.count(func.distinct(Evidence.id)).desc(), Person.id)
        .limit(limit + 1)
    ).all()
    audit.record(
        db,
        actor.user,
        case_id,
        "participants.viewed",
        "case",
        case_id,
        {"returned": min(limit, len(rows)), "truncated": len(rows) > limit},
        request.state.request_id,
    )
    db.commit()
    return {
        "items": [person_json(row) for row in rows[:limit]],
        "truncated": len(rows) > limit,
        "count_basis": COUNT_BASIS,
    }


@router.get("/cases/{case_id}/people/{person_id}")
def person(
    case_id: str, person_id: str, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)
):
    authorize_case(db, actor.user, case_id)
    require_person(db, actor.user, case_id, person_id)
    row = db.execute(people_query(actor.user, case_id).where(Person.id == person_id)).first()
    if not row:
        fail(404, "NOT_FOUND", "This participant has no indexed email metadata.")
    audit.record(
        db,
        actor.user,
        case_id,
        "participant.viewed",
        "person",
        person_id,
        request_id=request.state.request_id,
    )
    db.commit()
    return {**person_json(row), "count_basis": COUNT_BASIS}


def person_messages(db, user, case_id, person_id, spec, request):
    authorize_case(db, user, case_id)
    require_person(db, user, case_id, person_id)
    evidence_ids = select(Participant.evidence_id).where(
        Participant.person_id == person_id, *scope(Participant, user, case_id)
    )
    result = run_search(
        db,
        user.tenant_id,
        case_id,
        spec,
        request.app.state.cursor_secret,
        extra_conditions=[Evidence.id.in_(evidence_ids), Evidence.item_type == "email"],
        scope_key=f"participant:{person_id}",
    )
    audit.record(
        db,
        user,
        case_id,
        "participant.messages_viewed",
        "person",
        person_id,
        {"total_hits": result["total_hits"]},
        request.state.request_id,
    )
    db.commit()
    return {
        **result,
        "person_id": person_id,
        "scope_basis": "Exact address membership in from/to/cc/bcc/reply-to headers.",
    }


@router.get("/cases/{case_id}/people/{person_id}/messages")
def get_person_messages(
    case_id: str,
    person_id: str,
    request: Request,
    query: str = Query("", max_length=4096),
    cursor: str | None = Query(None, max_length=2048),
    page_size: int = Query(50, ge=1, le=200),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    spec = SearchInput(query=query, cursor=cursor, page_size=page_size)
    return person_messages(db, actor.user, case_id, person_id, spec, request)


@router.post("/cases/{case_id}/people/{person_id}/messages")
def search_person_messages(
    case_id: str,
    person_id: str,
    spec: SearchInput,
    request: Request,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    return person_messages(db, actor.user, case_id, person_id, spec, request)


@router.get("/cases/{case_id}/analytics/participants")
def participant_analytics(
    case_id: str,
    request: Request,
    limit: int = Query(200, ge=1, le=200),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    return people(case_id, request, limit, actor, db)


@router.get("/cases/{case_id}/network")
@router.get("/cases/{case_id}/analytics/communication-network")
def network(
    case_id: str,
    request: Request,
    limit: int = Query(500, ge=1, le=500),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    authorize_case(db, actor.user, case_id)
    sender, recipient = aliased(Participant), aliased(Participant)
    sender_person, recipient_person = aliased(Person), aliased(Person)
    query = (
        select(
            sender.person_id.label("source"),
            recipient.person_id.label("target"),
            func.count(func.distinct(Evidence.id)).label("count"),
            func.count(func.distinct(Evidence.original_id)).label("unique_messages"),
            func.count(func.distinct(Evidence.thread_id)).label("unique_threads"),
        )
        .select_from(Evidence)
        .join(sender, and_(sender.evidence_id == Evidence.id, sender.role == "from"))
        .join(recipient, and_(recipient.evidence_id == Evidence.id, recipient.role.in_(RECIPIENT_ROLES)))
        .join(sender_person, sender_person.id == sender.person_id)
        .join(recipient_person, recipient_person.id == recipient.person_id)
        .where(
            *scope(Evidence, actor.user, case_id),
            *scope(sender, actor.user, case_id),
            *scope(recipient, actor.user, case_id),
            *scope(sender_person, actor.user, case_id),
            *scope(recipient_person, actor.user, case_id),
            Evidence.item_type == "email",
        )
        .group_by(sender.person_id, recipient.person_id)
        .order_by(func.count(func.distinct(Evidence.id)).desc(), sender.person_id, recipient.person_id)
        .limit(limit + 1)
    )
    rows = db.execute(query).all()
    edges = [
        {key: row._mapping[key] for key in ("source", "target", "count", "unique_messages", "unique_threads")}
        for row in rows[:limit]
    ]
    ids = {edge[side] for edge in edges for side in ("source", "target")}
    nodes = (
        db.scalars(
            select(Person).where(Person.id.in_(ids), *scope(Person, actor.user, case_id)).order_by(Person.id)
        ).all()
        if ids
        else []
    )
    audit.record(
        db,
        actor.user,
        case_id,
        "communication.network_viewed",
        "case",
        case_id,
        {"edge_count": len(edges), "truncated": len(rows) > limit},
        request.state.request_id,
    )
    db.commit()
    return {
        "nodes": [
            {"id": item.id, "email": item.email, "name": item.name, "state": item.state} for item in nodes
        ],
        "edges": edges,
        "truncated": len(rows) > limit,
        "count_basis": COUNT_BASIS,
        "direction": "Header sender to collected to/cc/bcc addresses; no inferred identities.",
    }


@router.get("/cases/{case_id}/timeline")
def timeline(
    case_id: str,
    request: Request,
    cursor: str | None = Query(None, max_length=2048),
    limit: int = Query(200, ge=1, le=200),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    authorize_case(db, actor.user, case_id)
    context = cursor_decode(cursor, request.app.state.cursor_secret) if cursor else None
    if context and (
        context.get("tenant_id") != actor.user.tenant_id
        or context.get("case_id") != case_id
        or context.get("scope") != "metadata-timeline"
    ):
        fail(422, "CURSOR_SCOPE_MISMATCH", "The cursor belongs to a different chronology or matter.")
    snapshot = parse_date(context["snapshot"]) if context else now()
    base = [*scope(Evidence, actor.user, case_id), Evidence.created_at <= snapshot]
    conditions = [*base, Evidence.date_utc.is_not(None)]
    total = db.scalar(select(func.count()).select_from(Evidence).where(*conditions)) or 0
    missing = (
        db.scalar(select(func.count()).select_from(Evidence).where(*base, Evidence.date_utc.is_(None))) or 0
    )
    if context:
        previous = parse_date(context["date"])
        conditions.append(
            or_(
                Evidence.date_utc > previous, and_(Evidence.date_utc == previous, Evidence.id > context["id"])
            )
        )
    rows = db.scalars(
        select(Evidence).where(*conditions).order_by(Evidence.date_utc, Evidence.id).limit(limit + 1)
    ).all()
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = cursor_encode(
            {
                "scope": "metadata-timeline",
                "tenant_id": actor.user.tenant_id,
                "case_id": case_id,
                "snapshot": snapshot.isoformat(),
                "date": utc(last.date_utc).isoformat(),
                "id": last.id,
            },
            request.app.state.cursor_secret,
        )
    audit.record(
        db,
        actor.user,
        case_id,
        "timeline.viewed",
        "case",
        case_id,
        {"total_items": total, "missing_date": missing},
        request.state.request_id,
    )
    db.commit()
    return {
        "items": [
            {
                "id": item.id,
                "date_utc": utc(item.date_utc).isoformat(),
                "date_raw": item.date_raw,
                "timezone_source": item.timezone_source,
                "title": item.title,
                "evidence_id": item.id,
                "type": item.item_type,
                "source": "metadata",
            }
            for item in rows[:limit]
        ],
        "next_cursor": next_cursor,
        "total_items": total,
        "missing_date_count": missing,
        "truncated": len(rows) > limit,
        "basis": "Source metadata timestamps, not inferred events.",
    }


@router.get("/cases/{case_id}/analytics/traffic")
def traffic(
    case_id: str,
    request: Request,
    group_by: str = "day",
    limit: int = Query(500, ge=1, le=500),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    authorize_case(db, actor.user, case_id)
    formats = {"day": ("%Y-%m-%d", "YYYY-MM-DD"), "month": ("%Y-%m", "YYYY-MM"), "year": ("%Y", "YYYY")}
    if group_by not in formats:
        fail(422, "GROUP_UNAVAILABLE", "Traffic supports day, month or year grouping in UTC.")
    bucket = (
        func.strftime(formats[group_by][0], Evidence.date_utc)
        if db.bind.dialect.name == "sqlite"
        else func.to_char(Evidence.date_utc, formats[group_by][1])
    )
    base = [*scope(Evidence, actor.user, case_id), Evidence.item_type == "email"]
    rows = db.execute(
        select(
            bucket.label("key"),
            func.count().label("count"),
            func.count(func.distinct(Evidence.original_id)).label("unique_messages"),
        )
        .where(*base, Evidence.date_utc.is_not(None))
        .group_by(bucket)
        .order_by(bucket)
        .limit(limit + 1)
    ).all()
    missing = (
        db.scalar(select(func.count()).select_from(Evidence).where(*base, Evidence.date_utc.is_(None))) or 0
    )
    return {
        "items": [
            {
                "key": row._mapping["key"],
                "count": row._mapping["count"],
                "unique_messages": row._mapping["unique_messages"],
            }
            for row in rows[:limit]
        ],
        "group_by": group_by,
        "timezone": "UTC",
        "missing_date_count": missing,
        "truncated": len(rows) > limit,
        "count_basis": COUNT_BASIS,
    }


@router.get("/cases/{case_id}/emails")
def emails(
    case_id: str,
    request: Request,
    query: str = Query("", max_length=4096),
    cursor: str | None = Query(None, max_length=2048),
    page_size: int = Query(50, ge=1, le=200),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    authorize_case(db, actor.user, case_id)
    return run_search(
        db,
        actor.user.tenant_id,
        case_id,
        SearchInput(query=query, cursor=cursor, page_size=page_size, filters=Filters(item_types=["email"])),
        request.app.state.cursor_secret,
    )


def thread_results(db, user, case_id, thread_id, request, cursor=None, page_size=50):
    rows = db.scalar(
        select(Evidence.id)
        .where(
            *scope(Evidence, user, case_id), Evidence.thread_id == thread_id, Evidence.item_type == "email"
        )
        .limit(1)
    )
    if not rows:
        fail(404, "NOT_FOUND", "This collected conversation is unavailable.")
    spec = SearchInput(
        filters=Filters(item_types=["email"], thread_id=thread_id),
        sort=[Sort(field="sent_at", order="asc")],
        cursor=cursor,
        page_size=page_size,
    )
    result = run_search(
        db, user.tenant_id, case_id, spec, request.app.state.cursor_secret, scope_key=f"thread:{thread_id}"
    )
    audit.record(
        db,
        user,
        case_id,
        "thread.viewed",
        "thread",
        thread_id,
        {"total_hits": result["total_hits"]},
        request.state.request_id,
    )
    db.commit()
    return {
        **result,
        "thread_id": thread_id,
        "basis": "Explicit Message-ID, In-Reply-To and References headers only.",
        "inferred_links": False,
        "completeness": "not_assessed",
        "warnings": [
            "Only collected messages sharing the current explicit thread root appear. Missing references, subject-based joins and alias resolution are not inferred."
        ],
    }


@router.get("/cases/{case_id}/threads/{thread_id}")
def thread(
    case_id: str,
    thread_id: str,
    request: Request,
    cursor: str | None = Query(None, max_length=2048),
    page_size: int = Query(50, ge=1, le=200),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    authorize_case(db, actor.user, case_id)
    return thread_results(db, actor.user, case_id, thread_id, request, cursor, page_size)


@router.get("/cases/{case_id}/emails/{evidence_id}/thread")
def email_thread(
    case_id: str,
    evidence_id: str,
    request: Request,
    cursor: str | None = Query(None, max_length=2048),
    page_size: int = Query(50, ge=1, le=200),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    item, original = get_item(db, actor.user, case_id, evidence_id)
    if item.item_type != "email":
        fail(404, "NOT_FOUND", "This email is unavailable.")
    if not item.thread_id:
        from .search import evidence_json

        return {
            "thread_id": None,
            "items": [evidence_json(item, original)],
            "next_cursor": None,
            "total_hits": 1,
            "inferred_links": False,
            "completeness": "not_assessed",
            "warnings": [
                "This message has no usable explicit conversation identifier. No conversation was inferred."
            ],
        }
    return thread_results(db, actor.user, case_id, item.thread_id, request, cursor, page_size)
