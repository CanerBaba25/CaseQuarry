import base64
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import String, and_, cast, func, not_, or_, select, true
from sqlalchemy.orm import load_only

from .models import Evidence, Original, Participant
from .schemas import SearchInput
from .security import fail, utc

TOKEN = re.compile(r'\s*(\(|\)|(?:(?:[A-Za-z_][A-Za-z0-9_-]*):)?"(?:[^"\\]|\\.)*"|[^\s()"]+)')


def parse_date(value: str, inclusive_end=False):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        parsed = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
        return parsed + timedelta(days=1) if inclusive_end and len(value) == 10 else parsed
    except (ValueError, TypeError, OverflowError):
        fail(422, "INVALID_DATE", "Use an ISO 8601 date or timestamp.")


def contains(column, value: str, wildcard=False):
    value = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    if wildcard:
        value = value.replace("*", "%")
    return column.ilike(f"%{value}%", escape="\\")


def tag_condition(tag):
    return contains(cast(Evidence.tags, String), json.dumps(tag, ensure_ascii=True))


def term_condition(token: str):
    field, value = (
        token.split(":", 1) if ":" in token and re.match(r"^[a-zA-Z_-]+:", token) else ("text", token)
    )
    field = field.lower()
    if value.startswith('"'):
        value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if not value:
        fail(422, "INVALID_QUERY", "Search values must not be empty.")
    if field in {"text", "body"}:
        return (
            or_(contains(Evidence.text, value, True), contains(Evidence.title, value, True))
            if field == "text"
            else contains(Evidence.text, value, True)
        )
    if field in {"from", "sender"}:
        return contains(Evidence.sender, value, True)
    if field in {"to", "recipient", "cc", "bcc"}:
        if field in {"cc", "bcc"}:
            return contains(cast(Evidence.email_metadata[field], String), value)
        return contains(Evidence.recipients, value, True)
    if field in {"subject", "title"}:
        return contains(Evidence.title, value, True)
    if field in {"after", "before"}:
        date = parse_date(value)
        return Evidence.date_utc >= date if field == "after" else Evidence.date_utc < date
    if field == "has":
        if value != "attachment":
            fail(422, "INVALID_QUERY", "The supported has: value is attachment.")
        return Evidence.has_attachments.is_(True)
    if field == "type":
        return Evidence.item_type == value.lower()
    if field == "filename":
        return contains(Evidence.filename, value, True)
    if field == "tag":
        return tag_condition(value)
    if field == "source":
        return Evidence.source_id == value
    if field == "custodian":
        return Evidence.custodian_id == value
    if field in {"id", "evidence"}:
        return Evidence.id == value
    fail(422, "UNKNOWN_SEARCH_FIELD", f"Unsupported search field: {field}.")


def compile_query(query: str):
    tokens, index = [], 0
    while index < len(query):
        if not query[index:].strip():
            break
        match = TOKEN.match(query, index)
        if not match:
            fail(422, "INVALID_QUERY", "Search contains an unclosed quote or invalid token.")
        tokens.append(match.group(1))
        index = match.end()
    if len(tokens) > 128:
        fail(422, "QUERY_TOO_COMPLEX", "Reduce this query to at most 128 tokens.")
    if not tokens:
        return true()
    position = 0

    def atom(depth=0):
        nonlocal position
        if depth > 16 or position >= len(tokens):
            fail(422, "INVALID_QUERY", "Search expression is incomplete or nested too deeply.")
        token = tokens[position]
        position += 1
        if token.upper() == "NOT":
            return not_(atom(depth + 1))
        if token == "(":
            result = disjunction(depth + 1)
            if position >= len(tokens) or tokens[position] != ")":
                fail(422, "INVALID_QUERY", "Search contains an unclosed parenthesis.")
            position += 1
            return result
        if token in {"(", ")"} or token.upper() in {"AND", "OR"}:
            fail(422, "INVALID_QUERY", "An operator needs a search term on each side.")
        return term_condition(token)

    def conjunction(depth=0):
        nonlocal position
        result = atom(depth)
        while position < len(tokens) and tokens[position] != ")" and tokens[position].upper() != "OR":
            if tokens[position].upper() == "AND":
                position += 1
            result = and_(result, atom(depth))
        return result

    def disjunction(depth=0):
        nonlocal position
        result = conjunction(depth)
        while position < len(tokens) and tokens[position].upper() == "OR":
            position += 1
            result = or_(result, conjunction(depth))
        return result

    expression = disjunction()
    if position != len(tokens):
        fail(422, "INVALID_QUERY", "Search contains an unmatched parenthesis.")
    return expression


