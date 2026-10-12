"""Start an isolated synthetic API/web instance and execute the browser workflow."""

from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def main() -> None:
    from scripts.generate_synthetic_emails import generate
    from scripts.tasks import stop_children

    directory = (
        ROOT
        / ".data"
        / "browser-e2e"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3))
    )
    directory.mkdir(parents=True)
    generate(directory / "fixtures", 20, 42, 10)
    api_port, web_port = free_port(), free_port()
    token = secrets.token_urlsafe(48)
    env = {
        **os.environ,
        "CASEQUARRY_ENVIRONMENT": "test",
        "CASEQUARRY_DATABASE_URL": "sqlite:///" + (directory / "test.db").as_posix(),
        "CASEQUARRY_STORAGE_ROOT": str(directory / "private"),
        "CASEQUARRY_SETUP_TOKEN": token,
        "CASEQUARRY_WORKER_MODE": "embedded",
        "CASEQUARRY_AI_ENABLED": "false",
        "CASEQUARRY_ALLOW_REMOTE_AI": "false",
        "CASEQUARRY_API_INTERNAL_URL": f"http://127.0.0.1:{api_port}",
        "CASEQUARRY_NEXT_DIST_DIR": ".next/e2e-" + directory.name,
        "NEXT_TELEMETRY_DISABLED": "1",
        "CASEQUARRY_E2E_WEB": f"http://127.0.0.1:{web_port}",
        "CASEQUARRY_E2E_SETUP_TOKEN": token,
        "CASEQUARRY_E2E_EMAIL": "browser-reviewer@synthetic.example",
        "CASEQUARRY_E2E_PASSWORD": "Synthetic!" + secrets.token_urlsafe(24),
        "CASEQUARRY_E2E_FIXTURES": str(directory / "fixtures"),
        "CASEQUARRY_E2E_ARTIFACTS": str(directory / "artifacts"),
    }
    npm = "npm.cmd" if os.name == "nt" else "npm"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    children = []
    with ExitStack() as stack:
        try:
            for name, command in [
                (
                    "api",
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "casequarry.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(api_port),
                        "--no-access-log",
                    ],
                ),
                (
                    "web",
                    [
                        npm,
                        "--prefix",
                        "apps/web",
                        "run",
                        "dev",
                        "--",
                        "--hostname",
                        "127.0.0.1",
                        "--port",
                        str(web_port),
                    ],
                ),
            ]:
                log = stack.enter_context((directory / f"{name}.log").open("w", encoding="utf-8"))
                children.append(
                    subprocess.Popen(
                        command,
                        cwd=ROOT,
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        creationflags=flags,
                        start_new_session=os.name != "nt",
                    )
                )
            for label, url in [
                ("API", f"http://127.0.0.1:{api_port}/api/v1/health"),
                ("web", f"http://127.0.0.1:{web_port}/login"),
            ]:
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    if any(child.poll() is not None for child in children):
                        raise RuntimeError(
                            "E2E service failed to start; inspect ignored logs under " + str(directory)
                        )
                    try:
                        if httpx.get(url, timeout=5).is_success:
                            break
                    except httpx.RequestError:
                        pass
                    time.sleep(0.5)
                else:
                    raise RuntimeError(label + " did not become ready")
            print(
                "Running real browser workflow with synthetic records only; artifacts under "
                + str(directory),
                flush=True,
            )
            result = subprocess.run(["node", "scripts/browser_smoke.mjs"], cwd=ROOT, env=env, check=False)
            if result.returncode:
                raise SystemExit(result.returncode)
        finally:
            stop_children(children)


if __name__ == "__main__":
    main()
