"""Bounded deterministic investigation candidates with immutable source provenance."""

import codecs
import hashlib
import re
from difflib import SequenceMatcher

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import func, select

from .models import Artifact, Evidence, Original, Span
from .schemas import Input
from .security import Actor, authorize_case, current_actor, fail, get_db

router = APIRouter(prefix="/api/v1")
TEXT_LIMIT = 20_000
TOKEN_LIMIT = 1000
FINDING_LIMIT = 200
MAX_ORIGINAL_BYTES = 100_000_000
MAX_ARTIFACT_BYTES = 20_000_000
MAX_VERIFICATION_BYTES = 500_000_000
RULES = (
    ("email", re.compile(r"(?<![\w.!#$%&'*+/=?^_`{|}~-])[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+(?![\w.-])")),
    ("date", re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:,?\s+\d{4})?)\b", re.I)),
    ("amount", re.compile(r"(?<!\w)(?:[$€£]\s*\d[\d,.]*|(?:USD|EUR|GBP|CAD)\s+\d[\d,.]*)(?!\w)", re.I)),
    ("invoice", re.compile(r"\binvoice\s*(?:no\.?|number|#)\s*[:#-]?\s*[A-Z0-9][A-Z0-9_-]{0,39}\b", re.I)),
)


class SimilarityInput(Input):
    threshold: float = Field(default=.75, ge=.1, le=1, allow_inf_nan=False)
    candidate_limit: int = Field(default=100, ge=1, le=100)
    limit: int = Field(default=20, ge=1, le=20)


class CompareInput(Input):
    left_id: str
    right_id: str


def _query(tenant_id, case_id):
    # SQL applies the character limit before materializing rows in Python.
    return select(Evidence.id.label("id"), Evidence.title, Evidence.original_id, Evidence.text_version, Evidence.text_hash, Evidence.parser_state, func.length(Evidence.text).label("text_length"), func.substr(Evidence.text, 1, TEXT_LIMIT).label("text"), Original).join(Original, Evidence.original_id == Original.id).where(Evidence.tenant_id == tenant_id, Evidence.case_id == case_id, Original.tenant_id == tenant_id, Original.case_id == case_id)


def _prefix(path, character_limit):
    decoder, pieces, length = codecs.getincrementaldecoder("utf-8")("strict"), [], 0
    with path.open("rb") as stream:
        while length < character_limit:
            chunk = stream.read(min(4096, max(4, (character_limit - length) * 4)))
            if not chunk:
                decoded = decoder.decode(b"", final=True)
                pieces.append(decoded[:character_limit - length])
                break
            decoded = decoder.decode(chunk)
            pieces.append(decoded[:character_limit - length])
            length += len(pieces[-1])
    return "".join(pieces)


def _verified(db, row, storage):
    original = row.Original
    if row.parser_state not in {"indexed", "partial"} or not row.text:
        fail(409, "CANDIDATE_TEXT_UNAVAILABLE", "This operation requires available extracted text.")
    if original.byte_size > MAX_ORIGINAL_BYTES:
        fail(413, "CANDIDATE_SOURCE_LIMIT", "Candidate verification supports originals up to 100 megabytes each.")
    if not storage.verify(original)["valid"]:
        fail(409, "INTEGRITY_FAILED", "An original source failed verification.")
    artifact = db.scalar(select(Artifact).where(Artifact.evidence_id == row.id, Artifact.tenant_id == original.tenant_id, Artifact.case_id == original.case_id, Artifact.version == row.text_version, Artifact.kind == "extracted-text"))
    if artifact is None or artifact.sha256 != row.text_hash:
        fail(409, "DERIVED_INTEGRITY_FAILED", "A verified immutable extracted-text artifact is required.")
    try:
        if storage.path(artifact.storage_key).stat().st_size > MAX_ARTIFACT_BYTES:
            fail(413, "CANDIDATE_SOURCE_LIMIT", "Candidate verification supports extracted artifacts up to 20 megabytes each.")
        if not storage.verify(artifact)["valid"]:
            fail(409, "DERIVED_INTEGRITY_FAILED", "The immutable extracted-text artifact failed verification.")
        if _prefix(storage.path(artifact.storage_key), TEXT_LIMIT) != row.text:
            fail(409, "DERIVED_INTEGRITY_FAILED", "The retrieved text prefix differs from its immutable artifact.")
    except (OSError, UnicodeDecodeError):
        fail(409, "DERIVED_INTEGRITY_FAILED", "The immutable extracted-text artifact is unavailable or invalid.")
    return artifact


