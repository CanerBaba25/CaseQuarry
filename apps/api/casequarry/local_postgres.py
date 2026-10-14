"""Owner-private PostgreSQL cluster management for native development/server installs."""

import csv
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
from pathlib import Path

import psycopg
from psycopg import sql


def protect(path: Path):
    if os.name != "nt":
        path.chmod(0o700 if path.is_dir() else 0o600)
        return
    system = Path(os.environ["SystemRoot"]) / "System32"
    result = subprocess.run([str(system / "whoami.exe"), "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    sid = list(csv.reader(io.StringIO(result.stdout)))[0][1]
    if not re.fullmatch(r"S-1-[0-9-]+", sid):
        raise RuntimeError("Could not establish the current Windows account identity")
    subprocess.run([str(system / "icacls.exe"), str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F" if path.is_dir() else f"*{sid}:F", "/grant:r", "*S-1-5-18:(OI)(CI)F" if path.is_dir() else "*S-1-5-18:F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, creationflags=subprocess.CREATE_NO_WINDOW)


def binary_directory(explicit: Path | None = None) -> Path:
    candidates = [explicit] if explicit else []
    if shutil.which("pg_ctl"):
        candidates.append(Path(shutil.which("pg_ctl")).parent)
    if os.name == "nt":
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "CaseQuarryTools/postgresql16/pgsql/bin")
        candidates.extend(Path(os.getenv("ProgramFiles", "C:/Program Files")) / f"PostgreSQL/{version}/bin" for version in (16, 17, 18))
    else:
        candidates.extend(Path(f"/usr/lib/postgresql/{version}/bin") for version in (16, 17, 18))
    for candidate in candidates:
        if candidate and all((candidate / (name + (".exe" if os.name == "nt" else ""))).is_file() for name in ("pg_ctl", "initdb", "pg_dump", "pg_restore")):
            return candidate.resolve()
    raise RuntimeError("Install PostgreSQL16 or newer (server/client tools), then provide --postgres-bin or put pg_ctl on PATH. No existing database was changed.")


class LocalPostgres:
    def __init__(self, workspace: Path, binary: Path | None = None, root: Path | None = None):
        self.binary = binary_directory(binary)
        project = hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()[:12]
        base = Path(os.environ["LOCALAPPDATA"]) / "CaseQuarry" if os.name == "nt" else Path.home() / ".local/share/casequarry"
        self.root = (root or base / "postgres" / project).resolve()
        self.data, self.marker = self.root / "data", self.root / "cluster.json"
        self.flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    def tool(self, name):
        return str(self.binary / (name + (".exe" if os.name == "nt" else "")))

    def configuration(self):
        if self.marker.is_symlink() or self.root.is_symlink() or (hasattr(self.root, "is_junction") and self.root.is_junction()):
            raise RuntimeError("Managed PostgreSQL paths must not be links")
        value = json.loads(self.marker.read_text(encoding="utf8"))
        if value.get("format") != 1 or not isinstance(value.get("port"), int) or not 1 <= value["port"] <= 65535:
            raise RuntimeError("Managed PostgreSQL configuration is invalid")
        return value

    def initialize(self, port=5432):
        if not 1 <= port <= 65535:
            raise ValueError("Use a valid PostgreSQL port")
        if self.marker.exists():
            value = self.configuration()
            if value["port"] != port:
                raise RuntimeError("The owned cluster already uses another port; its configuration was preserved")
            return
        if self.data.exists():
            raise RuntimeError("Existing PostgreSQL data has no owner marker; refusing to initialize or replace it")
        self.root.mkdir(parents=True, exist_ok=True)
        protect(self.root)
        password = secrets.token_urlsafe(48)
        pwfile = self.root / "initial-password"
        created_password = False
        try:
            with pwfile.open("x", encoding="ascii") as output:
                created_password = True
                output.write(password + "\n")
            protect(pwfile)
            result = subprocess.run([self.tool("initdb"), "-D", str(self.data), "-U", "cq_local_manager", "--pwfile", str(pwfile), "--auth-host=scram-sha-256", "--auth-local=scram-sha-256", "--encoding=UTF8", "--no-locale", "--data-checksums"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=self.flags, check=False)
            if result.returncode:
                raise RuntimeError("PostgreSQL cluster initialization failed; existing files were preserved")
            self.marker.write_text(json.dumps({"format": 1, "port": port, "manager_password": password}), encoding="utf8")
            protect(self.marker)
        finally:
            if created_password:
                pwfile.unlink(missing_ok=True)

    def running(self):
        return subprocess.run([self.tool("pg_ctl"), "status", "-D", str(self.data)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=self.flags, check=False).returncode == 0

    def set_port(self, port):
        if not isinstance(port, int) or not 1 <= port <= 65535 or self.running():
            raise RuntimeError("Stop the owned server and choose a valid port before changing its binding")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", port))
        value = self.configuration()
        value["port"] = port
        self.marker.write_text(json.dumps(value), encoding="utf8")
        protect(self.marker)

    def start(self):
        configuration = self.configuration()
        if self.running():
            return
        # DEVNULL prevents inherited background handles keeping parent capture pipes open.
        result = subprocess.run([self.tool("pg_ctl"), "start", "-D", str(self.data), "-l", str(self.root / "postgresql.log"), "-o", f"-h 127.0.0.1 -p {configuration['port']}", "-w", "-t", "30"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=self.flags, check=False)
        if result.returncode:
            raise RuntimeError("Owned PostgreSQL server could not start; inspect its private log. Existing data was preserved.")

    def stop(self):
        self.configuration()
        if self.running():
            subprocess.run([self.tool("pg_ctl"), "stop", "-D", str(self.data), "-m", "fast", "-w", "-t", "30"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=self.flags, check=True)

    def provision_database(self, password, database="casequarry", user="casequarry"):
        self.start()
        value = self.configuration()
        with psycopg.connect(host="127.0.0.1", port=value["port"], user="cq_local_manager", password=value["manager_password"], dbname="postgres", autocommit=True, connect_timeout=5) as connection:
            if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (user,)).fetchone():
                connection.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(sql.Identifier(user), sql.Literal(password)))
            if not connection.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone():
                connection.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(database), sql.Identifier(user)))
        # Validate existing credentials; never rotate another role silently.
        with psycopg.connect(host="127.0.0.1", port=value["port"], user=user, password=password, dbname=database, connect_timeout=5) as connection:
            connection.execute("SELECT 1")
        from sqlalchemy.engine import URL

        return URL.create("postgresql+psycopg", username=user, password=password, host="127.0.0.1", port=value["port"], database=database).render_as_string(hide_password=False)

    def status(self):
        value = self.configuration()
        return {"running": self.running(), "host": "127.0.0.1", "port": value["port"], "data_path": str(self.data), "authentication": "scram-sha-256"}
