"""Change signals for authorized browser/desktop clients; no evidence replication."""

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .models import now
from .sync_models import FirmSyncRevision


def scope_key(tenant_id, case_id=None):
    return f"{tenant_id}:{case_id or 'system'}"


def record_change(db, tenant_id, case_id, event_type):
    # Reading evidence still belongs in the audit chain, but must not cause a
    # refresh/read/refresh loop on all connected computers.
    if event_type.rsplit(".", 1)[-1] in {"viewed", "searched", "downloaded", "previewed"}:
        return
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    scopes = [case_id]
    if case_id and (event_type.startswith("matter.") or event_type.startswith("member.")):
        scopes.insert(0, None)
    for current_scope in scopes:
        row = insert(FirmSyncRevision).values(
            scope_key=scope_key(tenant_id, current_scope),
            tenant_id=tenant_id,
            case_id=current_scope,
            revision=1,
            updated_at=now(),
        )
        db.execute(
            row.on_conflict_do_update(
                index_elements=["scope_key"],
                set_={"revision": FirmSyncRevision.revision + 1, "updated_at": now()},
            )
        )


def revision(db, tenant_id, case_id=None):
    row = db.get(FirmSyncRevision, scope_key(tenant_id, case_id))
    return row.revision if row else 0
