import json
from hashlib import sha256

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .models import Audit, AuditHead, new_id, now
from .security import utc


def audit_payload(event: Audit) -> dict:
    return {"id": event.id, "tenant_id": event.tenant_id, "case_id": event.case_id, "actor_id": event.actor_id, "sequence": event.sequence, "event_type": event.event_type, "target_type": event.target_type, "target_id": event.target_id, "request_id": event.request_id, "timestamp": utc(event.created_at).isoformat(), "metadata": event.metadata_json, "prev_hash": event.prev_hash}


def hash_event(event: Audit) -> str:
    return sha256(json.dumps(audit_payload(event), sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def record(db, user, case_id, event_type, target_type, target_id, metadata=None, request_id=""):
    scope_key = f"{user.tenant_id}:{case_id or 'system'}"
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    db.execute(insert(AuditHead).values(scope_key=scope_key, sequence=0, event_hash="").on_conflict_do_nothing(index_elements=["scope_key"]))
    row = db.execute(update(AuditHead).where(AuditHead.scope_key == scope_key).values(sequence=AuditHead.sequence + 1).returning(AuditHead.sequence, AuditHead.event_hash)).one()
    event = Audit(id=new_id(), created_at=now(), tenant_id=user.tenant_id, case_id=case_id, actor_id=user.id, sequence=row.sequence, event_type=event_type, target_type=target_type, target_id=str(target_id), request_id=request_id, metadata_json=metadata or {}, prev_hash=row.event_hash, event_hash="")
    event.event_hash = hash_event(event)
    db.add(event)
    db.execute(update(AuditHead).where(AuditHead.scope_key == scope_key).values(event_hash=event.event_hash))
    db.flush()
    return event


def verify_chain(db, tenant_id: str, case_id: str | None) -> dict:
    previous, count = "", 0
    query = select(Audit).where(Audit.tenant_id == tenant_id, Audit.case_id == case_id).order_by(Audit.sequence)
    for event in db.scalars(query).yield_per(200):
        count += 1
        if event.sequence != count or event.prev_hash != previous or hash_event(event) != event.event_hash:
            return {"valid": False, "events_checked": count, "first_invalid_event": event.id}
        previous = event.event_hash
    head = db.get(AuditHead, f"{tenant_id}:{case_id or 'system'}")
    valid = (head is None and count == 0) or (head is not None and head.sequence == count and head.event_hash == previous)
    return {"valid": valid, "events_checked": count, "head_hash": previous, "assurance": "Application hash chain; no independently protected signing anchor configured."}


def event_json(event: Audit) -> dict:
    return {**audit_payload(event), "event_hash": event.event_hash, "created_at": utc(event.created_at).isoformat()}
