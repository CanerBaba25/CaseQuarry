"""Install and supervise the packaged central CaseQuarry server."""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
import venv
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent


def default_data():
    return Path(os.environ["LOCALAPPDATA"]) / "CaseQuarryServer" if os.name == "nt" else Path.home() / ".local/share/casequarry-server"


def interpreter(data):
    return data / "runtime" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def command(arguments, *, env=None, cwd=None):
    result = subprocess.run([str(value) for value in arguments], env=env, cwd=cwd or PACKAGE, check=False)
    if result.returncode:
        raise RuntimeError(f"Server operation failed with exit code {result.returncode}; configuration and data were preserved.")


def verify():
    manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf8"))
    for name, expected in manifest["files"].items():
        target = (PACKAGE / name).resolve()
        if not target.is_relative_to(PACKAGE) or target.is_symlink() or not target.is_file():
            raise RuntimeError("Invalid or missing packaged file: " + name)
        with target.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != expected:
                raise RuntimeError("Packaged integrity check failed: " + name)
    return manifest


def install(args):
    manifest = verify()
    expected = "windows-x64" if os.name == "nt" else "linux-x64"
    if manifest["platform"] != expected or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("Install the server artifact matching this operating system and x64 architecture.")
    data = args.data_dir.resolve()
    data.mkdir(parents=True, exist_ok=True)
    if (data / "run.json").exists():
        raise RuntimeError("Stop the installed server before upgrading its runtime.")
    python = interpreter(data)
    uv = shutil.which("uv")
    if not python.exists():
        if uv:
            command([uv, "venv", "--python", "3.12", data / "runtime"])
        elif sys.version_info[:2] == (3, 12):
            venv.EnvBuilder(with_pip=True).create(data / "runtime")
        else:
            raise RuntimeError("Install uv or run this installer with Python3.12. Node20.9+ and PostgreSQL tools are also required.")
    if uv:
        command([uv, "pip", "sync", "--python", python, PACKAGE / "requirements.txt"])
        command([uv, "pip", "install", "--python", python, "--no-deps", *sorted((PACKAGE / "wheels").glob("casequarry-*.whl"))])
    else:
        command([python, "-m", "pip", "install", "--require-hashes", "-r", PACKAGE / "requirements.txt"])
        command([python, "-m", "pip", "install", "--no-deps", *sorted((PACKAGE / "wheels").glob("casequarry-*.whl"))])
    arguments = [python, PACKAGE / "server.py", "configure", "--data-dir", data]
    if args.postgres_bin:
        arguments += ["--postgres-bin", args.postgres_bin]
    if args.postgres_port:
        arguments += ["--postgres-port", str(args.postgres_port)]
    if args.loopback_development:
        arguments += ["--loopback-development"]
    if args.database_env:
        arguments += ["--database-env", args.database_env]
    command(arguments)
    print("Server installed. Private configuration is in the data directory; setup token and provider master key are never printed.")


def configure(args):
    from casequarry.config import Settings
    from casequarry.database import Database
    from casequarry.local_postgres import LocalPostgres, protect
    from casequarry_cli.main import init_environment
    from dotenv import dotenv_values
    from sqlalchemy.engine import make_url

    data = args.data_dir.resolve()
    data.mkdir(parents=True, exist_ok=True)
    protect(data)
    config = data / ".env"
    created = init_environment(config)
    if created:
        values = dotenv_values(config)
        port = args.postgres_port or (55432 if os.name == "nt" else 5432)
        if not args.postgres_port:
            with socket.socket() as listener:
                try:
                    listener.bind(("127.0.0.1", port))
                except OSError:
                    listener.bind(("127.0.0.1", 0))
                    port = listener.getsockname()[1]
        if args.database_env:
            url = os.environ.get(args.database_env)
            if not url:
                raise RuntimeError("The selected PostgreSQL environment variable is not set; credentials must not be passed on the command line.")
        else:
            cluster = LocalPostgres(data, args.postgres_bin, data / "postgres")
            cluster.initialize(port)
            url = cluster.provision_database(values["POSTGRES_PASSWORD"])
        changes = {"CASEQUARRY_DATABASE_URL": url, "CASEQUARRY_STORAGE_ROOT": str(data / "storage"), "CASEQUARRY_WORKER_MODE": "external", "CASEQUARRY_ENVIRONMENT": "development" if args.loopback_development else "production", "CASEQUARRY_ALLOW_INSECURE_LOCAL_COOKIES": "true" if args.loopback_development else "false"}
        original = config.read_text(encoding="utf8")
        lines = [line for line in original.splitlines() if line.split("=", 1)[0] not in changes]
        config.write_text("\n".join(lines + [key + "=" + value for key, value in changes.items()]) + "\n", encoding="utf8")
        protect(config)
    settings = Settings(_env_file=config)
    if make_url(settings.database_url).get_backend_name() != "postgresql":
        raise RuntimeError("Server installations require PostgreSQL. Preserve and explicitly migrate an existing SQLite installation before cutover.")
    database = Database(settings)
    try:
        database.migrate()
    finally:
        database.dispose()
    print("PostgreSQL schema is current; existing configuration and evidence are preserved.")


