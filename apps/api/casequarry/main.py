import logging
import os
import re
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from secrets import token_bytes, token_urlsafe

from fastapi import Body, Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from starlette.exceptions import HTTPException

from . import (
    __version__,
    auth_routes,
    case_routes,
    evidence_routes,
    exports,
    governance_routes,
    import_routes,
    investigation_routes,
    mfa_routes,
)
from .config import Settings
from .database import Database
from .models import ImportBatch, Member, Setting, Tenant, now
from .security import PASSWORDS, Actor, authorize_case, current_actor, digest, fail, get_db
from .storage import Storage
from .worker import worker_loop

LOGGER = logging.getLogger("casequarry.api")


def secret_file(path, binary=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_bytes() if binary else path.read_text().strip()
    value = token_bytes(32) if binary else token_urlsafe(32)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value if binary else value.encode())
    return value


def prepare_setup(database, settings, storage):
    with database.sessions() as db:
        if db.scalar(select(Tenant.id).limit(1)):
            return
        token = settings.setup_token or secret_file(storage.root / "setup-token")
        token_hash = digest(token)
        policy = db.get(Setting, "setup-policy")
        if policy is None:
            db.add(Setting(key="setup-policy", value={"token_hash": token_hash}))
        elif policy.value.get("token_hash") != token_hash:
            policy.value, policy.created_at = {"token_hash": token_hash}, now()
        db.commit()


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    database, storage = Database(settings), Storage(settings.storage_path)
    stop_event = threading.Event()

    @asynccontextmanager
    async def lifespan(application):
        database.initialize()
        prepare_setup(database, settings, storage)
        worker = None
        if settings.worker_mode == "embedded":
            worker = threading.Thread(target=worker_loop, args=(database, settings, storage, stop_event), name="casequarry-worker", daemon=True)
            worker.start()
        yield
        stop_event.set()
        if worker:
            worker.join(timeout=5)
        database.dispose()

    application = FastAPI(title="CaseQuarry API", version=__version__, lifespan=lifespan, docs_url="/api/docs" if settings.environment != "production" else None, redoc_url=None, openapi_url="/api/openapi.json" if settings.environment != "production" else None)
    application.state.settings = settings
    application.state.db = database
    application.state.storage = storage
    application.state.cursor_secret = secret_file(storage.root / "secrets" / "cursor.key", binary=True)
    application.state.dummy_password_hash = PASSWORDS.hash(token_urlsafe(24))
    buckets, bucket_lock = defaultdict(deque), threading.Lock()

    @application.middleware("http")
    async def request_context(request, call_next):
        supplied = request.headers.get("x-request-id", "")
        request.state.request_id = supplied if re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", supplied) else token_urlsafe(12)
        group = "auth" if request.url.path.startswith("/api/v1/auth/") or request.url.path == "/api/v1/setup" and request.method == "POST" else "api"
        key = (request.client.host if request.client else "local", group)
        current = time.monotonic()
        with bucket_lock:
            bucket = buckets[key]
            while bucket and bucket[0] <= current - 60:
                bucket.popleft()
            maximum = 10 if group == "auth" else 240
            limited = len(bucket) >= maximum
            if not limited:
                bucket.append(current)
        if limited:
            response = JSONResponse({"error_code": "RATE_LIMITED", "message": "Too many requests. Wait before trying again.", "request_id": request.state.request_id, "retryable": True}, status_code=429, headers={"Retry-After": "60"})
        else:
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > settings.max_upload_bytes * settings.max_batch_files + 1024 * 1024):
                response = JSONResponse({"error_code": "REQUEST_TOO_LARGE", "message": "The request exceeds the configured limit.", "request_id": request.state.request_id, "retryable": False}, status_code=413)
            else:
                response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if not request.url.path.startswith("/api/docs"):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @application.exception_handler(HTTPException)
    async def http_error(request, error):
        details = error.detail if isinstance(error.detail, dict) else {"error_code": "HTTP_ERROR", "message": str(error.detail), "retryable": False}
        return JSONResponse({**details, "request_id": getattr(request.state, "request_id", "")}, status_code=error.status_code, headers=error.headers)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        errors = [{"field": ".".join(map(str, detail["loc"])), "message": detail["msg"]} for detail in error.errors()]
        return JSONResponse({"error_code": "VALIDATION_ERROR", "message": "Check the supplied fields.", "request_id": getattr(request.state, "request_id", ""), "retryable": False, "errors": errors}, status_code=422)

    @application.exception_handler(Exception)
    async def unexpected_error(request, error):
        LOGGER.error("request_failed request_id=%s error_type=%s", getattr(request.state, "request_id", ""), type(error).__name__)
        return JSONResponse({"error_code": "INTERNAL_ERROR", "message": "An unexpected service error occurred.", "request_id": getattr(request.state, "request_id", ""), "retryable": False}, status_code=500)

    for router in (auth_routes.router, case_routes.router, import_routes.router, evidence_routes.router, exports.router, governance_routes.router, investigation_routes.router, mfa_routes.router):
        application.include_router(router)

    @application.get("/api/v1/health")
    def health():
        with database.sessions() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok", "version": __version__, "database": "ok", "storage": "local", "search": "scoped-sql", "queue": settings.worker_mode, "ai_enabled": settings.ai_enabled, "remote_ai_enabled": False, "production_ready": False}

    @application.get("/api/v1/cases/{case_id}/ai/providers")
    @application.get("/api/v1/cases/{case_id}/ai/policy")
    def model_policy(case_id: str, actor: Actor = Depends(current_actor), db=Depends(get_db)):
        authorize_case(db, actor.user, case_id)
        return {"enabled": False, "provider": "none", "remote_ai_allowed": False, "providers": [{"id": "local", "name": "Local model", "configured": False, "enabled": False}], "reason": "The optional cited local-model adapter is not yet enabled in this release. Ingestion, search and human review work without a model."}

    @application.post("/api/v1/cases/{case_id}/ai/ask")
    @application.post("/api/v1/cases/{case_id}/ai/summarize")
    def unavailable_model(case_id: str, body: dict = Body(default={}), actor: Actor = Depends(current_actor), db=Depends(get_db)):
        authorize_case(db, actor.user, case_id)
        fail(503, "AI_UNAVAILABLE", "No cited local model is configured. Use keyword search and human review; no evidence was sent to a provider.")

    @application.get("/api/v1/system/jobs")
    def jobs(actor: Actor = Depends(current_actor), db=Depends(get_db)):
        ids = select(Member.case_id).where(Member.user_id == actor.user.id, Member.tenant_id == actor.user.tenant_id)
        batches = db.scalars(select(ImportBatch).where(ImportBatch.case_id.in_(ids), ImportBatch.tenant_id == actor.user.tenant_id).order_by(ImportBatch.created_at.desc()).limit(100))
        return {"items": [import_routes.batch_json(batch) for batch in batches]}

    return application


app = create_app()
