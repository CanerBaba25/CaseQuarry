"""CaseQuarry CLI. All evidence operations use the authenticated public API."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import os
import secrets
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .client import API, Options, fail, logout, profiles, save_login
from .connector_commands import app as connectors
from .native import native_available
from .workflow_commands import register as register_workflows

app = typer.Typer(no_args_is_help=True, help="CaseQuarry: preserve, search and review evidence privately.")
auth = typer.Typer(help="Sign in using the API; store sessions only in the OS keyring.")
cases = typer.Typer(help="Create and manage authorized matters.")
ingest = typer.Typer(help="Plan and import local files with preserved originals.")
search_app = typer.Typer(
    invoke_without_command=True, help="Search authorized evidence and server-backed groups."
)
evidence = typer.Typer(help="Inspect and verify authorized evidence.")
review = typer.Typer(help="Record human review decisions and tags.")
exports = typer.Typer(help="Export authorized metadata and integrity manifests.")
audit = typer.Typer(help="Inspect and verify authorized audit events.")
email = typer.Typer(help="Email metadata, participants and conversations.")
ai = typer.Typer(help="Optional source-cited analysis; unavailable until configured.")
benchmark = typer.Typer(help="Generate deterministic synthetic evidence; scale targets require measurements.")
for name, group in [
    ("auth", auth),
    ("case", cases),
    ("ingest", ingest),
    ("search", search_app),
    ("evidence", evidence),
    ("review", review),
    ("export", exports),
    ("audit", audit),
    ("email", email),
    ("ai", ai),
    ("benchmark", benchmark),
    ("connector", connectors),
]:
    app.add_typer(group, name=name)

register_workflows(app, ingest, auth, email, evidence)


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"CaseQuarry {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    server: str | None = None,
    case: Annotated[str | None, typer.Option("--case")] = None,
    profile: str = "default",
    output: str = "table",
    limit: Annotated[int, typer.Option(min=1, max=200)] = 50,
    cursor: str | None = None,
    dry_run: bool = False,
    yes: bool = False,
    reason: str | None = None,
    version: Annotated[bool, typer.Option("--version", callback=version_callback, is_eager=True)] = False,
) -> None:
    if output not in {"table", "json", "csv"}:
        fail("--output must be table, json or csv.", 2)
    ctx.obj = Options(server, case, profile, output, limit, cursor, dry_run, reason, yes)


def show(value: Any, options: Options, output: str | None = None) -> None:
    mode = output or options.output
    if mode == "json":
        typer.echo(json.dumps(value, indent=2, ensure_ascii=False))
        return
    rows = value.get("items", value.get("values", [])) if isinstance(value, dict) else value
    if not isinstance(rows, list) or not rows:
        if mode == "csv":
            rows = [value] if isinstance(value, dict) else [{"value": value}]
        else:
            typer.echo(json.dumps(value, indent=2, ensure_ascii=False))
            return
    rows = [row if isinstance(row, dict) else {"value": row} for row in rows]
    fields = list(dict.fromkeys(field for row in rows for field in row))
    if mode == "csv":
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(item, ensure_ascii=False) if isinstance(item, (list, dict)) else item
                    for key, item in row.items()
                }
            )
        typer.echo(stream.getvalue(), nl=False)
    elif mode == "table":
        table = Table()
        for field in fields[:8]:
            table.add_column(field.replace("_", " "))
        for row in rows:
            table.add_row(*(str(row.get(field, "")) for field in fields[:8]))
        Console(markup=False).print(table)
        if isinstance(value, dict) and "total_hits" in value:
            typer.echo(f"Matched: {value['total_hits']}; next cursor: {value.get('next_cursor') or 'none'}")
    else:
        fail("--output must be table, json or csv.", 2)


def init_environment(path: Path = Path(".env")) -> bool:
    if path.exists():
        return False
    token, password = (secrets.token_urlsafe(48) for _ in range(2))
    content = f"CASEQUARRY_SETUP_TOKEN={token}\nPOSTGRES_PASSWORD={password}\nCASEQUARRY_DATABASE_URL=sqlite:///.data/casequarry.db\nCASEQUARRY_STORAGE_ROOT=.data/storage\nCASEQUARRY_WORKER_MODE=embedded\nCASEQUARRY_AI_ENABLED=false\nCASEQUARRY_ALLOW_REMOTE_AI=false\nCASEQUARRY_ALLOW_INSECURE_LOCAL_COOKIES=true\nCASEQUARRY_API_INTERNAL_URL=http://127.0.0.1:8000\nNEXT_TELEMETRY_DISABLED=1\nWEB_PORT=3000\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)
    if os.name != "nt":
        path.chmod(0o600)
    return True


@app.command("init")
def initialize(local: bool = False) -> None:
    if not local:
        fail("Use --local to generate this checkout's .env; server provisioning is not implemented.", 2)
    created = init_environment()
    typer.echo(
        "Generated .env with unique local secrets. Run uv run python scripts/tasks.py dev, then open /setup. Read the one-time setup token locally from .env."
        if created
        else ".env already exists; no secrets were overwritten."
    )


@app.command()
def health(ctx: typer.Context, output: str | None = None) -> None:
    show(API(ctx.obj).request("GET", "/health", auth=False), ctx.obj, output)


@app.command()
def status(ctx: typer.Context) -> None:
    health(ctx)


@app.command()
def doctor(ctx: typer.Context, check: str = "storage,db,search,queue,ocr") -> None:
    value = API(ctx.obj).request("GET", "/health", auth=False)
    show(
        {
            "requested_checks": check.split(","),
            "api": value,
            "notice": "Server health reports implemented subsystems only; OCR and large-scale search need separate validation.",
        },
        ctx.obj,
    )


@app.command("version")
def version_command(components: bool = False) -> None:
    typer.echo(
        json.dumps(
            {
                "casequarry": __version__,
                **(
                    {
                        "python": sys.version.split()[0],
                        "rust_native_verifier": "available"
                        if native_available()
                        else "not built; Python fallback available",
                    }
                    if components
                    else {}
                ),
            }
        )
    )


@app.command()
def setup(
    ctx: typer.Context,
    firm_name: Annotated[str, typer.Option()],
    name: Annotated[str, typer.Option()],
    email: Annotated[str, typer.Option()],
) -> None:
    if ctx.obj.dry_run:
        show(
            {"dry_run": True, "action": "administrator setup", "firm_name": firm_name, "email": email},
            ctx.obj,
        )
        return
    token = os.getenv("CASEQUARRY_SETUP_TOKEN") or typer.prompt("One-time setup token", hide_input=True)
    password = typer.prompt("Administrator password", hide_input=True, confirmation_prompt=True)
    show(
        API(ctx.obj).request(
            "POST",
            "/setup",
            auth=False,
            json={"token": token, "firm_name": firm_name, "name": name, "email": email, "password": password},
        ),
        ctx.obj,
    )


@auth.command("login")
def login(
    ctx: typer.Context,
    email: str | None = None,
    server: str | None = None,
    password_stdin: bool = False,
    totp_code: str | None = None,
) -> None:
    if ctx.obj.dry_run:
        show({"dry_run": True, "action": "login", "profile": ctx.obj.profile}, ctx.obj)
        return
    api = API(ctx.obj, server)
    address = email or typer.prompt("Email")
    password = (
        sys.stdin.readline().rstrip("\r\n") if password_stdin else typer.prompt("Password", hide_input=True)
    )
    result = api.request(
        "POST",
        "/auth/token",
        auth=False,
        json={"email": address, "password": password, "totp_code": totp_code},
    )
    token = result.get("access_token")
    if not token:
        fail("The API did not return a session token.", 7)
    save_login(ctx.obj.profile, api.server, address, token)
    typer.echo(f"Signed in as {address}; session stored in the OS keyring.")


@auth.command("logout")
def auth_logout(ctx: typer.Context) -> None:
    if ctx.obj.dry_run:
        show({"dry_run": True, "action": "logout", "profile": ctx.obj.profile}, ctx.obj)
        return
    try:
        API(ctx.obj).request("POST", "/auth/logout")
    finally:
        logout(ctx.obj.profile)
    typer.echo("Signed out; local credential cleared.")


@auth.command("whoami")
def whoami(ctx: typer.Context) -> None:
    show(API(ctx.obj).request("GET", "/me"), ctx.obj)


@auth.command("profiles")
def auth_profiles(ctx: typer.Context) -> None:
    show([{"profile": key, **value} for key, value in profiles().items()], ctx.obj)


@cases.command("create")
def case_create(
    ctx: typer.Context,
    number: Annotated[str, typer.Option()],
    title: Annotated[str, typer.Option()],
    description: str = "",
    client: str = "",
    jurisdiction: str = "",
    case_type: str = "civil",
) -> None:
    payload = {
        "matter_number": number,
        "title": title,
        "description": description,
        "client": client,
        "jurisdiction": jurisdiction,
        "case_type": case_type,
    }
    show(
        {"dry_run": True, "case": payload}
        if ctx.obj.dry_run
        else API(ctx.obj).request("POST", "/cases", json=payload),
        ctx.obj,
    )


@cases.command("list")
def case_list(ctx: typer.Context, sort: str = "updated", output: str | None = None) -> None:
    show(
        API(ctx.obj).request("GET", "/cases", params={"limit": ctx.obj.limit, "sort": sort}), ctx.obj, output
    )


@cases.command("show")
def case_show(ctx: typer.Context, case_id: str) -> None:
    show(API(ctx.obj).request("GET", API(ctx.obj).case_route(case_id)), ctx.obj)


@cases.command("stats")
def case_stats(ctx: typer.Context, case_id: str) -> None:
    show(API(ctx.obj).request("GET", API(ctx.obj).case_route(case_id, "/stats")), ctx.obj)


@cases.command("archive")
def case_archive(ctx: typer.Context, case_id: str, reason: Annotated[str, typer.Option()]) -> None:
    show(
        API(ctx.obj).request("POST", API(ctx.obj).case_route(case_id, "/archive"), json={"reason": reason}),
        ctx.obj,
    )


@cases.command("restore")
def case_restore(ctx: typer.Context, case_id: str) -> None:
    show(API(ctx.obj).request("POST", API(ctx.obj).case_route(case_id, "/restore")), ctx.obj)


def import_paths(path: Path, recursive: bool) -> list[Path]:
    if path.is_symlink():
        fail("Symbolic-link import paths are refused.", 2)
    if path.is_file():
        return [path]
    if not path.is_dir():
        fail("Import path does not exist.", 4)
    return sorted(
        item
        for item in (path.rglob("*") if recursive else path.iterdir())
        if item.is_file() and not item.is_symlink()
    )


@ingest.command("plan")
def ingest_plan(
    ctx: typer.Context,
    path: Annotated[Path, typer.Option()],
    case: str | None = None,
    recursive: bool = False,
) -> None:
    files = import_paths(path, recursive)
    show(
        {
            "dry_run": True,
            "case_id": case or ctx.obj.case_id,
            "file_count": len(files),
            "total_bytes": sum(item.stat().st_size for item in files),
            "formats": sorted({item.suffix.lower() for item in files}),
            "notice": "Unsupported/locked files are preserved and reported; no data uploaded by this command.",
        },
        ctx.obj,
    )


@ingest.command("files")
def ingest_files(
    ctx: typer.Context,
    path: Annotated[Path, typer.Option()],
    case: str | None = None,
    recursive: bool = False,
    source: str | None = None,
    source_label: str = "CLI import",
    custodian: str = "",
    wait: bool = False,
) -> None:
    files = import_paths(path, recursive)
    if ctx.obj.dry_run:
        ingest_plan(ctx, path, case, recursive)
        return
    api = API(ctx.obj)
    route = api.case_route(case, "/imports")
    import_root = path if path.is_dir() else path.parent
    batches = []
    for start in range(0, len(files), 25):
        with ExitStack() as stack:
            handles = [
                (
                    "files",
                    (
                        item.relative_to(import_root).as_posix(),
                        stack.enter_context(item.open("rb")),
                        "application/octet-stream",
                    ),
                )
                for item in files[start : start + 25]
            ]
            data = {"source_label": source_label, "custodian_name": custodian}
            if source:
                data["source_id"] = source
            batch = api.request("POST", route, files=handles, data=data)
            if wait:
                batch_id = batch.get("batch_id", batch.get("id"))
                deadline = time.monotonic() + 600
                while batch_id and time.monotonic() < deadline:
                    batch = api.request("GET", route + "/" + str(batch_id))
                    if batch.get("state") in {
                        "completed",
                        "partial",
                        "failed",
                        "cancelled",
                        "COMPLETED",
                        "PARTIAL",
                        "FAILED",
                    }:
                        break
                    time.sleep(1)
                else:
                    fail("Import continues in the server; inspect ingest status with its batch ID.", 6)
            batches.append(batch)
    show({"items": batches}, ctx.obj)
    if any(batch.get("state", "").lower() in {"partial", "failed"} for batch in batches):
        raise typer.Exit(6)


for format_name in ["eml", "mbox", "folder", "archive", "msg", "pst"]:
    ingest.command(format_name)(ingest_files)


@ingest.command("list")
def ingest_list(ctx: typer.Context, case: str | None = None) -> None:
    api = API(ctx.obj)
    show(api.request("GET", api.case_route(case, "/imports")), ctx.obj)


@ingest.command("status")
def ingest_status(ctx: typer.Context, batch_id: str, case: str | None = None) -> None:
    api = API(ctx.obj)
    show(api.request("GET", api.case_route(case, f"/imports/{batch_id}")), ctx.obj)


@ingest.command("errors")
def ingest_errors(
    ctx: typer.Context, batch_id: str, case: str | None = None, output: str | None = None
) -> None:
    api = API(ctx.obj)
    show(api.request("GET", api.case_route(case, f"/imports/{batch_id}/errors")), ctx.obj, output)


@ingest.command("retry")
def ingest_retry(
    ctx: typer.Context, batch_id: str, case: str | None = None, failed_only: bool = True
) -> None:
    api = API(ctx.obj)
    show(
        api.request(
            "POST", api.case_route(case, f"/imports/{batch_id}/retry"), json={"failed_only": failed_only}
        ),
        ctx.obj,
    )


@search_app.callback()
def search(
    ctx: typer.Context,
    case: str | None = None,
    query: str = "",
    sort: str = "sent_at:desc",
    group_by: str | None = None,
    type: Annotated[str | None, typer.Option("--type")] = None,
    tag: str | None = None,
    has_attachment: bool | None = None,
    from_date: Annotated[str | None, typer.Option("--from")] = None,
    to_date: Annotated[str | None, typer.Option("--to")] = None,
    limit: Annotated[int | None, typer.Option(min=1, max=200)] = None,
    cursor: str | None = None,
    output: str | None = None,
    mode: str = "keyword",
    view: str = "table",
) -> None:
    if ctx.invoked_subcommand:
        return
    field, _, order = sort.partition(":")
    filters: dict[str, Any] = {}
    if type:
        filters["item_types"] = [type]
    if tag:
        filters["tags"] = [tag]
    if has_attachment is not None:
        filters["has_attachment"] = has_attachment
    if from_date:
        filters["date_from"] = from_date
    if to_date:
        filters["date_to"] = to_date
    payload = {
        "query": query,
        "mode": mode,
        "filters": filters,
        "sort": [{"field": field, "order": order or "desc"}],
        "group_by": group_by,
        "page_size": limit or ctx.obj.limit,
        "cursor": cursor or ctx.obj.cursor,
    }
    api = API(ctx.obj)
    value = api.request("POST", api.case_route(case, "/search"), json=payload)
    if view == "count":
        value = {key: value[key] for key in ["case_id", "total_hits", "total_hits_relation"] if key in value}
    show(value, ctx.obj, output)


@search_app.command("facets")
def search_facets(
    ctx: typer.Context, case: str | None = None, query: str = "", fields: str = "sender,month,type"
) -> None:
    api = API(ctx.obj)
    show(
        api.request(
            "POST", api.case_route(case, "/search/facets"), json={"query": query, "fields": fields.split(",")}
        ),
        ctx.obj,
    )


@evidence.command("show")
def evidence_show(ctx: typer.Context, item_id: str, case: str | None = None) -> None:
    api = API(ctx.obj)
    show(api.request("GET", api.case_route(case, f"/evidence/{item_id}")), ctx.obj)


@evidence.command("hash-file")
def hash_local_file(ctx: typer.Context, path: Annotated[Path, typer.Option()], engine: str = "auto") -> None:
    from .native import hash_file

    show(hash_file(path, engine), ctx.obj)


@evidence.command("verify-file")
def verify_local_file(
    ctx: typer.Context,
    path: Annotated[Path, typer.Option()],
    sha256: Annotated[str, typer.Option()],
    byte_size: Annotated[int | None, typer.Option(min=0)] = None,
    engine: str = "auto",
) -> None:
    from .native import verify_file

    result = verify_file(path, sha256, byte_size, engine)
    show(result, ctx.obj)
    if not result["valid"]:
        raise typer.Exit(8)


@evidence.command("verify-manifest")
def verify_native_manifest(
    ctx: typer.Context,
    path: Annotated[Path, typer.Option()],
    root: Annotated[Path, typer.Option()],
    engine: str = "auto",
) -> None:
    from .native import verify_manifest

    result = verify_manifest(path, root, engine)
    show(result, ctx.obj)
    if not result["valid"]:
        raise typer.Exit(8)


@ingest.command("inventory-mbox")
def inventory_local_mbox(
    ctx: typer.Context,
    path: Annotated[Path, typer.Option()],
    engine: str = "auto",
    max_message_bytes: Annotated[int, typer.Option(min=1)] = 256 * 1024 * 1024,
    max_line_bytes: Annotated[int, typer.Option(min=1)] = 8 * 1024 * 1024,
) -> None:
    from .native import scan_mbox

    show(scan_mbox(path, engine, max_message_bytes, max_line_bytes), ctx.obj)


@evidence.command("text")
def evidence_text(
    ctx: typer.Context, item_id: str, case: str | None = None, output: str | None = None
) -> None:
    api = API(ctx.obj)
    show(api.request("GET", api.case_route(case, f"/evidence/{item_id}/content")), ctx.obj, output)


@evidence.command("verify")
def evidence_verify(ctx: typer.Context, item_id: str, case: str | None = None, deep: bool = False) -> None:
    api = API(ctx.obj)
    result = api.request("POST", api.case_route(case, f"/evidence/{item_id}/verify"))
    show(result, ctx.obj)
    if result.get("valid") is False or result.get("integrity_status") == "failed":
        raise typer.Exit(8)


@evidence.command("download")
def evidence_download(
    ctx: typer.Context,
    item_id: str,
    case: str | None = None,
    original: bool = True,
    output_dir: Path = Path("downloaded"),
) -> None:
    if ctx.obj.dry_run:
        show(
            {
                "dry_run": True,
                "action": "download original",
                "evidence_id": item_id,
                "output_dir": str(output_dir),
            },
            ctx.obj,
        )
        return
    api = API(ctx.obj)
    response = api.request("GET", api.case_route(case, f"/evidence/{item_id}/original"), raw=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{item_id}.original"
    if destination.exists():
        fail("Destination exists; use a different --output-dir.", 5)
    destination.write_bytes(response.content)
    typer.echo(f"Saved original to {destination}")


@review.command("decision")
def review_decision(
    ctx: typer.Context,
    item_id: str,
    value: Annotated[str, typer.Option()],
    case: str | None = None,
    reason: str = "",
    expected_version: int | None = None,
) -> None:
    api = API(ctx.obj)
    payload: dict[str, Any] = {"review_status": value.replace("-", "_"), "note": reason}
    if expected_version is not None:
        payload["expected_version"] = expected_version
    show(api.request("POST", api.case_route(case, f"/evidence/{item_id}/reviews"), json=payload), ctx.obj)


@review.command("tag")
def review_tag(
    ctx: typer.Context, item_id: str, tag: Annotated[str, typer.Option()], case: str | None = None
) -> None:
    api = API(ctx.obj)
    item = api.request("GET", api.case_route(case, f"/evidence/{item_id}"))
    tags = list(dict.fromkeys([*item.get("tags", []), tag]))
    show(
        api.request(
            "POST",
            api.case_route(case, f"/evidence/{item_id}/reviews"),
            json={"tags": tags, "expected_version": item.get("review_version", item.get("version", 0))},
        ),
        ctx.obj,
    )


@evidence.command("note")
def evidence_note(
    ctx: typer.Context, item_id: str, text: Annotated[str, typer.Option()], case: str | None = None
) -> None:
    api = API(ctx.obj)
    show(
        api.request("POST", api.case_route(case, f"/evidence/{item_id}/reviews"), json={"note": text}),
        ctx.obj,
    )


def export_file(
    ctx: typer.Context, case: str | None, path: Path, format_name: str, query: str, reason: str, yes: bool
) -> None:
    api = API(ctx.obj)
    reason = reason or ctx.obj.reason or ""
    if ctx.obj.dry_run:
        show({"dry_run": True, "format": format_name, "query": query, "path": str(path)}, ctx.obj)
        return
    if not reason.strip():
        fail("An export --reason is required.", 2)
    if not (yes or ctx.obj.yes) and not typer.confirm(
        "Export this authorized matter's matching metadata and manifest?"
    ):
        raise typer.Exit(2)
    manifest_path = path.with_suffix(path.suffix + ".manifest.json")
    if path.exists() or manifest_path.exists():
        fail("Export or manifest destination exists; choose another --path.", 5)
    result = api.request(
        "POST",
        api.case_route(case, "/exports"),
        json={
            "format": format_name,
            "query_spec": {"query": query, "mode": "keyword"},
            "reason": reason,
            "confirmed": True,
        },
    )
    url = result.get("download_url")
    if not url:
        show(result, ctx.obj)
        fail("Export is not ready. Inspect its server job status before downloading.", 6)
    if not url.startswith("/api/v1/"):
        fail("API returned a download location outside its authorized origin.", 7)
    response = api.request("GET", url.removeprefix("/api/v1"), raw=True)
    if result.get("sha256") and hashlib.sha256(response.content).hexdigest() != result["sha256"]:
        fail("Downloaded export hash does not match the server's recorded package hash.", 8)
    manifest_url = result.get("manifest_url")
    if not manifest_url or not manifest_url.startswith("/api/v1/"):
        fail("API did not provide an authorized hash-manifest location; no export files were saved.", 7)
    manifest = api.request("GET", manifest_url.removeprefix("/api/v1"), raw=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(response.content)
    with manifest_path.open("xb") as stream:
        stream.write(manifest.content)
    typer.echo(f"Saved {format_name} export to {path} and hash manifest to {manifest_path}.")


@exports.command("csv")
def export_csv(
    ctx: typer.Context,
    path: Annotated[Path, typer.Option()],
    case: str | None = None,
    query: str = "",
    reason: str = "",
    yes: bool = False,
) -> None:
    export_file(ctx, case, path, "csv", query, reason, yes)


@exports.command("json")
def export_json(
    ctx: typer.Context,
    path: Annotated[Path, typer.Option()],
    case: str | None = None,
    query: str = "",
    reason: str = "",
    yes: bool = False,
) -> None:
    export_file(ctx, case, path, "json", query, reason, yes)


@exports.command("package")
def export_zip(
    ctx: typer.Context,
    path: Annotated[Path, typer.Option()],
    case: str | None = None,
    query: str = "",
    reason: str = "",
    yes: bool = False,
) -> None:
    export_file(ctx, case, path, "zip", query, reason, yes)


@audit.command("list")
def audit_list(ctx: typer.Context, case: str | None = None) -> None:
    api = API(ctx.obj)
    show(api.request("GET", api.case_route(case, "/audit"), params={"limit": ctx.obj.limit}), ctx.obj)


@audit.command("verify")
def audit_verify(ctx: typer.Context, case: str | None = None) -> None:
    api = API(ctx.obj)
    result = api.request("POST", api.case_route(case, "/audit/verify"))
    show(result, ctx.obj)
    if result.get("valid") is False:
        raise typer.Exit(8)


@email.command("people")
def email_people(ctx: typer.Context, case: str | None = None, sort: str = "message-count:desc") -> None:
    api = API(ctx.obj)
    show(api.request("GET", api.case_route(case, "/people"), params={"sort": sort}), ctx.obj)


@email.command("show")
def email_show(ctx: typer.Context, item_id: str, case: str | None = None) -> None:
    evidence_show(ctx, item_id, case)


@email.command("thread")
def email_thread(ctx: typer.Context, item_id: str, case: str | None = None) -> None:
    api = API(ctx.obj)
    show(api.request("GET", api.case_route(case, f"/emails/{item_id}/thread")), ctx.obj)


@ai.command("providers")
def ai_providers(ctx: typer.Context, case: str | None = None) -> None:
    api = API(ctx.obj)
    show(api.request("GET", api.case_route(case, "/ai/providers")), ctx.obj)


@ai.command("ask")
def ai_ask(
    ctx: typer.Context,
    question: Annotated[str, typer.Option()],
    case: str | None = None,
    citations: str = "required",
) -> None:
    api = API(ctx.obj)
    show(
        api.request(
            "POST", api.case_route(case, "/ai/ask"), json={"question": question, "citations": citations}
        ),
        ctx.obj,
    )


@benchmark.command("generate")
def benchmark_generate(
    ctx: typer.Context,
    count: Annotated[int, typer.Option(min=1, max=2_000_000)] = 100,
    seed: int = 42,
    output: Path = Path(".data/synthetic"),
    documents: int = 100,
) -> None:
    if ctx.obj.dry_run:
        show(
            {
                "dry_run": True,
                "action": "generate synthetic evidence",
                "count": count,
                "documents": documents,
                "output": str(output),
            },
            ctx.obj,
        )
        return
    generator_path = Path(__file__).resolve().parents[3] / "scripts" / "generate_synthetic_emails.py"
    if not generator_path.exists():
        fail(
            "Synthetic generation uses a local QA asset excluded from public source releases. The core application can import your authorized files without it.",
            7,
        )
    specification = importlib.util.spec_from_file_location("casequarry_synthetic_generator", generator_path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    show(module.generate(output, count, seed, documents), Options(output="json"))
