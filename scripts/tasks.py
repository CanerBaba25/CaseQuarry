"""Portable development tasks. Run with `uv run python scripts/tasks.py --help`."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(*command: str) -> None:
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)


def environment() -> dict[str, str]:
    from dotenv import dotenv_values

    return {
        **{key: value for key, value in dotenv_values(ROOT / ".env").items() if value is not None},
        **os.environ,
    }


def initialize() -> None:
    from casequarry_cli.main import init_environment

    created = init_environment(ROOT / ".env")
    print("Generated .env with unique secrets." if created else "Kept existing .env and secrets.")
    print("The first-run setup token is in local .env. Open /setup and enter it; it is never printed here.")


def stop_children(children: list[subprocess.Popen]) -> None:
    for child in children:
        if child.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], check=False)
            else:
                os.killpg(child.pid, signal.SIGTERM)
    for child in children:
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()


def dev() -> None:
    if not (ROOT / ".env").exists():
        initialize()
    env = environment()
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    npm = "npm.cmd" if os.name == "nt" else "npm"
    children = []
    try:
        children.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "casequarry.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                    "--reload",
                    "--no-access-log",
                ],
                cwd=ROOT,
                env=env,
                creationflags=flags,
                start_new_session=os.name != "nt",
            )
        )
        children.append(
            subprocess.Popen(
                [npm, "--prefix", "apps/web", "run", "dev", "--", "--hostname", "127.0.0.1"],
                cwd=ROOT,
                env=env,
                creationflags=flags,
                start_new_session=os.name != "nt",
            )
        )
        print(
            "CaseQuarry web: http://127.0.0.1:3000 | API: http://127.0.0.1:8000 | Ctrl+C stops both.",
            flush=True,
        )
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        failed = next((child.returncode for child in children if child.returncode is not None), 1)
        if failed:
            raise SystemExit(failed)
    except KeyboardInterrupt:
        pass
    finally:
        stop_children(children)


def smoke(server: str, web: str) -> None:
    import httpx

    for label, url in [("API", server.rstrip("/") + "/api/v1/health"), ("web", web.rstrip("/") + "/login")]:
        response = httpx.get(url, timeout=10, follow_redirects=True)
        response.raise_for_status()
        print(f"{label}: HTTP {response.status_code}")
        if label == "API":
            print(json.dumps(response.json()))
    print("Service smoke passed. This does not replace authenticated workflow/security tests.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "task",
        choices=[
            "init",
            "setup",
            "dev",
            "migrate",
            "test",
            "test-unit",
            "test-integration",
            "test-security",
            "lint",
            "format",
            "typecheck",
            "smoke",
            "fixtures",
            "release",
            "notices",
            "benchmark",
            "test-e2e",
        ],
    )
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--web", default="http://127.0.0.1:3000")
    parser.add_argument("--count", type=int, default=10000)
    parser.add_argument("--output", type=Path, default=ROOT / ".data/synthetic")
    args = parser.parse_args()
    os.chdir(ROOT)
    qa_paths = {
        "test": "tests",
        "test-unit": "tests",
        "test-integration": "tests",
        "test-security": "tests",
        "test-e2e": "scripts/browser_e2e.py",
        "fixtures": "scripts/generate_synthetic_emails.py",
        "benchmark": "scripts/benchmark.py",
    }
    if args.task in qa_paths and not (ROOT / qa_paths[args.task]).exists():
        parser.exit(
            7,
            "This command uses local QA assets that are excluded from the public source distribution. Core setup/dev/diagnostics do not require them.\n",
        )
    npm = "npm.cmd" if os.name == "nt" else "npm"
    if args.task == "init":
        initialize()
    elif args.task == "setup":
        if not shutil.which("uv") or not shutil.which(npm):
            parser.error("Install uv and Node.js before setup.")
        initialize()
        run("uv", "sync", "--locked")
        run(npm, "--prefix", "apps/web", "ci")
    elif args.task == "dev":
        dev()
    elif args.task == "migrate":
        run(sys.executable, "-m", "alembic", "upgrade", "head")
    elif args.task == "test-e2e":
        run(sys.executable, "scripts/browser_e2e.py")
    elif args.task.startswith("test"):
        run(sys.executable, "-m", "pytest", "-q", "tests")
    elif args.task == "lint":
        run(
            "ruff",
            "check",
            *(
                path
                for path in ["apps/api", "apps/cli", "scripts", "tests", "migrations"]
                if (ROOT / path).exists()
            ),
        )
    elif args.task == "format":
        run(
            "ruff",
            "format",
            *(
                path
                for path in ["apps/api", "apps/cli", "scripts", "tests", "migrations"]
                if (ROOT / path).exists()
            ),
        )
    elif args.task == "typecheck":
        run(npm, "--prefix", "apps/web", "run", "typecheck")
    elif args.task == "smoke":
        smoke(args.server, args.web)
    elif args.task == "fixtures":
        from scripts.generate_synthetic_emails import generate

        print(json.dumps(generate(args.output, args.count, 42, 100), indent=2))
    elif args.task == "release":
        from scripts.release_source import release

        print(release(ROOT))
    elif args.task == "notices":
        from scripts.dependency_notices import generate_notices

        generate_notices(ROOT)
    elif args.task == "benchmark":
        from scripts.benchmark import run_benchmark

        report = run_benchmark(args.output, args.count)
        ingestion = report["ingestion"]
        summary = {
            key: report[key]
            for key in [
                "run_id",
                "status",
                "dataset",
                "search",
                "integrity",
                "audit",
                "resources",
                "disk_bytes",
                "limitations",
                "mixed_documents",
            ]
        }
        summary["ingestion"] = {
            "seconds": ingestion["seconds"],
            "email_occurrences_per_second": ingestion["email_occurrences_per_second"],
            "batch_states": [
                {"state": batch["state"], "counts": batch.get("counts", {})} for batch in ingestion["batches"]
            ],
            "stats": {key: value for key, value in ingestion["stats"].items() if key != "recent_activity"},
        }
        summary["full_report"] = str(ROOT / ".data" / "benchmarks" / report["run_id"] / "report.json")
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
