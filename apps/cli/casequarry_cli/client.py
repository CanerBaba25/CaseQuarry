"""Authenticated public-API access with safe diagnostics and OS credential storage."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import keyring
import typer

SERVICE = "CaseQuarry"


def config_path() -> Path:
    base = Path(os.getenv("APPDATA", Path.home() / ".config"))
    return base / "CaseQuarry" / "profiles.json"


def profiles() -> dict[str, dict[str, str]]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        fail(
            "CLI profile metadata is unreadable. Repair or remove profiles.json; credentials remain in the OS keyring.",
            2,
        )


def fail(message: str, code: int) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(code)


def validate_server(server: str) -> str:
    value = server.rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        fail("--server must be an HTTP(S) URL without embedded credentials.", 2)
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        fail("Use HTTPS for a server outside the local machine.", 2)
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        fail("--server must be the server origin, without a path, query or fragment.", 2)
    return value


def secure_keyring() -> None:
    backend = keyring.get_keyring()
    module = type(backend).__module__
    if "keyrings.alt" in module or ".fail" in module or ".null" in module or backend.priority <= 0:
        fail(
            "A secure OS keyring is unavailable. Configure Windows Credential Manager, macOS Keychain or Linux Secret Service; no plaintext credential fallback is used.",
            7,
        )


def save_login(profile: str, server: str, email: str, token: str) -> None:
    secure_keyring()
    try:
        keyring.set_password(SERVICE, profile, token)
        data = profiles()
        data[profile] = {"server": validate_server(server), "email": email}
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except typer.Exit:
        raise
    except Exception:
        fail("Could not save the session to the OS keyring. Check the credential-store configuration.", 7)


def logout(profile: str) -> None:
    secure_keyring()
    try:
        if keyring.get_password(SERVICE, profile):
            keyring.delete_password(SERVICE, profile)
    except Exception:
        fail("Could not clear the session from the OS keyring.", 7)


@dataclass
class Options:
    server: str | None = None
    case_id: str | None = None
    profile: str = "default"
    output: str = "table"
    limit: int = 50
    cursor: str | None = None
    dry_run: bool = False
    reason: str | None = None
    yes: bool = False


class API:
    def __init__(self, options: Options, server: str | None = None):
        self.options = options
        self.server = validate_server(
            server
            or options.server
            or profiles().get(options.profile, {}).get("server", "http://127.0.0.1:8000")
        )

    def token(self) -> str:
        token = os.getenv("CASEQUARRY_TOKEN")
        if token:
            return token
        stored = profiles().get(self.options.profile)
        if not stored or validate_server(stored.get("server", "")) != self.server:
            fail(
                "This profile is not signed in to the selected server. Run auth login for that server; an existing session is never sent to a different origin.",
                3,
            )
        secure_keyring()
        try:
            token = keyring.get_password(SERVICE, self.options.profile)
        except Exception:
            fail("Could not read the session from the OS keyring.", 7)
        if not token:
            fail("Not signed in. Run casequarry auth login.", 3)
        return token

    def request(self, method: str, route: str, *, auth: bool = True, raw: bool = False, **kwargs: Any) -> Any:
        if not route.startswith("/") or "\\" in route or ".." in route.split("/") or "#" in route:
            fail("Invalid API resource path.", 2)
        query_only = route.endswith(("/search", "/search/facets", "/search/explain"))
        if self.options.dry_run and method.upper() not in {"GET", "HEAD", "OPTIONS"} and not query_only:
            return {
                "dry_run": True,
                "method": method.upper(),
                "resource": route,
                "notice": "No request was sent; server authorization and validation will run on execution.",
            }
        headers = dict(kwargs.pop("headers", {}))
        if auth:
            headers["Authorization"] = "Bearer " + self.token()
        try:
            response = httpx.request(
                method,
                self.server + "/api/v1" + route,
                headers=headers,
                timeout=120,
                follow_redirects=False,
                **kwargs,
            )
        except httpx.RequestError:
            fail("Cannot reach the configured API. Check the server URL, TLS and service status.", 7)
        if not response.is_success:
            codes = {401: 3, 403: 3, 404: 4, 409: 5, 413: 2, 422: 2, 429: 7, 503: 7}
            try:
                payload = response.json()
                detail = payload.get("error", payload.get("detail", payload))
                message = (
                    detail.get("message", detail.get("detail", "Request failed"))
                    if isinstance(detail, dict)
                    else detail
                )
                code = (
                    detail.get("error_code", payload.get("error_code", "request_failed"))
                    if isinstance(detail, dict)
                    else payload.get("error_code", "request_failed")
                )
                if not isinstance(message, str):
                    message = "Request validation failed; check command arguments."
                fail(
                    f"{code} (HTTP {response.status_code}): {message}",
                    8 if "integrity" in str(code) else codes.get(response.status_code, 7),
                )
            except (ValueError, TypeError, AttributeError):
                fail(
                    f"API returned HTTP {response.status_code}. Check service status and command arguments.",
                    codes.get(response.status_code, 7),
                )
        if raw:
            return response
        if response.status_code == 204:
            return {"state": "completed"}
        try:
            return response.json()
        except ValueError:
            fail("API returned an unexpected non-JSON response.", 7)

    def case_route(self, case_id: str | None, suffix: str = "") -> str:
        value = case_id or self.options.case_id
        if not value:
            fail("--case CASE_ID is required for this command.", 2)
        if "/" in value or "?" in value or "#" in value:
            fail("Invalid case identifier.", 2)
        return f"/cases/{value}{suffix}"
