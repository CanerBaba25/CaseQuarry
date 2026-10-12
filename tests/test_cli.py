import hashlib
import json

import httpx
import pytest
from casequarry_cli.client import API, Options, validate_server
from casequarry_cli.main import app, init_environment
from typer.testing import CliRunner

from scripts.release_source import allowed

runner = CliRunner()


def test_version_and_real_command_help():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output
    result = runner.invoke(app, ["search", "--help"])
    assert result.exit_code == 0
    assert "--group-by" in result.output


@pytest.mark.parametrize(
    ("status", "exit_code"), [(401, 3), (403, 3), (404, 4), (409, 5), (422, 2), (503, 7)]
)
def test_http_failures_preserve_safe_diagnostic_and_exit(monkeypatch, status, exit_code):
    monkeypatch.setenv("CASEQUARRY_TOKEN", "private-session")
    monkeypatch.setattr(
        httpx,
        "request",
        lambda *args, **kwargs: httpx.Response(
            status, json={"error_code": "test_error", "detail": "Safe diagnostic"}
        ),
    )
    result = runner.invoke(app, ["auth", "whoami"])
    assert result.exit_code == exit_code
    assert "Safe diagnostic" in result.output
    assert "private-session" not in result.output


def test_login_never_prints_or_writes_token_to_profile(monkeypatch, tmp_path):
    from casequarry_cli import client

    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(client, "secure_keyring", lambda: None)
    saved = {}
    monkeypatch.setattr(
        client.keyring, "set_password", lambda service, profile, value: saved.update(token=value)
    )
    monkeypatch.setattr(
        httpx,
        "request",
        lambda *args, **kwargs: httpx.Response(
            200, json={"access_token": "hidden-bearer-secret", "token_type": "bearer"}
        ),
    )
    result = runner.invoke(
        app,
        ["auth", "login", "--email", "synthetic@example.org", "--password-stdin"],
        input="hidden-password\n",
    )
    assert result.exit_code == 0, result.output
    assert saved["token"] == "hidden-bearer-secret"
    assert "hidden-bearer-secret" not in result.output
    assert "hidden-password" not in result.output
    content = client.config_path().read_text()
    assert "hidden-bearer-secret" not in content
    assert json.loads(content)["default"]["email"] == "synthetic@example.org"


def test_plaintext_keyring_is_refused(monkeypatch):
    from casequarry_cli import client

    class Backend:
        priority = 1

    Backend.__module__ = "keyrings.alt.file"
    monkeypatch.delenv("CASEQUARRY_TOKEN", raising=False)
    monkeypatch.setattr(client, "profiles", lambda: {"default": {"server": "http://127.0.0.1:8000"}})
    monkeypatch.setattr(client.keyring, "get_keyring", lambda: Backend())
    with pytest.raises(Exception) as error:
        API(Options()).token()
    assert error.value.exit_code == 7


def test_session_is_never_reused_at_another_origin(monkeypatch):
    from casequarry_cli import client

    monkeypatch.delenv("CASEQUARRY_TOKEN", raising=False)
    monkeypatch.setattr(client, "profiles", lambda: {"default": {"server": "https://trusted.example"}})
    monkeypatch.setattr(
        client.keyring,
        "get_password",
        lambda *_: pytest.fail("Must not read credentials for a different origin"),
    )
    with pytest.raises(Exception) as error:
        API(Options(server="https://unrelated.example")).token()
    assert error.value.exit_code == 3


def test_server_requires_secure_origin():
    assert validate_server("http://127.0.0.1:8000/") == "http://127.0.0.1:8000"
    for value in [
        "http://remote.example",
        "https://user:secret@example.org",
        "https://example.org/api",
        "file:///tmp/evidence",
    ]:
        with pytest.raises(Exception) as error:
            validate_server(value)
        assert error.value.exit_code == 2


def test_init_never_overwrites_existing_secrets(tmp_path):
    path = tmp_path / ".env"
    assert init_environment(path)
    first = path.read_text()
    assert "CASEQUARRY_SETUP_TOKEN=" in first
    assert init_environment(path) is False
    assert path.read_text() == first


def test_source_release_excludes_private_artifacts():
    for path in [
        "graphify-out/graph.json",
        "AGENTS.md",
        ".env",
        ".env.local",
        "docs/RTK.md",
        "apps/web/node_modules/example/index.js",
        "IMPLEMENTATION_STATUS.md",
        ".data/original.eml",
        "CaseQuarry_CODEX_MASTER_SPEC.md",
    ]:
        assert not allowed(path), path
    for path in [".env.example", "apps/api/casequarry/main.py", "RELEASE_NOTES.md", "tests/test_cli.py"]:
        assert allowed(path), path


def test_dry_run_never_sends_a_mutation_or_creates_fixture_files(monkeypatch, tmp_path):
    monkeypatch.setattr(
        httpx, "request", lambda *args, **kwargs: pytest.fail("Dry run must not send mutation")
    )
    archived = runner.invoke(
        app, ["--dry-run", "--output", "json", "case", "archive", "SYN-CASE", "--reason", "Synthetic preview"]
    )
    assert archived.exit_code == 0, archived.output
    assert json.loads(archived.output)["dry_run"] is True
    path = tmp_path / "synthetic"
    generated = runner.invoke(app, ["--dry-run", "benchmark", "generate", "--output", str(path)])
    assert generated.exit_code == 0, generated.output
    assert not path.exists()


@pytest.mark.parametrize("tampered", [False, True])
def test_metadata_export_saves_manifest_and_refuses_bad_package_hash(monkeypatch, tmp_path, tampered):
    monkeypatch.setenv("CASEQUARRY_TOKEN", "private-session")
    metadata = b"evidence_id,sha256\nSYN-1,synthetic-hash\n"
    manifest = b'{"items":[{"evidence_id":"SYN-1","sha256":"synthetic-hash"}]}'

    def request(method, url, **kwargs):
        if method == "POST":
            assert kwargs["json"]["confirmed"] is True
            return httpx.Response(
                200,
                json={
                    "id": "SYN-EXPORT",
                    "state": "completed",
                    "sha256": hashlib.sha256(metadata).hexdigest(),
                    "download_url": "/api/v1/cases/SYN/exports/SYN-EXPORT/download",
                    "manifest_url": "/api/v1/cases/SYN/exports/SYN-EXPORT/manifest",
                },
            )
        if url.endswith("/manifest"):
            return httpx.Response(200, content=manifest)
        return httpx.Response(200, content=b"corrupted" if tampered else metadata)

    monkeypatch.setattr(httpx, "request", request)
    destination = tmp_path / "metadata.csv"
    result = runner.invoke(
        app,
        [
            "export",
            "csv",
            "--case",
            "SYN",
            "--path",
            str(destination),
            "--reason",
            "Synthetic export",
            "--yes",
        ],
    )
    assert result.exit_code == (8 if tampered else 0), result.output
    if tampered:
        assert not destination.exists()
    else:
        assert destination.read_bytes() == metadata
        assert destination.with_suffix(".csv.manifest.json").read_bytes() == manifest
    assert "private-session" not in result.output
