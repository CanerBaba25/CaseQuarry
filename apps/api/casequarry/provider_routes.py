"""Authenticated current-user credential controls; saving never contacts a provider."""

import re
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import Field, SecretStr
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from . import audit
from .models import Setting, Tenant, new_id, now
from .provider_models import ProviderCredential
from .provider_service import (
    PROVIDERS,
    credential_json,
    decrypt_key,
    encrypt_key,
    firm_policy_json,
    provider,
    validate_model,
)
from .schemas import Input, Reason
from .security import Actor, current_actor, fail, get_db

router = APIRouter(prefix="/api/v1")
ProviderID = Literal["openai", "gemini", "xai", "anthropic"]


class CredentialInput(Input):
    api_key: SecretStr | None = Field(default=None, min_length=10, max_length=512)
    model: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(default=0, ge=0)


class CloudPolicyInput(Reason):
    enabled: bool
    allowed_providers: list[ProviderID] = Field(default_factory=list, max_length=4)
    confirmed: bool = False
    expected_revision: int | None = Field(default=None, ge=0)


def _key(value):
    if not re.fullmatch(r"[\x21-\x7e]{10,512}", value) or any(marker in value.lower() for marker in ("***", "...", "redacted", "placeholder", "your_api", "your-api", "<", ">")):
        fail(422, "PROVIDER_KEY_INVALID", "Enter the complete API key; masked placeholders, whitespace and control characters are not accepted.")
    return value


@router.get("/ai/credentials")
def list_credentials(actor: Actor = Depends(current_actor), db=Depends(get_db)):
    rows = {row.provider: row for row in db.scalars(select(ProviderCredential).where(ProviderCredential.tenant_id == actor.user.tenant_id, ProviderCredential.user_id == actor.user.id))}
    return {"items": [credential_json(identifier, rows.get(identifier)) for identifier in PROVIDERS], "scope": "current_user", "validation": "Saving performs no vendor request and does not validate key, account or model availability."}


@router.put("/ai/credentials/{identifier}")
def save_credential(identifier: ProviderID, body: CredentialInput, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    provider(identifier)
    model = validate_model(body.model)
    existing = db.scalar(select(ProviderCredential).where(ProviderCredential.tenant_id == actor.user.tenant_id, ProviderCredential.user_id == actor.user.id, ProviderCredential.provider == identifier))
    if body.expected_revision != (existing.revision if existing else 0):
        fail(409, "PROVIDER_CREDENTIAL_CONFLICT", "Your credential changed. Refresh its current revision before saving.")
    if body.api_key is None:
        if existing is None or existing.revoked:
            fail(422, "PROVIDER_KEY_REQUIRED", "Provide a complete API key for the first save or after revocation.")
        key = decrypt_key(request.app.state.settings, existing)
    else:
        key = _key(body.api_key.get_secret_value())
    if model == key:
        fail(422, "PROVIDER_MODEL_INVALID", "The model identifier must not contain your API key.")
    if existing is None:
        row = ProviderCredential(id=new_id(), tenant_id=actor.user.tenant_id, user_id=actor.user.id, provider=identifier, model=model, last_four=key[-4:], revision=1, revoked=False)
        row.ciphertext = encrypt_key(request.app.state.settings, row, key)
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            fail(409, "PROVIDER_CREDENTIAL_CONFLICT", "A credential was saved concurrently. Refresh before updating it.")
    else:
        encrypted = encrypt_key(request.app.state.settings, existing, key)
        changed = db.execute(update(ProviderCredential).where(ProviderCredential.id == existing.id, ProviderCredential.revision == body.expected_revision).values(ciphertext=encrypted, last_four=key[-4:], model=model, revision=body.expected_revision + 1, revoked=False, updated_at=now())).rowcount
        if not changed:
            fail(409, "PROVIDER_CREDENTIAL_CONFLICT", "Your credential changed. Refresh before updating it.")
        row = existing
    audit.record(db, actor.user, None, "provider.credential_saved", "provider_credential", row.id, {"provider": identifier, "model": model, "revision": row.revision}, getattr(request.state, "request_id", ""))
    db.commit()
    db.refresh(row)
    return credential_json(identifier, row)


@router.delete("/ai/credentials/{identifier}")
def revoke_credential(identifier: ProviderID, body: Reason, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    if len(body.reason.strip()) < 3:
        fail(422, "REASON_REQUIRED", "Give a meaningful reason for revoking this key.")
    row = db.scalar(select(ProviderCredential).where(ProviderCredential.tenant_id == actor.user.tenant_id, ProviderCredential.user_id == actor.user.id, ProviderCredential.provider == identifier))
    if row is None:
        fail(404, "NOT_FOUND", "Your provider credential is unavailable.")
    db.execute(update(ProviderCredential).where(ProviderCredential.id == row.id).values(ciphertext="", last_four="", revoked=True, revision=ProviderCredential.revision + 1, updated_at=now()))
    audit.record(db, actor.user, None, "provider.credential_revoked", "provider_credential", row.id, {"provider": identifier}, getattr(request.state, "request_id", ""))
    db.commit()
    db.refresh(row)
    return credential_json(identifier, row)


@router.get("/ai/cloud-policy")
def get_cloud_policy(request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    return firm_policy_json(db, actor.user, request.app.state.settings)


@router.patch("/ai/cloud-policy")
def update_cloud_policy(body: CloudPolicyInput, request: Request, actor: Actor = Depends(current_actor), db=Depends(get_db)):
    db.execute(update(Tenant).where(Tenant.id == actor.user.tenant_id).values(name=Tenant.name))
    db.refresh(actor.user)
    if not actor.user.active or actor.user.role != "firm_admin":
        fail(403, "CLOUD_POLICY_PERMISSION_DENIED", "Only a firm administrator may authorize external provider processing.")
    if body.enabled and (not body.confirmed or len(body.reason.strip()) < 3 or not body.allowed_providers):
        fail(422, "CLOUD_POLICY_CONFIRMATION_REQUIRED", "Choose providers, confirm external processing and state its authorized purpose.")
    if body.enabled and not request.app.state.settings.allow_remote_ai:
        fail(503, "CLOUD_SERVER_DISABLED", "This server's operator has disabled cloud processing.")
    key = f"cloud-policy:{actor.user.tenant_id}"
    row = db.scalar(select(Setting).where(Setting.key == key).with_for_update())
    current = row.value.get("revision", 0) if row else 0
    if body.expected_revision is not None and current != body.expected_revision:
        fail(409, "CLOUD_POLICY_CONFLICT", "Another administrator changed this policy. Reload before saving.")
    value = {"tenant_id": actor.user.tenant_id, "enabled": body.enabled, "allowed_providers": sorted(set(body.allowed_providers)), "revision": current + 1, "approved_by": actor.user.id if body.enabled else None, "approved_at": now().isoformat() if body.enabled else None}
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))
    audit.record(db, actor.user, None, "provider.firm_policy_changed", "tenant", actor.user.tenant_id, {"enabled": body.enabled, "providers": value["allowed_providers"], "revision": current + 1, "reason": body.reason.strip()}, getattr(request.state, "request_id", ""))
    db.commit()
    return firm_policy_json(db, actor.user, request.app.state.settings)