def _load(db, user, case_id, identifier, storage):
    row = db.execute(_query(user.tenant_id, case_id).where(Evidence.id == identifier)).first()
    if row is None:
        fail(404, "NOT_FOUND", "The selected evidence is unavailable.")
    return row, _verified(db, row, storage)


def _provenance(row, artifact):
    return {"evidence_id": row.id, "title": row.title, "original_sha256": row.Original.sha256, "artifact_id": artifact.id, "artifact_sha256": artifact.sha256, "artifact_version": row.text_version, "retrieved_chars": len(row.text), "total_chars": row.text_length, "text_truncated": row.text_length > len(row.text), "parser_state": row.parser_state}


def _citation(row, artifact, start, end, span=None):
    return {"evidence_id": row.id, "span_id": span.id if span else None, "artifact_id": artifact.id, "artifact_version": row.text_version, "artifact_sha256": artifact.sha256, "original_sha256": row.Original.sha256, "char_start": start, "char_end": end, "page": span.page if span else None, "text_hash": hashlib.sha256(row.text[start:end].encode()).hexdigest(), "location": f"text:chars={start}-{end}"}


def _spans(db, row, artifact):
    spans = list(db.scalars(select(Span).where(Span.evidence_id == row.id, Span.tenant_id == row.Original.tenant_id, Span.case_id == row.Original.case_id, Span.artifact_id == artifact.id, Span.char_start < len(row.text)).order_by(Span.char_start, Span.id).limit(1001)))
    valid = []
    for span in spans[:1000]:
        if not 0 <= span.char_start < span.char_end <= len(row.text):
            continue  # A partially retrieved source span is explicitly outside this bounded operation.
        if hashlib.sha256(row.text[span.char_start:span.char_end].encode()).hexdigest() != span.text_hash:
            fail(409, "CITATION_INTEGRITY_FAILED", "A source span failed immutable text verification.")
        valid.append(span)
    return valid, len(spans) > 1000


def _shingles(text):
    words = re.findall(r"\w+", text.casefold())[:5000]
    if len(words) < 3:
        return set(words)
    return {tuple(words[index:index + 3]) for index in range(len(words) - 2)}


