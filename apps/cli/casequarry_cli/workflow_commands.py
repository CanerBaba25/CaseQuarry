"""Public-API workflow commands; server validation and permissions remain authoritative."""

import hashlib
import json
import re
from pathlib import Path
from typing import Annotated

import typer

from .client import API, fail


def document(path):
    try:
        with path.open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576:
            fail("JSON request documents must be at most 1 MiB.", 2)
        value = json.loads(raw)
        if not isinstance(value, dict):
            fail("Use a JSON object matching the public API request schema.", 2)
        return value
    except (OSError, ValueError):
        fail("The JSON request document is missing or invalid.", 2)


def redacted(value):
    if isinstance(value, dict):
        return {key: "[redacted]" if key.lower() in {"password", "access_token", "token", "secret", "provisioning_uri", "totp_secret"} else redacted(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redacted(item) for item in value]
    return value


def display(value, options):
    from .main import show
    show(redacted(value), options)


def identity(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        fail("Use an exact resource ID without path separators.", 2)
    return value


def register(app, ingest, auth, email, evidence):
    api_group = typer.Typer(help="Authenticated JSON public-API requests using bounded files; sensitive response fields are redacted.")
    app.add_typer(api_group, name="api")

    @api_group.command("request")
    def request(ctx: typer.Context, method: str, route: str, body: Path | None = None, data_file: Path | None = None):
        selected = method.upper()
        if selected not in {"GET", "POST", "PUT", "PATCH", "DELETE"} or (body and data_file):
            fail("Use GET/POST/PUT/PATCH/DELETE and at most one JSON --body or binary --data-file.", 2)
        if route.startswith("/api/v1"):
            fail("Give the API resource path, such as /cases, without /api/v1.", 2)
        kwargs = {}
        if body:
            kwargs["json"] = document(body)
        if data_file:
            try:
                with data_file.open("rb") as stream:
                    data = stream.read(64 * 1024 * 1024 + 1)
                if len(data) > 64 * 1024 * 1024:
                    fail("Binary request parts must be at most 64 MiB.", 2)
                kwargs.update(content=data, headers={"Content-Type": "application/octet-stream", "X-Chunk-SHA256": hashlib.sha256(data).hexdigest()})
            except OSError:
                fail("The binary request part is unavailable.", 4)
        display(API(ctx.obj).request(selected, route, **kwargs), ctx.obj)

    for group_name, resource in [("source", "sources"), ("custodian", "custodians"), ("member", "members"), ("task", "tasks"), ("hold", "holds"), ("issue", "issues"), ("saved-search", "saved-searches"), ("review-set", "review-sets"), ("assignment", "assignments"), ("upload", "upload-sessions")]:
        group = typer.Typer(help=f"Manage authorized {resource} through the public API. Mutation --body uses its exact JSON schema.")
        app.add_typer(group, name=group_name)
        add_resource(group, resource)
        if resource == "tasks":
            add_mutation(group, "update", resource, "PATCH")
        if resource == "members":
            add_mutation(group, "remove", resource, "DELETE")
        if resource == "holds":
            add_mutation(group, "activate", resource, "POST", "/activate")
            add_mutation(group, "release", resource, "POST", "/release")
        if resource == "issues":
            add_mutation(group, "link", resource, "POST", "/evidence")
        if resource == "saved-searches":
            add_mutation(group, "run", resource, "POST", "/execute")
        if resource == "upload-sessions":
            add_mutation(group, "complete", resource, "POST", "/complete")
        if resource == "assignments":
            for action in ("claim", "release", "complete", "cancel"):
                add_mutation(group, action, resource, "POST", "/" + action)

    for action in ("pause", "resume", "cancel"):
        add_mutation(ingest, action, "imports", "POST", "/" + action)

    @auth.command("mfa-status")
    def mfa_status(ctx: typer.Context):
        display(API(ctx.obj).request("GET", "/auth/mfa/status"), ctx.obj)

    @auth.command("sessions")
    def sessions(ctx: typer.Context):
        display(API(ctx.obj).request("GET", "/auth/sessions"), ctx.obj)

    @auth.command("revoke-session")
    def revoke_session(ctx: typer.Context, session_id: str, reason: Annotated[str, typer.Option()]):
        display(API(ctx.obj).request("POST", f"/auth/sessions/{identity(session_id)}/revoke", json={"reason": reason}), ctx.obj)

    @auth.command("change-password")
    def change_password(ctx: typer.Context, body: Annotated[Path, typer.Option()]):
        display(API(ctx.obj).request("POST", "/auth/password/change", json=document(body)), ctx.obj)

    user = typer.Typer(help="Firm administrator account changes; credentials remain in bounded JSON input files.")
    app.add_typer(user, name="user")

    @user.command("list")
    def users(ctx: typer.Context):
        display(API(ctx.obj).request("GET", "/users"), ctx.obj)

    @user.command("create")
    def create_user(ctx: typer.Context, body: Annotated[Path, typer.Option()]):
        display(API(ctx.obj).request("POST", "/users", json=document(body)), ctx.obj)

    @user.command("update")
    def update_user(ctx: typer.Context, user_id: str, body: Annotated[Path, typer.Option()]):
        display(API(ctx.obj).request("PATCH", f"/users/{identity(user_id)}", json=document(body)), ctx.obj)

    for command, resource in [("network", "network"), ("timeline", "timeline"), ("traffic", "analytics/traffic")]:
        add_read(email, command, resource)

    @evidence.command("entities")
    def entities(ctx: typer.Context, item_id: str, case: str | None = None):
        api = API(ctx.obj)
        display(api.request("GET", api.case_route(case, f"/evidence/{identity(item_id)}/entities")), ctx.obj)

    @evidence.command("near-duplicates")
    def near_duplicates(ctx: typer.Context, item_id: str, case: str | None = None, threshold: Annotated[float, typer.Option(min=0, max=1)] = 0.75, candidate_limit: Annotated[int, typer.Option(min=1, max=100)] = 100, limit: Annotated[int, typer.Option(min=1, max=100)] = 20):
        api = API(ctx.obj)
        display(api.request("POST", api.case_route(case, f"/evidence/{identity(item_id)}/near-duplicates"), json={"threshold": threshold, "candidate_limit": candidate_limit, "limit": limit}), ctx.obj)

    @evidence.command("compare")
    def compare(ctx: typer.Context, left_id: str, right_id: str, case: str | None = None):
        api = API(ctx.obj)
        display(api.request("POST", api.case_route(case, "/compare"), json={"left_id": identity(left_id), "right_id": identity(right_id)}), ctx.obj)


def add_read(group, command, resource):
    @group.command(command)
    def read(ctx: typer.Context, case: str | None = None):
        api = API(ctx.obj)
        display(api.request("GET", api.case_route(case, "/" + resource)), ctx.obj)


def add_resource(group, resource):
    if resource != "upload-sessions":
        add_read(group, "list", resource)

    @group.command("create")
    def create(ctx: typer.Context, body: Annotated[Path, typer.Option()], case: str | None = None):
        api = API(ctx.obj)
        display(api.request("POST", api.case_route(case, "/" + resource), json=document(body)), ctx.obj)

    if resource in {"issues", "review-sets", "assignments", "upload-sessions"}:
        @group.command("show")
        def show(ctx: typer.Context, resource_id: str, case: str | None = None):
            api = API(ctx.obj)
            display(api.request("GET", api.case_route(case, f"/{resource}/{identity(resource_id)}")), ctx.obj)


def add_mutation(group, command, resource, method, suffix=""):
    @group.command(command)
    def mutate(ctx: typer.Context, resource_id: str, body: Path | None = None, case: str | None = None):
        api = API(ctx.obj)
        kwargs = {"json": document(body)} if body else {}
        display(api.request(method, api.case_route(case, f"/{resource}/{identity(resource_id)}{suffix}"), **kwargs), ctx.obj)
