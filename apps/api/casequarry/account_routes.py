"""Account security and tenant administration with explicit concurrency controls."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field, field_validator
from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import aliased

from . import audit
from .mfa_routes import valid_mfa
from .models import Audit, Case, LoginSession, Member, Tenant, User, now
from .schemas import Input, Reason
from .security import PASSWORDS, Actor, current_actor, fail, get_db, password_valid, user_json, utc
from .time_zones import names as time_zone_names
from .time_zones import validate as validate_time_zone

router = APIRouter(prefix="/api/v1")


class PasswordChange(Input):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)
    totp_code: str | None = Field(default=None, max_length=6)


class UserPatch(Reason):
    active: bool | None = None
    role: (
        Literal["firm_admin", "attorney", "review_manager", "reviewer", "expert", "read_only", "auditor"]
        | None
    ) = None
    expected_active: bool
    expected_role: str = Field(max_length=30)


class UserPreferences(Input):
    time_zone: str = Field(min_length=1, max_length=100, strict=True)

    @field_validator("time_zone")
    @classmethod
    def supported_zone(cls, value):
        return validate_time_zone(value)


@router.get("/timezones")
def time_zones(actor: Actor = Depends(current_actor)):
    return {"items": time_zone_names(), "default": "UTC", "current": actor.user.time_zone}


@router.patch("/me/preferences")
def preferences(body: UserPreferences, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    db.refresh(actor.user, with_for_update={"key_share": True})
    if not actor.user.active:
        fail(401, "ACCOUNT_DISABLED", "This account is unavailable.")
    changed = actor.user.time_zone != body.time_zone
    if changed:
        actor.user.time_zone = body.time_zone
        audit.record(db, actor.user, None, "user.preferences_updated", "user", actor.user.id, {"fields": ["time_zone"]}, request.state.request_id)
        db.commit()
    return {**user_json(actor.user), "changed": changed}


def require_admin(db, actor, *, lock=False):
    if lock:
        # A tenant row write serializes the last-administrator invariant on SQLite and PostgreSQL.
        db.execute(update(Tenant).where(Tenant.id == actor.user.tenant_id).values(name=Tenant.name))
        db.refresh(actor.user)
    if not actor.user.active or actor.user.role != "firm_admin":
        fail(403, "PERMISSION_DENIED", "Firm administrator access is required.")


def _lock_user_and_matters(db, actor, user_id):
    """Use the same matter-before-sorted-users order as team and task changes."""
    tenant_id, actor_id = actor.user.tenant_id, actor.user.id
    for _attempt in range(3):
        scopes = select(Member.case_id).join(Case, and_(Case.id == Member.case_id, Case.tenant_id == Member.tenant_id)).where(Member.tenant_id == tenant_id, Member.user_id == user_id)
        case_ids = set(db.scalars(scopes))
        if case_ids:
            db.scalars(select(Case.id).where(Case.tenant_id == tenant_id, Case.id.in_(case_ids)).order_by(Case.id).with_for_update()).all()
        db.expire_all()
        users = {row.id: row for row in db.scalars(select(User).where(User.tenant_id == tenant_id, User.id.in_({actor_id, user_id})).order_by(User.id).with_for_update(key_share=True))}
        admin = users.get(actor_id)
        if admin is None or not admin.active or admin.role != "firm_admin":
            fail(403, "PERMISSION_DENIED", "Firm administrator access is required.")
        if user_id not in users:
            fail(404, "NOT_FOUND", "This user is unavailable.")
        if set(db.scalars(scopes)) <= case_ids:
            return users[user_id]
        # A concurrent grant added a matter before the user lock. Retry without
        # taking a new matter lock while retaining a user lock in the wrong order.
        db.rollback()
        require_admin(db, actor, lock=True)
    fail(409, "USER_TEAM_SCOPE_CHANGED", "This user's matter memberships are changing. Refresh and try again.", True)


def _guard_active_matter_lead(db, tenant_id, user_id):
    other, other_user = aliased(Member), aliased(User)
    another_lead = select(other.id).join(other_user, and_(other_user.id == other.user_id, other_user.tenant_id == other.tenant_id)).where(
        other.tenant_id == tenant_id, other.case_id == Member.case_id,
        other.role == "matter_lead", other.user_id != user_id, other_user.active.is_(True),
    ).correlate(Member).exists()
    stranded = db.scalar(select(Member.case_id).join(Case, and_(Case.id == Member.case_id, Case.tenant_id == Member.tenant_id)).where(
        Member.tenant_id == tenant_id, Member.user_id == user_id, Member.role == "matter_lead", ~another_lead,
    ).limit(1))
    if stranded:
        fail(409, "LAST_MATTER_LEAD", "Assign another active lead to this user's matters before deactivating the account.")


@router.get("/auth/sessions")
def sessions(actor: Actor = Depends(current_actor), db=Depends(get_db)):
    rows = db.scalars(
        select(LoginSession)
        .where(
            LoginSession.user_id == actor.user.id,
            LoginSession.revoked.is_(False),
            LoginSession.expires_at > now(),
        )
        .order_by(LoginSession.created_at.desc())
        .limit(100)
    )
    return {
        "items": [
            {
                "id": row.id,
                "current": row.id == actor.session.id,
                "created_at": utc(row.created_at).isoformat(),
                "expires_at": utc(row.expires_at).isoformat(),
            }
            for row in rows
        ],
        "limit": 100,
    }


@router.post("/auth/sessions/{session_id}/revoke")
def revoke_session(
    session_id: str, body: Reason, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)
):
    row = db.scalar(
        select(LoginSession).where(LoginSession.id == session_id, LoginSession.user_id == actor.user.id)
    )
    if row is None:
        fail(404, "NOT_FOUND", "This session is unavailable.")
    row.revoked = True
    audit.record(
        db,
        actor.user,
        None,
        "auth.session_revoked",
        "session",
        row.id,
        {"reason": body.reason, "current": row.id == actor.session.id},
        request.state.request_id,
    )
    db.commit()
    return {"revoked": True, "current": row.id == actor.session.id}


@router.post("/auth/password/change")
def change_password(
    body: PasswordChange, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)
):
    previous = actor.user.password_hash
    if (
        not password_valid(body.current_password, previous)
        or actor.user.mfa_enabled
        and not valid_mfa(request.app.state.storage, actor.user, body.totp_code)
    ):
        fail(401, "INVALID_CREDENTIALS", "Password or authenticator code is incorrect.")
    if body.current_password == body.new_password:
        fail(422, "PASSWORD_UNCHANGED", "Choose a different password.")
    changed = db.execute(
        update(User)
        .where(User.id == actor.user.id, User.password_hash == previous)
        .values(password_hash=PASSWORDS.hash(body.new_password))
    )
    if changed.rowcount != 1:
        fail(409, "PASSWORD_VERSION_CONFLICT", "Your password changed during this request. Sign in again.")
    revoked = db.execute(
        update(LoginSession)
        .where(
            LoginSession.user_id == actor.user.id,
            LoginSession.id != actor.session.id,
            LoginSession.revoked.is_(False),
        )
        .values(revoked=True)
    ).rowcount
    audit.record(
        db,
        actor.user,
        None,
        "auth.password_changed",
        "user",
        actor.user.id,
        {"other_sessions_revoked": revoked},
        request.state.request_id,
    )
    db.commit()
    return {"changed": True, "other_sessions_revoked": revoked, "current_session_preserved": True}


@router.patch("/users/{user_id}")
def patch_user(
    user_id: str, body: UserPatch, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)
):
    require_admin(db, actor, lock=True)
    row = _lock_user_and_matters(db, actor, user_id)
    if row.active != body.expected_active or row.role != body.expected_role:
        fail(409, "USER_VERSION_CONFLICT", "Another administrator changed this user. Refresh before saving.")
    changes = body.model_dump(exclude_none=True, include={"active", "role"})
    if not changes:
        fail(422, "USER_CHANGE_EMPTY", "Choose an account status or role change.")
    active, role = changes.get("active", row.active), changes.get("role", row.role)
    reducing_admin = row.active and row.role == "firm_admin" and (not active or role != "firm_admin")
    if user_id == actor.user.id and (not active or role != "firm_admin"):
        fail(
            409,
            "SELF_LOCKOUT_BLOCKED",
            "Ask another administrator to change your account role or deactivate it.",
        )
    if (
        reducing_admin
        and (
            db.scalar(
                select(func.count())
                .select_from(User)
                .where(
                    User.tenant_id == actor.user.tenant_id, User.active.is_(True), User.role == "firm_admin"
                )
            )
            or 0
        )
        <= 1
    ):
        fail(409, "LAST_ADMIN_BLOCKED", "Keep at least one active firm administrator.")
    if row.active and not active:
        _guard_active_matter_lead(db, actor.user.tenant_id, user_id)
    result = db.execute(
        update(User)
        .where(
            User.id == user_id,
            User.tenant_id == actor.user.tenant_id,
            User.active == body.expected_active,
            User.role == body.expected_role,
        )
        .values(**changes)
    )
    if result.rowcount != 1:
        fail(409, "USER_VERSION_CONFLICT", "Another administrator changed this user. Refresh before saving.")
    revoked = 0
    if not active or role != body.expected_role:
        revoked = db.execute(
            update(LoginSession)
            .where(LoginSession.user_id == user_id, LoginSession.revoked.is_(False))
            .values(revoked=True)
        ).rowcount
    audit.record(
        db,
        actor.user,
        None,
        "user.updated",
        "user",
        user_id,
        {"changes": changes, "reason": body.reason, "sessions_revoked": revoked},
        request.state.request_id,
    )
    db.commit()
    db.refresh(row)
    return {**user_json(row), "sessions_revoked": revoked}


@router.get("/system/audit")
def system_audit(
    limit: int = Query(50, ge=1, le=200),
    before_sequence: int | None = Query(None, ge=1),
    actor: Actor = Depends(current_actor),
    db=Depends(get_db),
):
    require_admin(db, actor)
    query = select(Audit).where(Audit.tenant_id == actor.user.tenant_id, Audit.case_id.is_(None))
    if before_sequence is not None:
        query = query.where(Audit.sequence < before_sequence)
    rows = list(db.scalars(query.order_by(Audit.sequence.desc()).limit(limit + 1)))
    return {
        "items": [audit.event_json(row) for row in rows[:limit]],
        "before_sequence": rows[limit - 1].sequence if len(rows) > limit else None,
        "scope": "tenant_system",
    }


@router.post("/system/audit/verify")
def verify_system_audit(actor: Actor = Depends(current_actor), db=Depends(get_db)):
    require_admin(db, actor)
    return audit.verify_chain(db, actor.user.tenant_id, None)
