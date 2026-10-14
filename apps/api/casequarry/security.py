from dataclasses import dataclass
from datetime import UTC, timedelta
from hashlib import sha256
from secrets import compare_digest, token_urlsafe

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Case, LoginSession, Member, User, now

PASSWORDS = PasswordHasher()
ROLES = {"matter_lead", "attorney", "review_manager", "reviewer", "expert", "read_only", "auditor"}
PERMISSIONS = {
    "view": ROLES,
    "import": {"matter_lead", "attorney", "review_manager"},
    "review": {"matter_lead", "attorney", "review_manager", "reviewer"},
    "privilege": {"matter_lead", "attorney"},
    "manage": {"matter_lead", "review_manager"},
    "export": {"matter_lead", "attorney", "review_manager"},
    "hold": {"matter_lead", "attorney"},
    "audit": {"matter_lead", "attorney", "review_manager", "auditor"},
}


def fail(status: int, code: str, message: str, retryable: bool = False):
    raise HTTPException(status, detail={"error_code": code, "message": message, "retryable": retryable})


def digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def password_valid(password: str, encoded: str) -> bool:
    try:
        return PASSWORDS.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def get_db(request: Request):
    with request.app.state.db.sessions() as session:
        yield session


@dataclass
class Actor:
    user: User
    session: LoginSession
    bearer: bool


def current_actor(request: Request, db: Session = Depends(get_db)) -> Actor:
    header = request.headers.get("authorization", "")
    bearer = header.lower().startswith("bearer ")
    token = header[7:].strip() if bearer else request.cookies.get("cq_session", "")
    if not token or len(token) > 200:
        fail(401, "AUTH_REQUIRED", "Sign in to continue.")
    login = db.scalar(select(LoginSession).where(LoginSession.token_hash == digest(token)))
    if login is None or login.revoked or utc(login.expires_at) <= now():
        fail(401, "SESSION_EXPIRED", "Your session has expired. Sign in again.")
    user = db.get(User, login.user_id)
    if user is None or not user.active:
        fail(401, "ACCOUNT_DISABLED", "This account is unavailable.")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and not bearer:
        supplied = request.headers.get("x-csrf-token", "")
        if not supplied or not compare_digest(digest(supplied), login.csrf_hash):
            fail(403, "CSRF_INVALID", "Refresh the page before trying this action again.")
    return Actor(user=user, session=login, bearer=bearer)


def authorize_case(db: Session, user: User, case_id: str, permission: str = "view") -> tuple[Case, Member]:
    case = db.scalar(select(Case).where(Case.id == case_id, Case.tenant_id == user.tenant_id))
    member = db.scalar(select(Member).where(Member.case_id == case_id, Member.user_id == user.id, Member.tenant_id == user.tenant_id))
    if case is None or member is None:
        fail(404, "NOT_FOUND", "The matter or item is unavailable.")
    if member.role not in PERMISSIONS.get(permission, set()):
        fail(403, "PERMISSION_DENIED", "Your matter role does not allow this action.")
    if case.archived_at and permission in {"import", "review"}:
        fail(409, "MATTER_ARCHIVED", "Restore this archived matter before making changes.")
    return case, member


def create_session(db: Session, user: User, ttl_seconds: int):
    token, csrf = token_urlsafe(32), token_urlsafe(32)
    session = LoginSession(token_hash=digest(token), csrf_hash=digest(csrf), user_id=user.id, expires_at=now() + timedelta(seconds=ttl_seconds))
    db.add(session)
    db.flush()
    return session, token, csrf


def user_json(user: User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "tenant_id": user.tenant_id, "role": user.role, "active": user.active, "mfa_enabled": user.mfa_enabled, "time_zone": user.time_zone, "language": user.language}
