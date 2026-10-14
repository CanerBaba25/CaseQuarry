"""Authenticated public-API access with safe diagnostics and OS credential storage."""

from __future__ import annotations

import errno
import json
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import keyring
import typer

SERVICE = "CaseQuarry"
SESSION_FORMAT = "casequarry-cli-session-v1"
_ANY_CREDENTIAL = object()


def config_path() -> Path:
    base = Path(os.getenv("APPDATA", Path.home() / ".config"))
    return base / "CaseQuarry" / "profiles.json"


def profiles() -> dict[str, dict[str, str]]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or any(
            not isinstance(name, str)
            or not name
            or not isinstance(profile, dict)
            or not isinstance(profile.get("server"), str)
            or not profile["server"]
            or ("email" in profile and not isinstance(profile["email"], str))
            for name, profile in data.items()
        ):
            raise ValueError("Invalid profile metadata")
        return data
    except (ValueError, OSError):
        fail(
            "CLI profile metadata is unreadable. Repair or remove profiles.json; credentials remain in the OS keyring.",
            2,
        )


def fail(message: str, code: int) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(code)


def validate_server(server: str) -> str:
    if not isinstance(server, str):
        fail("--server must be a valid HTTP(S) origin.", 2)
    value = server.strip()
    try:
        if not value or any(char.isspace() or ord(char) < 32 or ord(char) == 127 or char == "\\" for char in value):
            raise ValueError("Invalid URL characters")
        parsed = urlsplit(value)
        if parsed.port == 0:
            raise ValueError("Invalid server port")
        origin = httpx.URL(value)
        if (parsed.scheme, parsed.port) in {("https", 443), ("http", 80)}:
            origin = origin.copy_with(port=None)
        normalized = str(origin).rstrip("/")
    except (ValueError, httpx.InvalidURL):
        fail("--server must be a valid HTTP(S) origin with a valid port.", 2)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        fail("--server must be an HTTP(S) URL without embedded credentials.", 2)
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        fail("Use HTTPS for a server outside the local machine.", 2)
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        fail("--server must be the server origin, without a path, query or fragment.", 2)
    return normalized


def secure_keyring() -> None:
    backend = keyring.get_keyring()
    module = type(backend).__module__
    if "keyrings.alt" in module or ".fail" in module or ".null" in module or backend.priority <= 0:
        fail(
            "A secure OS keyring is unavailable. Configure Windows Credential Manager, macOS Keychain or Linux Secret Service; no plaintext credential fallback is used.",
            7,
        )


def write_profiles(data: dict[str, dict[str, str]]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".profiles-", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def profile_store_lock(timeout: float = 5.0):
    """Serialize metadata/keyring updates; the OS releases this lock on exit."""
    path = config_path().parent / ".profiles.lock"
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        fail("Cannot open the CLI profile-store lock. Check access to the profile directory.", 7)
    with os.fdopen(descriptor, "r+b", buffering=0) as stream:
        if os.name == "nt":
            import msvcrt

            def acquire():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)

            def release():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire():
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release():
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

        deadline = time.monotonic() + timeout
        while True:
            try:
                acquire()
                break
            except OSError as error:
                if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    fail("Cannot acquire the CLI profile-store lock. Check profile-directory access.", 7)
                if time.monotonic() >= deadline:
                    fail("The CLI profile store is busy. Retry after the other sign-in or sign-out finishes.", 7)
                time.sleep(0.05)
        try:
            yield
        finally:
            release()


def save_login(profile: str, server: str, email: str, token: str) -> None:
    server = validate_server(server)
    if not profile or not isinstance(email, str) or not isinstance(token, str) or not token:
        fail("The API did not return a valid session for this profile.", 7)
    secure_keyring()
    try:
        # Keep the origin/account with the secret: failed or concurrent metadata
        # publication must never cause that secret to be used for another origin.
        with profile_store_lock():
            data = profiles()
            credential = json.dumps({"format": SESSION_FORMAT, "server": server, "email": email, "token": token})
            keyring.set_password(SERVICE, profile, credential)
            data[profile] = {"server": server, "email": email}
            write_profiles(data)
    except typer.Exit:
        raise
    except Exception:
        fail("Could not save the session to the OS keyring. Check the credential-store configuration.", 7)


def logout(profile: str, *, expected_credential: object = _ANY_CREDENTIAL) -> bool:
    secure_keyring()
    try:
        with profile_store_lock():
            current = keyring.get_password(SERVICE, profile)
            if current and expected_credential is not _ANY_CREDENTIAL and current != expected_credential:
                return False
            if current:
                keyring.delete_password(SERVICE, profile)
            return True
    except typer.Exit:
        raise
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
        try:
            credential = json.loads(token)
        except (ValueError, TypeError):
            fail("This saved CLI session needs a fresh sign-in. Run casequarry auth login.", 3)
        if (
            not isinstance(credential, dict)
            or credential.get("format") != SESSION_FORMAT
            or not isinstance(credential.get("token"), str)
            or not credential["token"]
        ):
            fail("The saved CLI session is invalid. Run casequarry auth login.", 3)
        if credential.get("server") != self.server or credential.get("email") != stored.get("email"):
            fail("This saved CLI session belongs to another server or account. Run casequarry auth login.", 3)
        return credential["token"]

    def logout(self) -> bool:
        """Revoke the captured session without deleting a later local sign-in."""
        captured: object = _ANY_CREDENTIAL
        try:
            secure_keyring()
            with profile_store_lock():
                try:
                    captured = keyring.get_password(SERVICE, self.options.profile)
                except Exception:
                    fail("Could not read the session from the OS keyring.", 7)
                token = self.token()
            self.request("POST", "/auth/logout", auth=False, headers={"Authorization": "Bearer " + token})
        finally:
            if captured is not _ANY_CREDENTIAL:
                cleared = logout(self.options.profile, expected_credential=captured)
        return cleared

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
