"""Account security and tenant administration with explicit concurrency controls."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import func, select, update

from . import audit
from .mfa_routes import valid_mfa
from .models import Audit, LoginSession, Tenant, User, now
from .schemas import Input, Reason
from .security import PASSWORDS, Actor, current_actor, fail, get_db, password_valid, user_json, utc

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


def require_admin(db, actor, *, lock=False):
    if lock:
        # A tenant row write serializes the last-administrator invariant on SQLite and PostgreSQL.
        db.execute(update(Tenant).where(Tenant.id == actor.user.tenant_id).values(name=Tenant.name))
        db.refresh(actor.user)
    if not actor.user.active or actor.user.role != "firm_admin":
        fail(403, "PERMISSION_DENIED", "Firm administrator access is required.")


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
    row = db.scalar(select(User).where(User.id == user_id, User.tenant_id == actor.user.tenant_id))
    if row is None:
        fail(404, "NOT_FOUND", "This user is unavailable.")
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
