import hashlib

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select, update

from . import audit
from .case_routes import source_json
from .models import (
    Annotation,
    Artifact,
    Audit,
    Evidence,
    Member,
    Original,
    Review,
    ReviewSet,
    ReviewSetItem,
    SavedSearch,
    Source,
    Span,
)
from .schemas import AnnotationInput, BulkReviewInput, ReviewInput, ReviewSetInput, SavedInput, SearchInput
from .search import compile_query, evidence_json, run_search, search_conditions
from .security import Actor, authorize_case, current_actor, fail, get_db, utc

router = APIRouter(prefix="/api/v1")


def get_item(db, user, case_id, evidence_id, permission="view"):
    authorize_case(db, user, case_id, permission)
    row = db.execute(
        select(Evidence, Original)
        .join(Original, Evidence.original_id == Original.id)
        .where(
            Evidence.id == evidence_id,
            Evidence.case_id == case_id,
            Evidence.tenant_id == user.tenant_id,
            Original.case_id == case_id,
            Original.tenant_id == user.tenant_id,
        )
    ).first()
    if not row:
        fail(404, "NOT_FOUND", "This evidence is unavailable.")
    return row


def checked_text(db, item, storage):
    if hashlib.sha256(item.text.encode()).hexdigest() != item.text_hash:
        fail(409, "DERIVED_INTEGRITY_FAILED", "Extracted text failed integrity verification.")
    artifact = db.scalar(
        select(Artifact).where(
            Artifact.evidence_id == item.id,
            Artifact.case_id == item.case_id,
            Artifact.tenant_id == item.tenant_id,
            Artifact.version == item.text_version,
        )
    )
    if artifact:
        verified = storage.verify(artifact)
        # Artifacts carry a digest but no byte-size column; verify the digest directly.
        if verified["actual_sha256"] != artifact.sha256:
            fail(409, "DERIVED_INTEGRITY_FAILED", "The extracted text artifact is missing or changed.")
    return artifact


def spans_json(db, item):
    spans = db.scalars(
        select(Span)
        .where(Span.evidence_id == item.id, Span.case_id == item.case_id, Span.tenant_id == item.tenant_id)
        .order_by(Span.char_start)
    ).all()
    result = []
    for span in spans:
        text = item.text[span.char_start : span.char_end]
        if hashlib.sha256(text.encode()).hexdigest() != span.text_hash:
            fail(409, "CITATION_INTEGRITY_FAILED", "A citation span failed integrity verification.")
        result.append(
            {
                "id": span.id,
                "span_id": span.id,
                "artifact_id": span.artifact_id,
                "artifact_version": item.text_version,
                "page": span.page,
                "char_start": span.char_start,
                "char_end": span.char_end,
                "text_hash": span.text_hash,
                "text": text,
                "location": f"page:{span.page}"
                if span.page
                else f"text:chars={span.char_start}-{span.char_end}",
            }
        )
    return result


