import getpass
import hashlib
import json
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Annotated

import typer

from .acquisition import Mailbox, folder_inventory, safe_failure, upload_folder
from .client import API, fail

app = typer.Typer(help="Explicit, read-only local-folder, Maildir and IMAPS acquisition.")


def show_result(value, options):
    from .main import show
    show(value, options)


@app.command("folder-inventory")
def folder_plan(ctx: typer.Context, path: Annotated[Path, typer.Option()], recursive: bool = False, maildir: bool = False, maximum: Annotated[int, typer.Option(min=1, max=2000)] = 2000):
    try:
        rows = folder_inventory(path, recursive, maildir, maximum)
        show_result({"items": [{key: value for key, value in row.items() if key != "path"} for row in rows], "file_count": len(rows), "read_only": True, "bytes": sum(row["byte_size"] for row in rows)}, ctx.obj)
    except Exception as error:
        safe_failure(error)


@app.command("folder-import")
def folder_import(ctx: typer.Context, path: Annotated[Path, typer.Option()], case: str | None = None, recursive: bool = False, maildir: bool = False, source_label: Annotated[str, typer.Option()] = "Explicit folder acquisition", custodian: str = "", maximum: Annotated[int, typer.Option(min=1, max=2000)] = 2000):
    try:
        rows = folder_inventory(path, recursive, maildir, maximum)
        show_result(upload_folder(ctx.obj, rows, case, source_label, custodian, maildir), ctx.obj)
    except Exception as error:
        safe_failure(error)


def password(stdin):
    value = sys.stdin.readline().rstrip("\r\n") if stdin else getpass.getpass("Mailbox password (not saved): ")
    if not value:
        fail("A mailbox password is required; it is never stored by this connector.", 2)
    return value


@app.command("imap-inventory")
def imap_inventory(ctx: typer.Context, host: Annotated[str, typer.Option()], username: Annotated[str, typer.Option()], mailbox: Annotated[str, typer.Option()], after_uid: Annotated[int, typer.Option(min=0)] = 0, maximum: Annotated[int, typer.Option(min=1, max=200)] = 50, port: Annotated[int, typer.Option(min=1, max=65535)] = 993, ca_file: Path | None = None, password_stdin: bool = False):
    if ctx.obj.dry_run:
        show_result({"dry_run": True, "host": host, "mailbox": mailbox, "after_uid": after_uid, "maximum": maximum, "read_only": True, "notice": "No connection or credential prompt was made."}, ctx.obj)
        return
    connection = None
    try:
        connection = Mailbox(host, username, password(password_stdin), mailbox, port, ca_file)
        show_result(connection.inventory(after_uid, maximum), ctx.obj)
    except Exception as error:
        safe_failure(error)
    finally:
        if connection:
            connection.close()


@app.command("imap-fetch")
def imap_fetch(ctx: typer.Context, host: Annotated[str, typer.Option()], username: Annotated[str, typer.Option()], mailbox: Annotated[str, typer.Option()], uid: Annotated[list[int], typer.Option(min=1)], uidvalidity: Annotated[str, typer.Option()], path: Annotated[Path, typer.Option()], authorized: Annotated[bool, typer.Option("--authorized")] = False, port: Annotated[int, typer.Option(min=1, max=65535)] = 993, ca_file: Path | None = None, password_stdin: bool = False, max_message_bytes: Annotated[int, typer.Option(min=1, max=64 * 1024 * 1024)] = 16 * 1024 * 1024):
    selected = sorted(set(uid))
    if len(selected) > 200 or not uidvalidity.isdigit():
        fail("Select at most 200 explicit UIDs and the UIDVALIDITY from inventory.", 2)
    if ctx.obj.dry_run:
        show_result({"dry_run": True, "host": host, "mailbox": mailbox, "uids": selected, "uidvalidity": uidvalidity, "read_only": True, "notice": "No mailbox connection or local writes were made."}, ctx.obj)
        return
    if not authorized:
        fail("Use --authorized after reviewing the explicit mailbox and UID scope you are permitted to collect.", 2)
    connection = None
    try:
        connection = Mailbox(host, username, password(password_stdin), mailbox, port, ca_file, max_message_bytes)
        show_result(connection.fetch(selected, path, uidvalidity), ctx.obj)
    except Exception as error:
        safe_failure(error)
    finally:
        if connection:
            connection.close()


@app.command("adapters")
def adapters(ctx: typer.Context, case: str | None = None):
    api = API(ctx.obj)
    show_result(api.request("GET", api.case_route(case, "/imports/adapters")), ctx.obj)


@app.command("imap-import")
def imap_import(ctx: typer.Context, path: Annotated[Path, typer.Option()], source_label: Annotated[str, typer.Option()], case: str | None = None):
    """Import an exact local acquisition manifest through the authenticated API."""
    try:
        if path.is_symlink() or path.stat().st_size > 1_048_576:
            fail("Choose a bounded, regular acquisition manifest.", 2)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            fail("The acquisition manifest must be a JSON object.", 2)
        rows = manifest.get("items", [])
        if manifest.get("format") != "casequarry-imap-acquisition-v1" or manifest.get("state") != "completed" or not 1 <= len(rows) <= 200:
            fail("Use a completed IMAP acquisition manifest containing 1 to 200 exact originals.", 2)
        total = 0
        for row in rows:
            expected = f"uid-{int(row['uid'])}.eml"
            item = path.parent / expected
            if row["filename"] != expected or item.is_symlink():
                fail("Acquisition manifest filenames are invalid.", 8)
            total += item.stat().st_size
            if total > 64 * 1024 * 1024:
                fail("Acquisition originals exceed the 64 MiB scope limit.", 2)
            with item.open("rb") as stream:
                raw = stream.read(64 * 1024 * 1024 + 1)
            if len(raw) != row["byte_size"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
                fail("An acquired original failed manifest size/hash verification.", 8)
        if ctx.obj.dry_run:
            show_result({"dry_run": True, "file_count": len(rows), "byte_size": total, "source_label": source_label}, ctx.obj)
            return
        api = API(ctx.obj)
        source = api.request("POST", api.case_route(case, "/sources"), json={"label": source_label, "kind": "imap-read-only"})
        batches = []
        for start in range(0, len(rows), 25):
            with ExitStack() as stack:
                files = [("files", (row["filename"], stack.enter_context((path.parent / row["filename"]).open("rb")), "message/rfc822")) for row in rows[start:start + 25]]
                paths = {row["filename"]: row["original_path"] for row in rows[start:start + 25]}
                batches.append(api.request("POST", api.case_route(case, "/imports"), files=files, data={"source_id": source["id"], "source_paths": json.dumps(paths)}))
        show_result({"items": batches, "file_count": len(rows), "notice": "Imported original bytes and UID provenance; local acquisition manifest remains available separately."}, ctx.obj)
    except (KeyError, TypeError, ValueError, OSError):
        fail("The acquisition manifest or its local originals are unavailable or invalid.", 2)
