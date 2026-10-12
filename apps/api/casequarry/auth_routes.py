from datetime import timedelta
from secrets import compare_digest

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import audit
from .models import Setting, Tenant, User, now
from .schemas import LoginInput, SetupInput, UserInput
from .security import (
    PASSWORDS,
    Actor,
    create_session,
    current_actor,
    digest,
    fail,
    get_db,
    password_valid,
    user_json,
    utc,
)

router = APIRouter(prefix="/api/v1")


def set_session_cookies(response, request, token, csrf):
    settings = request.app.state.settings
    response.set_cookie("cq_session", token, max_age=settings.session_ttl_seconds, httponly=True, secure=settings.secure_cookies, samesite="lax", path="/")
    response.set_cookie("cq_csrf", csrf, max_age=settings.session_ttl_seconds, httponly=False, secure=settings.secure_cookies, samesite="lax", path="/")


@router.get("/setup")
def setup_status(request: Request, db=Depends(get_db)):
    required = db.scalar(select(Tenant.id).limit(1)) is None
    policy = db.get(Setting, "setup-policy")
    return {"required": required, "token_required": required, "token_expired": bool(required and policy and utc(policy.created_at) + timedelta(seconds=request.app.state.settings.setup_token_ttl_seconds) <= now())}


@router.post("/setup", status_code=201)
def setup(body: SetupInput, request: Request, response: Response, db=Depends(get_db)):
    if db.scalar(select(Tenant.id).limit(1)):
        fail(409, "SETUP_COMPLETE", "Administrator setup has already completed.")
    policy = db.get(Setting, "setup-policy")
    if policy is None or not compare_digest(digest(body.token), policy.value.get("token_hash", "")) or utc(policy.created_at) + timedelta(seconds=request.app.state.settings.setup_token_ttl_seconds) <= now():
        fail(403, "SETUP_TOKEN_INVALID", "The setup token is incorrect or expired. Rotate it locally and restart the service.")
    if "@" not in body.email or len(body.email.rsplit("@", 1)[1]) < 3:
        fail(422, "EMAIL_INVALID", "Enter a valid email address.")
    tenant = Tenant(name=body.firm_name.strip())
    db.add(tenant)
    db.flush()
    user = User(tenant_id=tenant.id, email=body.email.strip().lower(), name=body.name.strip(), password_hash=PASSWORDS.hash(body.password), role="firm_admin")
    db.add(user)
    db.flush()
    _, token, csrf = create_session(db, user, request.app.state.settings.session_ttl_seconds)
    db.add(Setting(key="setup-complete", value={"tenant_id": tenant.id}))
    audit.record(db, user, None, "system.bootstrapped", "tenant", tenant.id, request_id=request.state.request_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, "SETUP_COMPLETE", "Administrator setup has already completed.")
    set_session_cookies(response, request, token, csrf)
    return {"user": user_json(user), "csrf_token": csrf}


def authenticate(body, request, db):
    email = body.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    encoded = user.password_hash if user else request.app.state.dummy_password_hash
    valid = password_valid(body.password, encoded)
    if not user or not user.active or not valid:
        fail(401, "INVALID_CREDENTIALS", "Email, password or authentication code is incorrect.")
    if user.mfa_enabled:
        from .mfa_routes import valid_mfa
        if not valid_mfa(request.app.state.storage, user, body.totp_code):
            fail(401, "MFA_REQUIRED", "A valid authentication code is required.")
    return user


@router.post("/auth/login")
def login(body: LoginInput, request: Request, response: Response, db=Depends(get_db)):
    user = authenticate(body, request, db)
    _, token, csrf = create_session(db, user, request.app.state.settings.session_ttl_seconds)
    audit.record(db, user, None, "auth.login", "user", user.id, request_id=request.state.request_id)
    db.commit()
    set_session_cookies(response, request, token, csrf)
    return {"user": user_json(user), "csrf_token": csrf}


@router.post("/auth/token")
def token_login(body: LoginInput, request: Request, db=Depends(get_db)):
    user = authenticate(body, request, db)
    _, token, _ = create_session(db, user, request.app.state.settings.session_ttl_seconds)
    audit.record(db, user, None, "auth.token_issued", "user", user.id, request_id=request.state.request_id)
    db.commit()
    return {"access_token": token, "token_type": "bearer", "expires_in": request.app.state.settings.session_ttl_seconds, "user": user_json(user)}


@router.post("/auth/logout")
def logout(request: Request, response: Response, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    actor.session.revoked = True
    audit.record(db, actor.user, None, "auth.logout", "session", actor.session.id, request_id=request.state.request_id)
    db.commit()
    response.delete_cookie("cq_session", path="/")
    response.delete_cookie("cq_csrf", path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request, actor: Actor = Depends(current_actor)):
    return {**user_json(actor.user), "csrf_token": request.cookies.get("cq_csrf") if not actor.bearer else None}


@router.get("/users")
def users(actor: Actor = Depends(current_actor), db=Depends(get_db)):
    if actor.user.role != "firm_admin":
        fail(403, "PERMISSION_DENIED", "Firm administrator access is required.")
    return {"items": [user_json(user) for user in db.scalars(select(User).where(User.tenant_id == actor.user.tenant_id).order_by(User.name).limit(200))]}


@router.post("/users", status_code=201)
def create_user(body: UserInput, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    if actor.user.role != "firm_admin":
        fail(403, "PERMISSION_DENIED", "Firm administrator access is required.")
    if "@" not in body.email:
        fail(422, "EMAIL_INVALID", "Enter a valid email address.")
    if db.scalar(select(User.id).where(User.email == body.email.strip().lower())):
        fail(409, "USER_EXISTS", "This email is already registered.")
    user = User(tenant_id=actor.user.tenant_id, email=body.email.strip().lower(), name=body.name, password_hash=PASSWORDS.hash(body.password), role=body.role)
    db.add(user)
    db.flush()
    audit.record(db, actor.user, None, "user.created", "user", user.id, {"role": user.role}, request.state.request_id)
    db.commit()
    return user_json(user)
