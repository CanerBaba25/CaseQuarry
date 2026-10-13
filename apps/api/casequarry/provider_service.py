"""User-owned encrypted credentials and explicit firm authorization for cloud APIs."""

import json
import re

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from .models import Setting, User
from .provider_models import ProviderCredential
from .security import fail, utc

PROVIDERS = {
    "openai": {"name": "OpenAI API", "endpoint": "https://api.openai.com/v1/responses"},
    "gemini": {"name": "Google Gemini API", "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/"},
    "xai": {"name": "xAI Grok API", "endpoint": "https://api.x.ai/v1/chat/completions"},
    "anthropic": {"name": "Anthropic Claude API", "endpoint": "https://api.anthropic.com/v1/messages"},
}
MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}")
CLOUD_WARNINGS = [
    "Cloud jobs transmit selected extracted evidence to the chosen external provider using your own API key and may incur charges.",
    "Saving a key does not test it or authorize transmission. Review the provider account's current retention, training, region and billing terms.",
    "OpenAI requests disable response storage; this does not establish zero data retention. Other providers retain their own account-specific policies.",
]


def provider(identifier):
    if identifier not in PROVIDERS:
        fail(503, "REMOTE_AI_UNAVAILABLE", "Choose an implemented cloud provider: openai, gemini, xai or anthropic.")
    return PROVIDERS[identifier]


def validate_model(value):
    if not MODEL_PATTERN.fullmatch(value) or value.startswith(("sk-", "AIza", "xai-")):
        fail(422, "PROVIDER_MODEL_INVALID", "Provide a compatible provider model identifier, without a URL, API key or path.")
    return value


def encryption(settings):
    key = getattr(settings, "provider_key_encryption_key", None)
    if not key:
        fail(503, "PROVIDER_ENCRYPTION_UNAVAILABLE", "Configure the server's private provider encryption key before saving credentials.")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeError, TypeError):
        fail(503, "PROVIDER_ENCRYPTION_UNAVAILABLE", "The server provider encryption key is invalid.")


def encrypt_key(settings, row, api_key):
    value = {"tenant_id": row.tenant_id, "user_id": row.user_id, "provider": row.provider, "credential_id": row.id, "api_key": api_key}
    return encryption(settings).encrypt(json.dumps(value, separators=(",", ":")).encode()).decode("ascii")


def decrypt_key(settings, row):
    try:
        value = json.loads(encryption(settings).decrypt(row.ciphertext.encode("ascii")))
        context = {"tenant_id": row.tenant_id, "user_id": row.user_id, "provider": row.provider, "credential_id": row.id}
        if any(value.get(key) != desired for key, desired in context.items()) or not isinstance(value.get("api_key"), str):
            fail(409, "PROVIDER_CREDENTIAL_INTEGRITY_FAILED", "The encrypted credential scope could not be verified.")
        return value["api_key"]
    except (InvalidToken, ValueError, UnicodeError, TypeError, AttributeError):
        fail(409, "PROVIDER_CREDENTIAL_INTEGRITY_FAILED", "The encrypted credential could not be verified with this server's key.")


def credential(db, user, identifier, *, revision=None):
    provider(identifier)
    row = db.scalar(select(ProviderCredential).where(ProviderCredential.tenant_id == user.tenant_id, ProviderCredential.user_id == user.id, ProviderCredential.provider == identifier))
    if row is None or row.revoked or not row.ciphertext:
        fail(503, "PROVIDER_CREDENTIAL_REQUIRED", "Save your own API key and compatible model for the selected provider first.")
    if revision is not None and row.revision != revision:
        fail(409, "PROVIDER_CREDENTIAL_CHANGED", "Your provider credential changed. Request a new job using its current configuration.")
    return row


def credential_json(identifier, row=None):
    configured = bool(row and not row.revoked and row.ciphertext)
    return {"provider": identifier, "name": provider(identifier)["name"], "configured": configured, "masked_key": "\u2022" * 4 + row.last_four if configured else None, "model": row.model if row else None, "revision": row.revision if row else 0, "revoked": bool(row and row.revoked), "updated_at": utc(row.updated_at).isoformat() if row else None, "validation_status": "saved_not_tested" if configured else "not_configured"}


def firm_policy(db, user, settings):
    row = db.get(Setting, f"cloud-policy:{user.tenant_id}")
    value = row.value if row and row.value.get("tenant_id") == user.tenant_id else {}
    approved = db.scalar(select(User.id).where(User.id == value.get("approved_by"), User.tenant_id == user.tenant_id, User.active.is_(True), User.role == "firm_admin")) if value.get("enabled") else None
    allowed = [identifier for identifier in value.get("allowed_providers", []) if identifier in PROVIDERS]
    return value, bool(settings.allow_remote_ai and value.get("enabled") and approved and allowed)


def firm_policy_json(db, user, settings):
    value, effective = firm_policy(db, user, settings)
    return {"enabled": bool(value.get("enabled")), "effective_enabled": effective, "server_capable": bool(settings.allow_remote_ai), "allowed_providers": [identifier for identifier in value.get("allowed_providers", []) if identifier in PROVIDERS], "revision": value.get("revision", 0), "approved_by": value.get("approved_by"), "approved_at": value.get("approved_at"), "warnings": CLOUD_WARNINGS}


def require_firm_policy(db, user, settings, identifier, *, revision=None):
    provider(identifier)
    value, effective = firm_policy(db, user, settings)
    if not effective or identifier not in value.get("allowed_providers", []):
        fail(503, "CLOUD_FIRM_CONSENT_REQUIRED", "An active firm administrator must explicitly enable this provider before external processing.")
    if revision is not None and value.get("revision") != revision:
        fail(409, "CLOUD_FIRM_POLICY_CHANGED", "The firm cloud policy changed. Request a new job under its current policy.")
    return value