@router.post("/cases/{case_id}/search")
def search(
    case_id: str,
    body: SearchInput,
    request: Request,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    authorize_case(db, actor.user, case_id)
    result = run_search(db, actor.user.tenant_id, case_id, body, request.app.state.cursor_secret)
    audit.record(
        db,
        actor.user,
        case_id,
        "evidence.searched",
        "case",
        case_id,
        {
            "query_hash": hashlib.sha256(body.query.encode()).hexdigest(),
            "total_hits": result["total_hits"],
            "page_size": body.page_size,
        },
        request.state.request_id,
    )
    db.commit()
    return result


@router.post("/cases/{case_id}/search/facets")
def facets(
    case_id: str,
    body: SearchInput,
    request: Request,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    authorize_case(db, actor.user, case_id)
    result = run_search(db, actor.user.tenant_id, case_id, body, request.app.state.cursor_secret)
    return {key: result[key] for key in ("case_id", "facets", "groups", "total_hits", "coverage")}


@router.get("/cases/{case_id}/evidence/{evidence_id}")
def detail(
    case_id: str,
    evidence_id: str,
    request: Request,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    item, original = get_item(db, actor.user, case_id, evidence_id)
    if item.text:
        checked_text(db, item, request.app.state.storage)
    verified = request.app.state.storage.verify(original)
    original.integrity_status = "verified" if verified["valid"] else "failed"
    attachments = db.execute(
        select(Evidence, Original)
        .join(Original, Evidence.original_id == Original.id)
        .where(
            Evidence.parent_id == item.id,
            Evidence.case_id == case_id,
            Evidence.tenant_id == actor.user.tenant_id,
        )
    ).all()
    notes = db.scalars(
        select(Annotation)
        .where(
            Annotation.evidence_id == item.id,
            Annotation.case_id == case_id,
            Annotation.tenant_id == actor.user.tenant_id,
        )
        .order_by(Annotation.created_at)
    ).all()
    reviews = db.scalars(
        select(Review)
        .where(
            Review.evidence_id == item.id, Review.case_id == case_id, Review.tenant_id == actor.user.tenant_id
        )
        .order_by(Review.version.desc())
        .limit(100)
    ).all()
    source = db.get(Source, item.source_id)
    result = {
        **evidence_json(item, original),
        "text": item.text,
        "html": None,
        "email": item.email_metadata,
        "metadata": item.metadata_json,
        "spans": spans_json(db, item),
        "attachments": [evidence_json(child, raw) for child, raw in attachments],
        "source": source_json(source),
        "annotations": [
            {
                "id": note.id,
                "text": note.text,
                "span_id": note.span_id,
                "author_id": note.author_id,
                "created_at": utc(note.created_at).isoformat(),
            }
            for note in notes
        ],
        "review_history": [
            {
                "id": review.id,
                "version": review.version,
                "reviewer_id": review.reviewer_id,
                "changes": review.changes,
                "note": review.note,
                "created_at": utc(review.created_at).isoformat(),
            }
            for review in reviews
        ],
    }
    audit.record(
        db,
        actor.user,
        case_id,
        "evidence.viewed",
        "evidence",
        item.id,
        {"original_integrity": verified["valid"]},
        request.state.request_id,
    )
    db.commit()
    return result


@router.get("/cases/{case_id}/evidence/{evidence_id}/content")
def content(
    case_id: str,
    evidence_id: str,
    request: Request,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    item, _ = get_item(db, actor.user, case_id, evidence_id)
    if item.text:
        checked_text(db, item, request.app.state.storage)
    return {
        "evidence_id": item.id,
        "text": item.text,
        "artifact_version": item.text_version,
        "spans": spans_json(db, item),
        "parser_state": item.parser_state,
    }


@router.get("/cases/{case_id}/evidence/{evidence_id}/metadata")
def metadata(case_id: str, evidence_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    item, original = get_item(db, actor.user, case_id, evidence_id)
    return {
        **evidence_json(item, original),
        "email": item.email_metadata,
        "metadata": item.metadata_json,
        "date_raw": item.date_raw,
        "timezone_source": item.timezone_source,
    }


@router.get("/cases/{case_id}/evidence/{evidence_id}/citations")
def citations(
    case_id: str,
    evidence_id: str,
    request: Request,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    item, _ = get_item(db, actor.user, case_id, evidence_id)
    if item.text:
        checked_text(db, item, request.app.state.storage)
    return {"evidence_id": item.id, "items": spans_json(db, item)}


@router.get("/cases/{case_id}/evidence/{evidence_id}/family")
def family(case_id: str, evidence_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    item, _ = get_item(db, actor.user, case_id, evidence_id)
    parent_id = item.parent_id or item.id
    rows = db.execute(
        select(Evidence, Original)
        .join(Original, Evidence.original_id == Original.id)
        .where(
            Evidence.case_id == case_id,
            Evidence.tenant_id == actor.user.tenant_id,
            (Evidence.id == parent_id) | (Evidence.parent_id == parent_id),
        )
    ).all()
    return {"items": [evidence_json(value, original) for value, original in rows]}


@router.get("/cases/{case_id}/evidence/{evidence_id}/related")
def related(case_id: str, evidence_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    item, _ = get_item(db, actor.user, case_id, evidence_id)
    rows = db.execute(
        select(Evidence, Original)
        .join(Original, Evidence.original_id == Original.id)
        .where(
            Evidence.case_id == case_id,
            Evidence.tenant_id == actor.user.tenant_id,
            Evidence.id != item.id,
            (Evidence.original_id == item.original_id)
            | ((Evidence.thread_id == item.thread_id) if item.thread_id else Evidence.id == ""),
        )
        .limit(200)
    ).all()
    return {
        "items": [
            {
                **evidence_json(value, original),
                "relationship": "exact_duplicate"
                if value.original_id == item.original_id
                else "explicit_email_thread",
            }
            for value, original in rows
        ]
    }


@router.post("/cases/{case_id}/evidence/{evidence_id}/verify")
def verify(
    case_id: str,
    evidence_id: str,
    request: Request,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    item, original = get_item(db, actor.user, case_id, evidence_id)
    result = request.app.state.storage.verify(original)
    original.integrity_status = "verified" if result["valid"] else "failed"
    audit.record(
        db,
        actor.user,
        case_id,
        "evidence.integrity_checked",
        "evidence",
        item.id,
        {"valid": result["valid"]},
        request.state.request_id,
    )
    db.commit()
    return {"evidence_id": item.id, **result}


@router.get("/cases/{case_id}/evidence/{evidence_id}/original")
def original_download(
    case_id: str,
    evidence_id: str,
    request: Request,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    item, original = get_item(db, actor.user, case_id, evidence_id)
    if not request.app.state.storage.verify(original)["valid"]:
        original.integrity_status = "failed"
        audit.record(
            db,
            actor.user,
            case_id,
            "evidence.download_blocked",
            "evidence",
            item.id,
            {"reason": "integrity_failed"},
            request.state.request_id,
        )
        db.commit()
        fail(409, "INTEGRITY_FAILED", "Original integrity verification failed. Download is blocked.")
    if item.parser_state == "quarantined":
        fail(409, "EVIDENCE_QUARANTINED", "This item is quarantined and cannot be downloaded.")
    audit.record(
        db,
        actor.user,
        case_id,
        "evidence.downloaded",
        "evidence",
        item.id,
        {"sha256": original.sha256},
        request.state.request_id,
    )
    db.commit()
    return FileResponse(
        request.app.state.storage.path(original.storage_key),
        media_type="application/octet-stream",
        filename=item.filename,
        headers={"X-Evidence-SHA256": original.sha256, "Cache-Control": "no-store"},
    )


def apply_review(db, user, case_id, item, body, request_id):
    authorize_case(db, user, case_id, "review")
    changes = body.model_dump(exclude_none=True, exclude={"expected_version", "note"})
    if not changes and not body.note:
        fail(422, "REVIEW_EMPTY", "Choose a review change or write a note.")
    if body.privilege_status is not None and (
        body.privilege_status in {"confirmed", "cleared"}
        or item.privilege_status in {"confirmed", "cleared"} and body.privilege_status != item.privilege_status
    ):
        authorize_case(db, user, case_id, "privilege")
    if body.assigned_to and not db.scalar(
        select(Member.id).where(
            Member.user_id == body.assigned_to, Member.case_id == case_id, Member.tenant_id == user.tenant_id
        )
    ):
        fail(404, "NOT_FOUND", "The assigned reviewer is not a member of this matter.")
    expected = item.review_version if body.expected_version is None else body.expected_version
    result = db.execute(
        update(Evidence)
        .where(
            Evidence.id == item.id,
            Evidence.tenant_id == user.tenant_id,
            Evidence.case_id == case_id,
            Evidence.review_version == expected,
        )
        .values(**changes, review_version=expected + 1)
    )
    if result.rowcount != 1:
        fail(409, "REVIEW_VERSION_CONFLICT", "Another reviewer changed this item. Refresh before saving.")
    db.add(
        Review(
            tenant_id=user.tenant_id,
            case_id=case_id,
            evidence_id=item.id,
            reviewer_id=user.id,
            version=expected + 1,
            changes=changes,
            note=body.note or "",
        )
    )
    if body.note:
        db.add(
            Annotation(
                tenant_id=user.tenant_id,
                case_id=case_id,
                evidence_id=item.id,
                author_id=user.id,
                text=body.note,
            )
        )
    audit.record(
        db,
        user,
        case_id,
        "evidence.reviewed",
        "evidence",
        item.id,
        {"version": expected + 1, "fields": list(changes), "note_length": len(body.note or "")},
        request_id,
    )
    db.flush()
    db.refresh(item)


@router.post("/cases/{case_id}/evidence/{evidence_id}/reviews")
def review(
    case_id: str,
    evidence_id: str,
    body: ReviewInput,
    request: Request,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    item, original = get_item(db, actor.user, case_id, evidence_id, "review")
    apply_review(db, actor.user, case_id, item, body, request.state.request_id)
    db.commit()
    return evidence_json(item, original)


@router.post("/cases/{case_id}/reviews/bulk")
def bulk_review(
    case_id: str,
    body: BulkReviewInput,
    request: Request,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    authorize_case(db, actor.user, case_id, "review")
    ids = list(dict.fromkeys(body.evidence_ids))
    for evidence_id in ids:
        item, _ = get_item(db, actor.user, case_id, evidence_id, "review")
        apply_review(db, actor.user, case_id, item, body.changes, request.state.request_id)
    db.commit()
    return {"updated": len(ids), "evidence_ids": ids}


@router.post("/cases/{case_id}/evidence/{evidence_id}/tags")
def tag(
    case_id: str,
    evidence_id: str,
    body: ReviewInput,
    request: Request,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    if body.tags is None:
        fail(422, "TAGS_REQUIRED", "Supply a tags list.")
    item, original = get_item(db, actor.user, case_id, evidence_id, "review")
    apply_review(db, actor.user, case_id, item, body, request.state.request_id)
    db.commit()
    return evidence_json(item, original)


@router.post("/cases/{case_id}/evidence/{evidence_id}/annotations", status_code=201)
def annotate(
    case_id: str,
    evidence_id: str,
    body: AnnotationInput,
    request: Request,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    item, _ = get_item(db, actor.user, case_id, evidence_id, "review")
    if body.span_id and not db.scalar(
        select(Span.id).where(
            Span.id == body.span_id,
            Span.evidence_id == item.id,
            Span.case_id == case_id,
            Span.tenant_id == actor.user.tenant_id,
        )
    ):
        fail(404, "NOT_FOUND", "This citation span is unavailable.")
    note = Annotation(
        tenant_id=actor.user.tenant_id,
        case_id=case_id,
        evidence_id=item.id,
        span_id=body.span_id,
        author_id=actor.user.id,
        text=body.text,
    )
    db.add(note)
    db.flush()
    audit.record(
        db,
        actor.user,
        case_id,
        "evidence.annotated",
        "annotation",
        note.id,
        {"evidence_id": item.id, "span_id": body.span_id},
        request.state.request_id,
    )
    db.commit()
    return {
        "id": note.id,
        "text": note.text,
        "span_id": note.span_id,
        "author_id": note.author_id,
        "created_at": utc(note.created_at).isoformat(),
    }


@router.get("/cases/{case_id}/tags")
def tags(case_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    totals = {}
    for values in db.scalars(
        select(Evidence.tags).where(Evidence.case_id == case_id, Evidence.tenant_id == actor.user.tenant_id)
    ).yield_per(200):
        for value in values:
            totals[value] = totals.get(value, 0) + 1
    return {
        "items": [{"name": name, "count": count, "kind": "human"} for name, count in sorted(totals.items())]
    }


@router.get("/cases/{case_id}/saved-searches")
def saved_searches(case_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    return {
        "items": [
            {
                "id": item.id,
                "name": item.name,
                "query_spec": item.query_spec,
                "created_at": utc(item.created_at).isoformat(),
            }
            for item in db.scalars(
                select(SavedSearch)
                .where(SavedSearch.case_id == case_id, SavedSearch.tenant_id == actor.user.tenant_id)
                .order_by(SavedSearch.created_at.desc())
                .limit(200)
            )
        ]
    }


@router.post("/cases/{case_id}/saved-searches", status_code=201)
def save_search(
    case_id: str,
    body: SavedInput,
    request: Request,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    authorize_case(db, actor.user, case_id, "review")
    compile_query(body.query_spec.query)
    saved = SavedSearch(
        tenant_id=actor.user.tenant_id,
        case_id=case_id,
        owner_id=actor.user.id,
        name=body.name,
        query_spec=body.query_spec.model_dump(exclude={"cursor"}),
    )
    db.add(saved)
    db.flush()
    audit.record(
        db, actor.user, case_id, "search.saved", "saved-search", saved.id, request_id=request.state.request_id
    )
    db.commit()
    return {"id": saved.id, "name": saved.name, "query_spec": saved.query_spec}


@router.post("/cases/{case_id}/saved-searches/{search_id}/execute")
def execute_saved(
    case_id: str, search_id: str, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)
):
    authorize_case(db, actor.user, case_id)
    saved = db.scalar(
        select(SavedSearch).where(
            SavedSearch.id == search_id,
            SavedSearch.case_id == case_id,
            SavedSearch.tenant_id == actor.user.tenant_id,
        )
    )
    if not saved:
        fail(404, "NOT_FOUND", "This saved search is unavailable.")
    return run_search(
        db,
        actor.user.tenant_id,
        case_id,
        SearchInput.model_validate(saved.query_spec),
        request.app.state.cursor_secret,
    )


@router.get("/cases/{case_id}/review-sets")
def review_sets(case_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    rows = db.execute(
        select(ReviewSet, func.count(ReviewSetItem.evidence_id))
        .outerjoin(ReviewSetItem, ReviewSetItem.set_id == ReviewSet.id)
        .where(ReviewSet.case_id == case_id, ReviewSet.tenant_id == actor.user.tenant_id)
        .group_by(ReviewSet.id)
        .order_by(ReviewSet.created_at.desc())
        .limit(200)
    ).all()
    return {
        "items": [
            {"id": item.id, "name": item.name, "count": count, "query_spec": item.query_spec}
            for item, count in rows
        ]
    }


@router.post("/cases/{case_id}/review-sets", status_code=201)
def make_review_set(
    case_id: str,
    body: ReviewSetInput,
    request: Request,
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    authorize_case(db, actor.user, case_id, "review")
    if body.evidence_ids:
        ids = list(dict.fromkeys(body.evidence_ids))
        permitted = set(
            db.scalars(
                select(Evidence.id).where(
                    Evidence.id.in_(ids),
                    Evidence.case_id == case_id,
                    Evidence.tenant_id == actor.user.tenant_id,
                )
            )
        )
        if permitted != set(ids):
            fail(404, "NOT_FOUND", "One or more selected evidence items are unavailable.")
    elif body.query_spec:
        ids = list(
            db.scalars(
                select(Evidence.id)
                .where(*search_conditions(actor.user.tenant_id, case_id, body.query_spec))
                .limit(20001)
            )
        )
        if len(ids) > 20000:
            fail(413, "REVIEW_SET_LIMIT", "Narrow this snapshot to at most 20,000 items.")
    else:
        fail(422, "REVIEW_SET_SCOPE_REQUIRED", "Choose evidence or a search scope.")
    item = ReviewSet(
        tenant_id=actor.user.tenant_id,
        case_id=case_id,
        name=body.name,
        created_by=actor.user.id,
        query_spec=body.query_spec.model_dump(exclude={"cursor"}) if body.query_spec else {},
    )
    db.add(item)
    db.flush()
    for evidence_id in ids:
        db.add(
            ReviewSetItem(
                tenant_id=actor.user.tenant_id, case_id=case_id, set_id=item.id, evidence_id=evidence_id
            )
        )
    audit.record(
        db,
        actor.user,
        case_id,
        "review_set.created",
        "review-set",
        item.id,
        {"snapshot_count": len(ids)},
        request.state.request_id,
    )
    db.commit()
    return {"id": item.id, "name": item.name, "count": len(ids), "query_spec": item.query_spec}


@router.get("/cases/{case_id}/review-sets/{set_id}")
def show_review_set(case_id: str, set_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    item = db.scalar(
        select(ReviewSet).where(
            ReviewSet.id == set_id, ReviewSet.case_id == case_id, ReviewSet.tenant_id == actor.user.tenant_id
        )
    )
    if not item:
        fail(404, "NOT_FOUND", "This review set is unavailable.")
    count = db.scalar(select(func.count()).select_from(ReviewSetItem).where(ReviewSetItem.set_id == item.id))
    return {"id": item.id, "name": item.name, "count": count, "query_spec": item.query_spec}


@router.get("/cases/{case_id}/audit")
def audit_events(
    case_id: str,
    limit: int = Query(100, ge=1, le=200),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    authorize_case(db, actor.user, case_id, "audit")
    rows = db.scalars(
        select(Audit)
        .where(Audit.case_id == case_id, Audit.tenant_id == actor.user.tenant_id)
        .order_by(Audit.sequence.desc())
        .limit(limit)
    ).all()
    return {"items": [audit.event_json(event) for event in rows], "next_cursor": None}


@router.post("/cases/{case_id}/audit/verify")
def verify_audit(case_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    authorize_case(db, actor.user, case_id, "audit")
    return audit.verify_chain(db, actor.user.tenant_id, case_id)