def search_conditions(tenant_id, case_id, spec: SearchInput):
    if spec.mode != "keyword":
        fail(
            503,
            "SEARCH_MODE_UNAVAILABLE",
            "Semantic and hybrid search are not configured. Use keyword search.",
        )
    conditions = [Evidence.tenant_id == tenant_id, Evidence.case_id == case_id, compile_query(spec.query)]
    filters = spec.filters
    for person_id, roles in (
        (filters.person_id, None),
        (filters.sender_person_id, ("from",)),
        (filters.recipient_person_id, ("to", "cc", "bcc")),
    ):
        if person_id:
            participant_evidence = select(Participant.evidence_id).where(
                Participant.tenant_id == tenant_id,
                Participant.case_id == case_id,
                Participant.person_id == person_id,
            )
            if roles:
                participant_evidence = participant_evidence.where(Participant.role.in_(roles))
            conditions.append(Evidence.id.in_(participant_evidence))
    for values, column in (
        (filters.item_types, Evidence.item_type),
        (filters.review_status, Evidence.review_status),
        (filters.privilege_status, Evidence.privilege_status),
        (filters.source_ids, Evidence.source_id),
        (filters.custodian_ids, Evidence.custodian_id),
        (filters.parser_state, Evidence.parser_state),
    ):
        if values:
            conditions.append(column.in_(values))
    for value, column in ((filters.sender, Evidence.sender), (filters.recipient, Evidence.recipients)):
        if value:
            conditions.append(contains(column, value))
    for tag in filters.tags:
        conditions.append(tag_condition(tag))
    for tag in filters.exclude_tags:
        conditions.append(not_(tag_condition(tag)))
    date_column = Evidence.created_at if filters.date_field == "imported_at" else Evidence.date_utc
    if filters.date_field not in {"sent_at", "date_utc", "imported_at"}:
        fail(422, "INVALID_DATE_FIELD", "Choose sent_at, date_utc or imported_at.")
    date_from = parse_date(filters.date_from) if filters.date_from else None
    date_to = parse_date(filters.date_to, inclusive_end=True) if filters.date_to else None
    if date_from and date_to and date_to <= date_from:
        fail(422, "INVALID_DATE_RANGE", "The end of the date range must follow its start.")
    if date_from:
        conditions.append(date_column >= date_from)
    if date_to:
        conditions.append(date_column < date_to)
    if filters.missing_date is not None:
        conditions.append(date_column.is_(None) if filters.missing_date else date_column.is_not(None))
    for value, column in (
        (filters.has_attachment, Evidence.has_attachments),
        (filters.bookmarked, Evidence.bookmarked),
    ):
        if value is not None:
            conditions.append(column == value)
    for value, column in (
        (filters.thread_id, Evidence.thread_id),
        (filters.parent_id, Evidence.parent_id),
        (filters.assigned_to, Evidence.assigned_to),
    ):
        if value:
            conditions.append(column == value)
    return conditions