@router.post("/cases/{case_id}/evidence/{evidence_id}/near-duplicates")
def near_duplicates(case_id: str, evidence_id: str, body: SimilarityInput, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    source, source_artifact = _load(db, actor.user, case_id, evidence_id, request.app.state.storage)
    conditions = (Evidence.tenant_id == actor.user.tenant_id, Evidence.case_id == case_id, Evidence.original_id != source.original_id, Evidence.parser_state.in_(["indexed", "partial"]), Evidence.text != "")
    count = db.scalar(select(func.count()).select_from(Evidence).where(*conditions)) or 0
    rows = list(db.execute(_query(actor.user.tenant_id, case_id).where(*conditions).order_by(Evidence.id).limit(body.candidate_limit)))
    base, candidates, text_truncated = _shingles(source.text), [], source.text_length > len(source.text)
    for row in rows:
        compared = _shingles(row.text)
        score = len(base & compared) / len(base | compared) if base | compared else 0
        text_truncated |= row.text_length > len(row.text)
        if score >= body.threshold:
            candidates.append((score, row))
    candidates.sort(key=lambda item: (-item[0], item[1].id))
    items, integrity_omitted, verification_omitted = [], 0, 0
    verification_bytes = source.Original.byte_size
    for score, row in candidates:
        if len(items) >= body.limit:
            break
        if row.Original.byte_size > MAX_ORIGINAL_BYTES or verification_bytes + row.Original.byte_size > MAX_VERIFICATION_BYTES:
            verification_omitted += 1
            continue
        try:
            artifact = _verified(db, row, request.app.state.storage)
        except HTTPException as error:
            if error.status_code in {409, 413}:
                integrity_omitted += 1
                continue
            raise
        verification_bytes += row.Original.byte_size
        items.append({**_provenance(row, artifact), "score": round(score, 6), "relationship": "near_duplicate_candidate", "review_state": "pending_human_review", "citations": [_citation(row, artifact, 0, len(row.text))]})
    return {"source": _provenance(source, source_artifact), "items": items, "coverage": {"eligible_count": count, "scanned_count": len(rows), "returned_count": len(items), "matched_count": len(candidates), "integrity_omitted": integrity_omitted, "verification_budget_omitted": verification_omitted, "corpus_truncated": count > len(rows), "text_truncated": text_truncated, "result_truncated": len(candidates) > len(items) + integrity_omitted + verification_omitted}, "method": "Unicode casefold word-trigram Jaccard over first20kcharacters/5000words; ID-ordered candidate pool; exact original duplicates excluded", "limits": ["Deterministic similarity candidates require human comparison; no deletion, merge, exclusion or review decision is applied.", "Scores describe retrieved prefixes, not whole documents, whenever text or candidate coverage is truncated.", "Originals up to 100MB and text artifacts up to 20MB; verification examines at most 500MB of original bytes per request."]}


@router.get("/cases/{case_id}/evidence/{evidence_id}/entities")
def entities(case_id: str, evidence_id: str, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    row, artifact = _load(db, actor.user, case_id, evidence_id, request.app.state.storage)
    spans, span_truncated = _spans(db, row, artifact)
    found = sorted(((match.start(), match.end(), kind, match.group()) for kind, pattern in RULES for match in pattern.finditer(row.text)), key=lambda item: (item[0], item[2]))
    items, unanchored = [], 0
    for start, end, kind, text in found[:FINDING_LIMIT]:
        anchors = [span for span in spans if span.char_start <= start and end <= span.char_end]
        if not anchors:
            unanchored += 1
            continue
        items.append({"kind": kind, "text": text, "char_start": start, "char_end": end, "review_state": "pending_human_review", "citations": [_citation(row, artifact, start, end, anchors[0])]})
    return {"source": _provenance(row, artifact), "items": items, "review_state": "pending_human_review", "coverage": {"retrieved_chars": len(row.text), "total_chars": row.text_length, "text_truncated": row.text_length > len(row.text), "finding_truncated": len(found) > FINDING_LIMIT, "span_truncated": span_truncated, "unanchored_omitted": unanchored, "returned_count": len(items)}, "method": "local_regex_candidate_v1", "limits": ["Email, date, currency amount and explicitly labeled invoice-number patterns only; names, roles, obligations and company identities are not inferred.", "Dates retain their source spelling; locale, timezone, validity and whether they describe an event require human interpretation.", "Candidates do not create verified identities, timeline events, final facts or review codes."]}


def _tokens(text):
    matches = list(re.finditer(r"\S+(?:\s+|$)|\s+", text))
    kept = matches[:TOKEN_LIMIT]
    return [match.group() for match in kept], [match.start() for match in kept] + [kept[-1].end() if kept else 0], len(matches) > TOKEN_LIMIT


@router.post("/cases/{case_id}/compare")
def compare(case_id: str, body: CompareInput, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    authorize_case(db, actor.user, case_id)
    left, left_artifact = _load(db, actor.user, case_id, body.left_id, request.app.state.storage)
    right, right_artifact = _load(db, actor.user, case_id, body.right_id, request.app.state.storage)
    left_tokens, left_offsets, left_truncated = _tokens(left.text)
    right_tokens, right_offsets, right_truncated = _tokens(right.text)
    opcodes = SequenceMatcher(None, left_tokens, right_tokens, autojunk=False).get_opcodes()
    segments = []
    for kind, a, b, c, d in opcodes[:FINDING_LIMIT]:
        left_start, left_end = left_offsets[a], left_offsets[b]
        right_start, right_end = right_offsets[c], right_offsets[d]
        citations = []
        if left_end > left_start:
            citations.append(_citation(left, left_artifact, left_start, left_end))
        if right_end > right_start:
            citations.append(_citation(right, right_artifact, right_start, right_end))
        segments.append({"kind": kind, "left_start": left_start, "left_end": left_end, "right_start": right_start, "right_end": right_end, "left_text": left.text[left_start:left_end], "right_text": right.text[right_start:right_end], "citations": citations})
    return {"left": _provenance(left, left_artifact), "right": _provenance(right, right_artifact), "segments": segments, "coverage": {"left_compared_chars": left_offsets[-1], "right_compared_chars": right_offsets[-1], "text_truncated": left.text_length > len(left.text) or right.text_length > len(right.text), "token_truncated": left_truncated or right_truncated, "segment_truncated": len(opcodes) > FINDING_LIMIT}, "method": "bounded_exact_word_whitespace_diff_v1", "review_state": "pending_human_review", "limits": ["Up to20kcharacters and1000tokens per source; at most200diffsegments. Covers extracted text only, without layout, images or unextracted content.", "Differences are source-backed comparison candidates; the operation does not establish which document is authentic, later, authoritative or contradictory."]}
