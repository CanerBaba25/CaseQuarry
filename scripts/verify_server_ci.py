"""Verify a release server ZIP using a disposable PostgreSQL cluster on Windows."""

import argparse
import os
import secrets
import socket
import sys
import tempfile
import traceback
from pathlib import Path

from sqlalchemy.engine import make_url
from verify_server import verify


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def run(args, private_values):
    if os.name != "nt":
        verify(args)
        return

    from casequarry.local_postgres import LocalPostgres

    configured = args.postgres_bin or (Path(os.environ["PGBIN"]) if os.environ.get("PGBIN") else None)
    original = os.environ.get(args.database_env)
    with tempfile.TemporaryDirectory(prefix="casequarry-server-ci-") as temporary:
        owned = Path(temporary).resolve()
        temporary_parent = Path(tempfile.gettempdir()).resolve()
        if not owned.is_relative_to(temporary_parent):
            raise RuntimeError("The generated QA cluster must remain inside the temporary directory.")
        manager = LocalPostgres(Path.cwd(), binary=configured, root=owned / "postgres")
        if manager.root != owned / "postgres" or manager.root.is_symlink():
            raise RuntimeError("The QA cluster location is invalid.")
        initialized = False
        try:
            manager.initialize(free_port())
            initialized = True
            private_values.append(manager.configuration()["manager_password"])
            password = secrets.token_urlsafe(48)
            private_values.append(password)
            database_url = manager.provision_database(
                password, database="casequarry_ci", user="casequarry_ci"
            )
            private_values.append(database_url)
            os.environ[args.database_env] = database_url
            print("Verifying the server artifact against an isolated loopback PostgreSQL cluster.")
            verify(args)
        finally:
            try:
                if initialized:
                    manager.stop()
            finally:
                if original is None:
                    os.environ.pop(args.database_env, None)
                else:
                    os.environ[args.database_env] = original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--database-env", default="CASEQUARRY_TEST_POSTGRES_URL")
    parser.add_argument(
        "--postgres-bin",
        type=Path,
        help="Optional PostgreSQL binary directory; otherwise PGBIN or installed tools are discovered.",
    )
    args = parser.parse_args()
    if not args.archive.is_file():
        parser.error("The server ZIP does not exist.")
    private_values = []
    try:
        supplied = os.environ.get(args.database_env)
        if supplied:
            private_values.append(supplied)
            password = make_url(supplied).password
            if password:
                private_values.append(password)
        run(args, private_values)
    except Exception:
        diagnostic = traceback.format_exc()
        for value in sorted(set(private_values), key=len, reverse=True):
            diagnostic = diagnostic.replace(value, "[redacted QA database credential]")
        sys.stderr.write(diagnostic)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