def evidence_json(item: Evidence, original: Original, snippet: str | None = None):
    return {
        "id": item.id,
        "evidence_id": item.id,
        "type": item.item_type,
        "title": item.title,
        "date_utc": utc(item.date_utc).isoformat() if item.date_utc else None,
        "created_at": utc(item.created_at).isoformat(),
        "date_raw": item.date_raw,
        "timezone_source": item.timezone_source,
        "sender": item.sender,
        "recipients": [address.strip() for address in item.recipients.split(",") if address.strip()],
        "source_id": item.source_id,
        "custodian_id": item.custodian_id,
        "parent_id": item.parent_id,
        "snippet": item.text[:300] if snippet is None else snippet,
        "sha256": original.sha256,
        "byte_size": original.byte_size,
        "original_name": item.filename,
        "has_attachments": item.has_attachments,
        "review_status": item.review_status,
        "privilege_status": item.privilege_status,
        "tags": item.tags,
        "bookmarked": item.bookmarked,
        "parser_state": item.parser_state,
        "parser_error": item.parser_error,
        "review_version": item.review_version,
        "assigned_to": item.assigned_to,
        "thread_id": item.thread_id,
        "integrity_status": original.integrity_status,
    }


def grouping(db, conditions, field):
    if not field:
        return []
    mapping = {
        "sender": Evidence.sender,
        "type": Evidence.item_type,
        "review_status": Evidence.review_status,
        "source": Evidence.source_id,
        "custodian": Evidence.custodian_id,
        "thread": Evidence.thread_id,
        "privilege_status": Evidence.privilege_status,
        "reviewer": Evidence.assigned_to,
    }
    if field in {"month", "year", "day"}:
        formats = {"month": ("%Y-%m", "YYYY-MM"), "year": ("%Y", "YYYY"), "day": ("%Y-%m-%d", "YYYY-MM-DD")}
        mapping[field] = (
            func.strftime(formats[field][0], Evidence.date_utc)
            if db.bind.dialect.name == "sqlite"
            else func.to_char(Evidence.date_utc, formats[field][1])
        )
    if field == "tag":
        totals = {}
        for tags in db.scalars(select(Evidence.tags).where(*conditions)).yield_per(200):
            for tag in tags or ["Untagged"]:
                totals[tag] = totals.get(tag, 0) + 1
        return [
            {"key": key, "count": count}
            for key, count in sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))[:200]
        ]
    if field not in mapping:
        fail(422, "GROUP_UNAVAILABLE", "This grouping is not available in the current search backend.")
    key = func.coalesce(cast(mapping[field], String), "Unknown")
    result = db.execute(
        select(key, func.count())
        .where(*conditions)
        .group_by(key)
        .order_by(func.count().desc(), key)
        .limit(200)
    ).all()
    return [{"key": value or "Unknown", "count": count} for value, count in result]


def cursor_encode(value, secret):
    payload = base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def cursor_decode(value, secret):
    try:
        payload, signature = value.rsplit(".", 1)
        expected = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, TypeError, json.JSONDecodeError):
        fail(422, "INVALID_CURSOR", "The cursor is invalid. Start this search again.")


