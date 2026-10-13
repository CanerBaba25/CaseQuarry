"""Serialize matter team changes with the task actions they authorize."""

from sqlalchemy import select, update

from .models import Case, User
from .security import authorize_case, fail


def lock_case_action(db, user, case_id, permission, user_ids=()):
    # Authorize before locking, then refresh authority after acquiring the row.
    authorize_case(db, user, case_id, permission)
    db.execute(update(Case).where(Case.id == case_id, Case.tenant_id == user.tenant_id).values(updated_at=Case.updated_at))
    tenant_id, user_id = user.tenant_id, user.id
    db.expire_all()
    # Lock actor and target users in a consistent order across different matters.
    # NO KEY UPDATE also remains compatible with foreign-key reference checks.
    identifiers = {user_id, *(identifier for identifier in user_ids if identifier)}
    users = db.scalars(select(User).where(User.id.in_(identifiers), User.tenant_id == tenant_id).order_by(User.id).with_for_update(key_share=True)).all()
    fresh_user = next((item for item in users if item.id == user_id), None)
    if fresh_user is None or not fresh_user.active:
        fail(401, "ACCOUNT_DISABLED", "This account is unavailable.")
    return authorize_case(db, fresh_user, case_id, permission)
