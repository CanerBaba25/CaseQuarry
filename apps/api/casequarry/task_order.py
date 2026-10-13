"""Transactional task-order invalidation, separate from ordinary task completion."""

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .models import Case, Member, User, now
from .security import PERMISSIONS
from .sync_models import FirmSyncRevision


def key(tenant_id, user_id, state_filtered=False):
    prefix = "worklist-state" if state_filtered else "worklist"
    return f"{prefix}:{tenant_id}:{user_id}"


def revision_expression(tenant_id, user_id, state_filtered=False):
    return func.coalesce(select(FirmSyncRevision.revision).where(
        FirmSyncRevision.scope_key == key(tenant_id, user_id, state_filtered),
        FirmSyncRevision.tenant_id == tenant_id, FirmSyncRevision.case_id.is_(None),
    ).scalar_subquery(), 0)


def creation_revision(tenant_id, case_id):
    return func.coalesce(select(FirmSyncRevision.revision).where(
        FirmSyncRevision.scope_key == f"task-list:{tenant_id}:{case_id}",
        FirmSyncRevision.tenant_id == tenant_id, FirmSyncRevision.case_id == case_id,
    ).scalar_subquery(), 0)


def bump_created(db, tenant_id, case_id):
    """Fence UUID-seek matter pages when creation commits after their snapshot."""
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    row = insert(FirmSyncRevision).values(scope_key=f"task-list:{tenant_id}:{case_id}", tenant_id=tenant_id, case_id=case_id, revision=1, updated_at=now())
    db.execute(row.on_conflict_do_update(index_elements=["scope_key"], set_={"revision": FirmSyncRevision.revision + 1, "updated_at": now()}))


def bump_visible(db, tenant_id, case_id, user_ids, *, state_only=False):
    """Only an active user's currently visible matter can invalidate their cursor."""
    identifiers = {value for value in user_ids if value}
    if not identifiers:
        return
    visible = db.scalars(select(User.id).join(Member, and_(Member.user_id == User.id, Member.tenant_id == User.tenant_id)).join(Case, and_(Case.id == Member.case_id, Case.tenant_id == Member.tenant_id)).where(
        User.id.in_(identifiers), User.tenant_id == tenant_id, User.active.is_(True),
        Member.case_id == case_id, Member.role.in_(PERMISSIONS["view"]), Case.archived_at.is_(None),
    ).order_by(User.id)).all()
    insert = sqlite_insert if db.bind.dialect.name == "sqlite" else pg_insert
    for user_id in visible:
        # Every ordering/access change fences both cursor scopes. Ordinary state
        # changes fence filtered pages without breaking all-active completion.
        for filtered in (True,) if state_only else (False, True):
            row = insert(FirmSyncRevision).values(scope_key=key(tenant_id, user_id, filtered), tenant_id=tenant_id, case_id=None, revision=1, updated_at=now())
            db.execute(row.on_conflict_do_update(index_elements=["scope_key"], set_={"revision": FirmSyncRevision.revision + 1, "updated_at": now()}))
