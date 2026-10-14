"""Extract/install a server artifact and run authenticated smoke on isolated PostgreSQL."""

import argparse
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]

CLI_LOCK_PROBE = '''
import json
import sys
import time
from pathlib import Path
import typer
from casequarry_cli import client

def forbidden(*args, **kwargs):
    raise RuntimeError("Profile-lock verification must not access credentials or HTTP")

client.secure_keyring = forbidden
for name in ("get_keyring", "get_password", "set_password", "delete_password"):
    setattr(client.keyring, name, forbidden)
client.httpx.request = forbidden
client.httpx.Client.request = forbidden
client.config_path = lambda: Path(sys.argv[2]) / "profiles.json"
started = time.monotonic()
try:
    with client.profile_store_lock(timeout=0.2 if sys.argv[1] == "contend" else 1):
        if sys.argv[1] == "owner":
            Path(sys.argv[3]).write_text("locked")
            sys.stdin.buffer.read(1)
        print(json.dumps({"acquired": True}))
except typer.Exit as error:
    print(json.dumps({"blocked": True, "exit_code": error.exit_code, "elapsed_seconds": time.monotonic() - started}))
'''


def verify_cli_profile_lock(python, directory, env):
    """Exercise the installed CLI lock with owned processes and private files."""
    clean_env = {key: value for key, value in env.items() if not key.startswith("CASEQUARRY_") and key not in {"PYTHONPATH", "PYTHONHOME"}}
    results = []
    with tempfile.TemporaryDirectory(prefix="cli-profile-lock-", dir=directory) as temporary:
        profile = Path(temporary)
        command = [str(python), "-I", "-c", CLI_LOCK_PROBE]
        options = {"env": clean_env, "cwd": profile, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "creationflags": subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0}

        def probe(mode):
            result = subprocess.run([*command, mode, str(profile)], timeout=10, **options)
            if result.returncode:
                raise RuntimeError(f"Installed CLI lock probe failed: {result.stdout.decode(errors='replace')} {result.stderr.decode(errors='replace')}")
            return json.loads(result.stdout), result.stderr.decode(errors="replace").strip()

        for exit_mode in ("normal", "terminated"):
            ready = profile / (exit_mode + ".ready")
            owner = subprocess.Popen([*command, "owner", str(profile), str(ready)], stdin=subprocess.PIPE, **options)
            try:
                deadline = time.monotonic() + 10
                while not ready.exists() and owner.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                if not ready.exists():
                    raise RuntimeError("Installed CLI lock owner did not become ready")
                blocked, diagnostic = probe("contend")
                elapsed = blocked.get("elapsed_seconds", 0)
                if not blocked.get("blocked") or blocked.get("exit_code") != 7 or not 0.15 <= elapsed < 3:
                    raise RuntimeError("Installed CLI profile lock did not enforce bounded cross-process exclusion")
                if exit_mode == "normal":
                    output, errors = owner.communicate(input=b"\n", timeout=5)
                    if owner.returncode or errors or json.loads(output) != {"acquired": True}:
                        raise RuntimeError("Installed CLI profile lock owner did not exit cleanly")
                else:
                    owner.terminate()
                    owner.communicate(timeout=5)
                acquired, errors = probe("acquire")
                if acquired != {"acquired": True} or errors:
                    raise RuntimeError("Installed CLI profile lock remained held after its owner exited")
                results.append({"owner_exit": exit_mode, "excluded": True, "bounded_wait_seconds": round(elapsed, 3), "reacquired": True, "contention_diagnostic": diagnostic})
            except Exception as error:
                if owner.poll() is None:
                    owner.kill()
                output, errors = owner.communicate(timeout=5)
                if output or errors:
                    error.add_note(f"Owned CLI lock probe diagnostics: {output.decode(errors='replace')} {errors.decode(errors='replace')}")
                raise
            finally:
                if owner.poll() is None:
                    owner.kill()
                owner.communicate(timeout=5)
    return {"platform": sys.platform, "checks": results, "credential_or_http_access": False}


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def verify(args):
    original_url = os.environ.get(args.database_env)
    if not original_url or make_url(original_url).get_backend_name() != "postgresql":
        raise RuntimeError("Set the named environment variable to the QA PostgreSQL URL; never put credentials in argv.")
    run_id = uuid.uuid4().hex
    schema = "cq_package_" + run_id
    engine = create_engine(original_url)
    report_path = ROOT / ".data/server-validation" / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + run_id[:6]) / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {"synthetic_only": True, "checks": [], "archive": args.archive.name}
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = make_url(original_url).update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(hide_password=False)
    env = {key: value for key, value in os.environ.items() if not key.startswith("CASEQUARRY_")}
    env["CASEQUARRY_PACKAGE_DATABASE_URL"] = scoped
    child = None
    try:
        with ExitStack() as stack:
            temporary = stack.enter_context(tempfile.TemporaryDirectory(prefix="casequarry-server-verify-"))
            directory = Path(temporary).resolve()
            assert directory.is_relative_to(Path(tempfile.gettempdir()).resolve())
            with zipfile.ZipFile(args.archive) as archive:
                for entry in archive.infolist():
                    target = (directory / entry.filename).resolve()
                    if not target.is_relative_to(directory) or entry.filename.startswith(("/", "\\")) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                        raise RuntimeError("Unsafe server archive path")
                archive.extractall(directory)
            manifests = list(directory.glob("*/manifest.json"))
            if len(manifests) != 1:
                raise RuntimeError("Server artifact requires one root manifest")
            package, data = manifests[0].parent, directory / "private"
            manifest = json.loads(manifests[0].read_text())
            report.update({"version": manifest["version"], "platform": manifest["platform"], "packaged_files": len(manifest["files"])})
            controller = package / "server.py"
            def stop_owned():
                if child and child.poll() is None:
                    if (data / "run.json").is_file():
                        subprocess.run([sys.executable, str(controller), "stop", "--data-dir", str(data)], env=env, check=False)
                    try:
                        child.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        if os.name == "nt":
                            subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                        else:
                            child.terminate()
                        child.wait(timeout=10)
            stack.callback(stop_owned)
            subprocess.run([sys.executable, str(controller), "verify"], env=env, check=True)
            subprocess.run([sys.executable, str(controller), "install", "--data-dir", str(data), "--database-env", "CASEQUARRY_PACKAGE_DATABASE_URL", "--loopback-development"], env=env, check=True)
            report["checks"].append("Artifact hashes, isolated runtime install and actual PostgreSQL static migrations")
            installed_python = data / "runtime" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            report["cli_profile_lock"] = verify_cli_profile_lock(installed_python, directory, env)
            report["checks"].append("Installed CLI profile-store OS lock: bounded process exclusion and reacquisition after normal and abrupt owner exit")
            port = free_port()
            with (report_path.parent / "services.log").open("w", encoding="utf8") as log:
                child = subprocess.Popen([sys.executable, str(controller), "start", "--data-dir", str(data), "--web-port", str(port)], env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                web = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        raise RuntimeError("Packaged service exited; inspect private service log")
                    try:
                        if httpx.get(web + "/login", timeout=3).status_code == 200:
                            ready = httpx.get(web + "/api/v1/health", timeout=3)
                            if ready.status_code == 200 and ready.json().get("version") == manifest["version"] and ready.json().get("database_engine") == "postgresql":
                                break
                    except (httpx.RequestError, ValueError):
                        pass
                    time.sleep(.5)
                else:
                    raise RuntimeError("Packaged services did not become ready")
                with httpx.Client(base_url=web + "/api/v1", timeout=20) as owner, httpx.Client(base_url=web + "/api/v1", timeout=20) as second:
                    health = owner.get("/health")
                    assert health.status_code == 200 and health.json()["version"] == manifest["version"] and health.json()["database_engine"] == "postgresql"
                    config = dotenv_values(data / ".env")
                    password = "Synthetic!" + secrets.token_urlsafe(24)
                    setup = owner.post("/setup", json={"token": config["CASEQUARRY_SETUP_TOKEN"], "firm_name": "Synthetic Package Firm", "name": "Synthetic Owner", "email": "package-owner@synthetic.example", "password": password})
                    assert setup.status_code == 201, f"Setup returnedHTTP{setup.status_code}"
                    owner.headers["X-CSRF-Token"] = setup.json()["csrf_token"]
                    created = owner.post("/cases", json={"matter_number": "SYN-PACKAGE", "title": "Synthetic packaged server matter"})
                    assert created.status_code == 201
                    case_id = created.json()["id"]
                    login = second.post("/auth/login", json={"email": "package-owner@synthetic.example", "password": password})
                    assert login.status_code == 200
                    second.headers["X-CSRF-Token"] = login.json()["csrf_token"]
                    shared = second.get(f"/cases/{case_id}")
                    assert shared.status_code == 200 and shared.json()["title"] == "Synthetic packaged server matter"
                    report["checks"].append("Packaged web/API authentication and independent client shared-matter access")
                    before = second.get("/sync", params={"case_id": case_id}).json()["case_revision"]
                    raw = b"Synthetic packaged original. Invoice1097.\n"
                    submitted = owner.post(f"/cases/{case_id}/imports", files={"files": ("synthetic.txt", raw, "text/plain")})
                    assert submitted.status_code == 202
                    batch_id = submitted.json()["batch_id"]
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        status = owner.get(f"/cases/{case_id}/imports/{batch_id}")
                        assert status.status_code == 200
                        if status.json()["state"] in {"completed", "partial", "failed"}:
                            break
                        time.sleep(.5)
                    assert status.json()["state"] == "completed"
                    found = second.post(f"/cases/{case_id}/search", json={"query": "Invoice1097"})
                    assert found.status_code == 200 and found.json()["total_hits"] == 1
                    item = found.json()["items"][0]
                    original = second.get(f"/cases/{case_id}/evidence/{item['id']}/original")
                    assert original.status_code == 200 and original.content == raw
                    assert hashlib.sha256(original.content).hexdigest() == item["sha256"]
                    after = second.get("/sync", params={"case_id": case_id}).json()["case_revision"]
                    assert after > before
                    report["checks"].append("Standalone worker durable import, shared search/original integrity and transactional sync revision")
                subprocess.run([sys.executable, str(controller), "stop", "--data-dir", str(data)], env=env, check=True)
                child.wait(timeout=30)
                assert child.returncode == 0
                child = None
                report["checks"].append("Owned server supervisor clean stop without stopping or dropping PostgreSQL")
            report["status"] = "passed"
    except Exception as error:
        report["status"], report["error"] = "failed", type(error).__name__ + ": " + str(error)
        raise
    finally:
        if child and child.poll() is None:
            child.terminate()
            child.wait(timeout=30)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"status": report["status"], "checks": len(report["checks"]), "report": str(report_path)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--database-env", default="CASEQUARRY_TEST_POSTGRES_URL")
    verify(parser.parse_args())


if __name__ == "__main__":
    main()