def stop_children(children):
    for child in children:
        if child.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            else:
                os.killpg(child.pid, signal.SIGTERM)
    for child in children:
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()


def serve(args):
    from casequarry.config import Settings
    from casequarry.database import Database
    from casequarry.local_postgres import LocalPostgres, protect
    from dotenv import dotenv_values

    manifest = verify()
    data = args.data_dir.resolve()
    config = data / ".env"
    if not config.is_file():
        raise RuntimeError("Install/configure the server before starting it.")
    if (data / "run.json").exists():
        raise RuntimeError("An existing supervisor marker must be stopped or reviewed before starting another server.")
    if (data / "postgres/cluster.json").exists():
        LocalPostgres(data, args.postgres_bin, data / "postgres").start()
    settings = Settings(_env_file=config)
    database = Database(settings)
    try:
        database.require_current_schema()
    finally:
        database.dispose()
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Install Node20.9+ before starting the packaged web server.")
    environment = {**os.environ, **{key: value for key, value in dotenv_values(config).items() if value is not None}, "PORT": str(args.web_port), "HOSTNAME": "127.0.0.1", "NEXT_TELEMETRY_DISABLED": "1"}
    logs, children = [], []
    marker = data / "run.json"
    run_id = uuid.uuid4().hex
    stop_marker = data / ("stop-" + run_id)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        commands = [("api", [sys.executable, "-m", "uvicorn", "casequarry.main:app", "--host", "127.0.0.1", "--port", "8000", "--no-access-log", "--no-proxy-headers"]), ("worker", [sys.executable, "-m", "casequarry.worker"]), ("web", [node, PACKAGE / manifest["web_entry"]])]
        for name, arguments in commands:
            log = (data / f"{name}.log").open("a", encoding="utf8")
            logs.append(log)
            children.append(subprocess.Popen([str(value) for value in arguments], cwd=data, env=environment, stdout=log, stderr=subprocess.STDOUT, creationflags=flags, start_new_session=os.name != "nt"))
        marker.write_text(json.dumps({"run_id": run_id, "supervisor_pid": os.getpid(), "web_port": args.web_port}), encoding="utf8")
        protect(marker)
        for url in ["http://127.0.0.1:8000/api/v1/health", f"http://127.0.0.1:{args.web_port}/login"]:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("A server component stopped; inspect private data-directory logs.")
                try:
                    if urllib.request.urlopen(url, timeout=3).status == 200:
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(.5)
            else:
                raise RuntimeError("A server component did not become ready.")
        print(f"Server ready on loopback http://127.0.0.1:{args.web_port}. Use the HTTPS proxy for other computers. Ctrl+C or the stop command stops application services; PostgreSQL remains persistent.", flush=True)
        while not stop_marker.exists():
            if any(child.poll() is not None for child in children):
                raise RuntimeError("A server component stopped; inspect private logs.")
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_children(children)
        for log in logs:
            log.close()
        marker.unlink(missing_ok=True)
        stop_marker.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["verify", "install", "configure", "start", "stop", "status"])
    parser.add_argument("--data-dir", type=Path, default=default_data())
    parser.add_argument("--postgres-bin", type=Path)
    parser.add_argument("--postgres-port", type=int)
    parser.add_argument("--web-port", type=int, default=3000)
    parser.add_argument("--loopback-development", action="store_true")
    parser.add_argument("--database-env", help="Name of an environment variable containing an existing PostgreSQL URL; never pass credentials in argv.")
    args = parser.parse_args()
    try:
        if args.action == "verify":
            value = verify()
            print(json.dumps({"version": value["version"], "platform": value["platform"], "files_verified": len(value["files"])}))
        elif args.action == "install":
            install(args)
        elif args.action == "configure":
            configure(args)
        elif args.action == "start":
            python = interpreter(args.data_dir.resolve())
            if Path(sys.executable).resolve() != python.resolve():
                command([python, PACKAGE / "server.py", "start", "--data-dir", args.data_dir, "--web-port", str(args.web_port), *(["--postgres-bin", args.postgres_bin] if args.postgres_bin else [])])
            else:
                serve(args)
        elif args.action == "stop":
            value = json.loads((args.data_dir / "run.json").read_text())
            if not isinstance(value.get("run_id"), str) or not re.fullmatch("[a-f0-9]{32}", value["run_id"]):
                raise RuntimeError("Invalid server supervisor marker")
            (args.data_dir / ("stop-" + value["run_id"])).touch()
            print("Requested stop of the owned application supervisor; database data is retained.")
        else:
            print(json.dumps({"configured": (args.data_dir / ".env").exists(), "supervisor_marker": (args.data_dir / "run.json").exists()}))
    except (RuntimeError, OSError) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    main()