def run_search(db, tenant_id, case_id, spec, secret, extra_conditions=None, scope_key=None):
    conditions = search_conditions(tenant_id, case_id, spec)
    conditions.extend(extra_conditions or [])
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "tenant_id": tenant_id,
                "case_id": case_id,
                "scope_key": scope_key,
                **spec.model_dump(exclude={"cursor", "page_size"}),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    cursor = cursor_decode(spec.cursor, secret) if spec.cursor else None
    if cursor and cursor.get("query") != fingerprint:
        fail(422, "CURSOR_SCOPE_MISMATCH", "The cursor belongs to a different query or matter.")
    snapshot = parse_date(cursor["snapshot"]) if cursor else datetime.now(UTC)
    conditions.append(Evidence.created_at <= snapshot)
    total = db.scalar(select(func.count()).select_from(Evidence).where(*conditions)) or 0
    sort = spec.sort[0]
    date_min = datetime(1900, 1, 1, tzinfo=UTC)
    mapping = {
        "date": (func.coalesce(Evidence.date_utc, date_min), "date_utc"),
        "sent_at": (func.coalesce(Evidence.date_utc, date_min), "date_utc"),
        "date_utc": (func.coalesce(Evidence.date_utc, date_min), "date_utc"),
        "imported_at": (Evidence.created_at, "created_at"),
        "title": (func.lower(Evidence.title), "title"),
        "sender": (func.lower(Evidence.sender), "sender"),
        "size": (Original.byte_size, "byte_size"),
        "evidence_id": (Evidence.id, "id"),
        "relevance": (Evidence.created_at, "created_at"),
    }
    if sort.field not in mapping:
        fail(422, "SORT_UNAVAILABLE", "This sort is not available in the current search backend.")
    expression, attribute = mapping[sort.field]
    page_conditions = list(conditions)
    if cursor:
        value = cursor["value"]
        if attribute in {"date_utc", "created_at"}:
            value = parse_date(value)
        operator = expression > value if sort.order == "asc" else expression < value
        tie = Evidence.id > cursor["id"] if sort.order == "asc" else Evidence.id < cursor["id"]
        page_conditions.append(or_(operator, and_(expression == value, tie)))
    ordering = (
        [expression.asc(), Evidence.id.asc()]
        if sort.order == "asc"
        else [expression.desc(), Evidence.id.desc()]
    )
    rows = db.execute(
        select(Evidence, Original, func.substr(Evidence.text, 1, 300), expression)
        .options(
            load_only(
                Evidence.id, Evidence.item_type, Evidence.title, Evidence.date_utc,
                Evidence.created_at, Evidence.date_raw, Evidence.timezone_source,
                Evidence.sender, Evidence.recipients, Evidence.source_id,
                Evidence.custodian_id, Evidence.parent_id, Evidence.filename,
                Evidence.has_attachments, Evidence.review_status,
                Evidence.privilege_status, Evidence.tags, Evidence.bookmarked,
                Evidence.parser_state, Evidence.parser_error, Evidence.review_version,
                Evidence.assigned_to, Evidence.thread_id, raiseload=True,
            ),
            load_only(Original.sha256, Original.byte_size, Original.integrity_status, raiseload=True),
        )
        .join(Original, Evidence.original_id == Original.id)
        .where(*page_conditions)
        .order_by(*ordering)
        .limit(spec.page_size + 1)
    ).all()
    next_cursor = None
    if len(rows) > spec.page_size:
        item, _original, _snippet, value = rows[spec.page_size - 1]
        if attribute in {"date_utc", "created_at"}:
            value = utc(value or date_min).isoformat()
        next_cursor = cursor_encode(
            {"query": fingerprint, "snapshot": snapshot.isoformat(), "value": value, "id": item.id}, secret
        )
    facets = [
        {"field": field, "values": grouping(db, conditions, field)}
        for field in ("type", "sender", "review_status", "source")
    ]
    groups = grouping(db, conditions, spec.group_by)
    states = db.execute(
        select(Evidence.parser_state, func.count())
        .where(Evidence.tenant_id == tenant_id, Evidence.case_id == case_id)
        .group_by(Evidence.parser_state)
    ).all()
    return {
        "case_id": case_id,
        "index_version": "sql-v1",
        "total_hits": total,
        "total_hits_relation": "eq",
        "next_cursor": next_cursor,
        "items": [evidence_json(item, original, snippet) for item, original, snippet, _sort_value in rows[: spec.page_size]],
        "facets": facets,
        "groups": groups,
        "coverage": {
            "total_items": sum(count for _, count in states),
            "states": dict(states),
            "search_backend": "scoped-sql",
            "scale_validated": False,
        },
        "warnings": [
            "Relevance sort currently uses recency; ranked search requires the future OpenSearch backend."
        ]
        if sort.field == "relevance"
        else [],
    }
