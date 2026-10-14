import json
import os
from datetime import UTC, datetime, timedelta

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import update

from . import audit
from .models import LoginSession
from .schemas import Input
from .security import Actor, current_actor, fail, get_db, lock_user, password_valid

router = APIRouter(prefix="/api/v1/auth/mfa")


class PasswordInput(Input):
    password: str = Field(min_length=1, max_length=1024)


class CodeInput(Input):
    code: str = Field(pattern=r"^\d{6}$")


class DisableInput(PasswordInput, CodeInput):
    pass


def cipher(storage):
    path = storage.root / "secrets" / "mfa.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        key = path.read_bytes()
    else:
        key = Fernet.generate_key()
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(key)
    return Fernet(key)


def read_secret(storage, encoded):
    try:
        return json.loads(cipher(storage).decrypt(encoded.encode()).decode())
    except (InvalidToken, ValueError, TypeError, AttributeError):
        return None


def valid_mfa(storage, user, code):
    payload = read_secret(storage, user.mfa_secret)
    return bool(payload and pyotp.TOTP(payload["secret"]).verify(code or "", valid_window=1))


def lock_actor(db, actor):
    lock_user(db, actor.user)
    if not actor.user.active:
        fail(401, "ACCOUNT_DISABLED", "This account is unavailable.")


@router.get("/status")
def status(actor: Actor = Depends(current_actor)):
    return {"enabled": actor.user.mfa_enabled, "method": "totp", "issuer": "CaseQuarry"}


@router.post("/enroll")
def enroll(body: PasswordInput, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    lock_actor(db, actor)
    if actor.user.mfa_enabled:
        fail(409, "MFA_ALREADY_ENABLED", "Disable the existing authenticator before enrolling another.")
    if not password_valid(body.password, actor.user.password_hash):
        fail(401, "INVALID_CREDENTIALS", "Your password is incorrect.")
    secret = pyotp.random_base32()
    payload = {"secret": secret, "created_at": datetime.now(UTC).isoformat()}
    actor.user.mfa_secret = cipher(request.app.state.storage).encrypt(json.dumps(payload).encode()).decode()
    audit.record(db, actor.user, None, "auth.mfa_enrollment_started", "user", actor.user.id, request_id=request.state.request_id)
    db.commit()
    return {"secret": secret, "provisioning_uri": pyotp.TOTP(secret).provisioning_uri(actor.user.email, issuer_name="CaseQuarry"), "expires_in": 600, "enabled": False}


@router.post("/confirm")
def confirm(body: CodeInput, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    lock_actor(db, actor)
    payload = read_secret(request.app.state.storage, actor.user.mfa_secret)
    if not payload or datetime.fromisoformat(payload["created_at"]) + timedelta(minutes=10) < datetime.now(UTC):
        fail(409, "MFA_ENROLLMENT_EXPIRED", "Start authenticator enrollment again.")
    if not pyotp.TOTP(payload["secret"]).verify(body.code, valid_window=1):
        fail(401, "MFA_CODE_INVALID", "The authenticator code is incorrect.")
    actor.user.mfa_enabled = True
    db.execute(update(LoginSession).where(LoginSession.user_id == actor.user.id, LoginSession.id != actor.session.id).values(revoked=True))
    audit.record(db, actor.user, None, "auth.mfa_enabled", "user", actor.user.id, request_id=request.state.request_id)
    db.commit()
    return {"enabled": True, "other_sessions_revoked": True}


@router.post("/disable")
def disable(body: DisableInput, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    lock_actor(db, actor)
    if not actor.user.mfa_enabled:
        fail(409, "MFA_NOT_ENABLED", "No authenticator is enabled.")
    if not password_valid(body.password, actor.user.password_hash) or not valid_mfa(request.app.state.storage, actor.user, body.code):
        fail(401, "INVALID_CREDENTIALS", "Password or authenticator code is incorrect.")
    actor.user.mfa_secret, actor.user.mfa_enabled = None, False
    db.execute(update(LoginSession).where(LoginSession.user_id == actor.user.id, LoginSession.id != actor.session.id).values(revoked=True))
    audit.record(db, actor.user, None, "auth.mfa_disabled", "user", actor.user.id, request_id=request.state.request_id)
    db.commit()
    return {"enabled": False, "other_sessions_revoked": True}
