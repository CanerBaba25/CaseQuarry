"""Real routed export/governance flows with independently stored synthetic originals."""

import csv
import hashlib
import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from casequarry import exports, governance_routes
from casequarry.audit import verify_chain
from casequarry.config import Settings
from casequarry.database import Database
from casequarry.models import (
    Case,
    Evidence,
    Export,
    ImportBatch,
    Member,
    Occurrence,
    Original,
    Source,
    Tenant,
    User,
)
from casequarry.security import create_session
from casequarry.storage import Storage
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import select


def add_evidence(db, storage, user, case_id, *, filename="invoice.txt", raw=b"Synthetic evidence bytes."):
    source = Source(tenant_id=user.tenant_id, case_id=case_id, label="Synthetic folder", operator_id=user.id)
    db.add(source)
    db.flush()
    batch = ImportBatch(tenant_id=user.tenant_id, case_id=case_id, source_id=source.id, submitted_by=user.id)
    db.add(batch)
    db.flush()
    key, digest, size = storage.store_bytes(user.tenant_id, case_id, raw)
    original = Original(tenant_id=user.tenant_id, case_id=case_id, sha256=digest, byte_size=size, storage_key=key)
    db.add(original)
    db.flush()
    occurrence = Occurrence(tenant_id=user.tenant_id, case_id=case_id, original_id=original.id, source_id=source.id, batch_id=batch.id, original_name=filename, original_path="synthetic/" + filename, occurrence_key=hashlib.sha256(batch.id.encode()).hexdigest())
    db.add(occurrence)
    db.flush()
    evidence = Evidence(tenant_id=user.tenant_id, case_id=case_id, original_id=original.id, occurrence_id=occurrence.id, source_id=source.id, item_type="text", title="=1+1", filename=filename, text="Body secret must not appear in metadata exports.", review_status="responsive", parser_state="indexed")
    db.add(evidence)
    db.flush()
    return evidence, original


@pytest.fixture
def env(tmp_path):
    settings = Settings(environment="test", database_url=f"sqlite:///{tmp_path / 'exports.sqlite'}", storage_path=tmp_path / "objects")
    database, storage = Database(settings), Storage(settings.storage_path)
    database.initialize()
    with database.sessions() as db:
        tenant = Tenant(name="Synthetic test firm")
        db.add(tenant)
        db.flush()
        user = User(tenant_id=tenant.id, email="owner@example.test", name="Synthetic owner", password_hash="unused", role="firm_admin")
        db.add(user)
        db.flush()
        cases = [Case(tenant_id=tenant.id, matter_number=f"TEST-{number}", title="Synthetic matter", created_by=user.id) for number in (1, 2)]
        db.add_all(cases)
        db.flush()
        db.add(Member(tenant_id=tenant.id, case_id=cases[0].id, user_id=user.id, role="matter_lead"))
        evidence, original = add_evidence(db, storage, user, cases[0].id)
        private, _private_original = add_evidence(db, storage, user, cases[1].id, filename="private.txt")
        _session, token, _csrf = create_session(db, user, 3600)
        db.commit()
        identifiers = {"user_id": user.id, "case_id": cases[0].id, "private_case_id": cases[1].id, "evidence_id": evidence.id, "original_id": original.id, "private_id": private.id, "tenant_id": tenant.id}
    app = FastAPI()
    app.state.db, app.state.storage, app.state.settings = database, storage, settings
    app.include_router(exports.router)
    app.include_router(governance_routes.router)

    @app.exception_handler(HTTPException)
    async def safe_error(_request, error):
        return JSONResponse(status_code=error.status_code, content=error.detail)

    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield SimpleNamespace(client=client, database=database, storage=storage, settings=settings, **identifiers)
    database.dispose()


def request_export(env, format="json", **changes):
    body = {"format": format, "evidence_ids": [env.evidence_id], "reason": "Synthetic acceptance export", "confirmed": True}
    body.update(changes)
    return env.client.post(f"/api/v1/cases/{env.case_id}/exports", json=body)


def complete_export(env, format="json"):
    response = request_export(env, format)
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["state"] == "pending"
    assert exports.process_pending_exports(env.database, env.settings, env.storage) is True
    response = env.client.get(f"/api/v1/cases/{env.case_id}/exports/{job['id']}")
    assert response.status_code == 200
    result = response.json()
    assert result["state"] == "completed", result
    return result


@pytest.mark.parametrize("format", ["csv", "json", "zip"])
def test_export_metadata_or_native_bytes_has_verified_manifest(env, format):
    job = complete_export(env, format)
    download = env.client.get(job["download_url"])
    assert download.status_code == 200, download.text
    assert hashlib.sha256(download.content).hexdigest() == job["sha256"]
    sidecar = env.client.get(job["manifest_url"])
    assert sidecar.status_code == 200
    assert hashlib.sha256(sidecar.content).hexdigest() == download.headers["x-manifest-sha256"]
    manifest = sidecar.json()
    assert manifest["item_count"] == 1
    assert manifest["items"][0]["evidence_id"] == env.evidence_id
    assert manifest["items"][0]["source_id"]
    assert manifest["items"][0]["occurrence_id"]
    if format == "csv":
        rows = list(csv.DictReader(io.StringIO(download.content.decode("utf-8-sig"))))
        assert rows[0]["title"] == "'=1+1"
        assert rows[0]["sha256"] == hashlib.sha256(b"Synthetic evidence bytes.").hexdigest()
        assert "Body secret" not in download.text
    elif format == "json":
        assert download.json()["manifest"] == manifest
        assert "Body secret" not in download.text
    else:
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            assert json.loads(archive.read("manifest.json")) == manifest
            entry = manifest["items"][0]
            original = archive.read(entry["package_path"])
            assert original == b"Synthetic evidence bytes."
            assert hashlib.sha256(original).hexdigest() == entry["sha256"]
    with env.database.sessions() as db:
        assert verify_chain(db, env.tenant_id, env.case_id)["valid"]


def test_export_requires_explicit_confirmation_and_scoped_evidence(env):
    assert request_export(env, confirmed=False).status_code == 422
    assert request_export(env, evidence_ids=[env.private_id]).status_code == 404
    assert request_export(env, evidence_ids=[]).status_code == 422
    assert env.client.get(f"/api/v1/cases/{env.private_case_id}/exports").status_code == 404


@pytest.mark.parametrize("status", ["suspected", "confirmed"])
@pytest.mark.parametrize("format", ["csv", "json", "zip"])
def test_privilege_holdback_applies_to_every_export_format(env, status, format):
    with env.database.sessions() as db:
        db.get(Evidence, env.evidence_id).privilege_status = status
        db.commit()
    response = request_export(env, format)
    assert response.status_code == 409
    assert response.json()["error_code"] == "PRIVILEGE_HOLDBACK"


def test_unreviewed_native_export_is_blocked_but_metadata_is_available(env):
    with env.database.sessions() as db:
        db.get(Evidence, env.evidence_id).review_status = "unreviewed"
        db.commit()
    assert request_export(env, "zip").status_code == 409
    assert complete_export(env, "json")["state"] == "completed"


@pytest.mark.parametrize("change", ["review", "source", "package", "manifest", "requester-membership", "requester-disabled"])
def test_download_revalidates_review_integrity_and_requester_permission(env, change):
    job = complete_export(env)
    with env.database.sessions() as db:
        record = db.get(Export, job["id"])
        if change == "review":
            db.get(Evidence, env.evidence_id).review_version += 1
        elif change == "source":
            env.storage.path(db.get(Original, env.original_id).storage_key).write_bytes(b"tampered original")
        elif change == "package":
            env.storage.path(record.storage_key).write_bytes(b"tampered package")
        elif change == "manifest":
            env.storage.path(record.counts["manifest_storage_key"]).write_bytes(b"tampered manifest")
        elif change == "requester-membership":
            db.delete(db.scalar(select(Member).where(Member.case_id == env.case_id, Member.user_id == env.user_id)))
        else:
            db.get(User, env.user_id).active = False
        db.commit()
    response = env.client.get(job["download_url"])
    assert response.status_code in {401, 403, 404, 409}
    assert response.json()["error_code"]


def test_worker_denies_requester_whose_matter_grant_was_revoked(env):
    response = request_export(env)
    assert response.status_code == 202
    job_id = response.json()["id"]
    with env.database.sessions() as db:
        db.delete(db.scalar(select(Member).where(Member.case_id == env.case_id, Member.user_id == env.user_id)))
        db.commit()
    assert exports.process_pending_exports(env.database, env.settings, env.storage) is True
    with env.database.sessions() as db:
        job = db.get(Export, job_id)
        assert job.state == "failed"
        assert job.storage_key is None
        assert job.counts["error_code"] == "NOT_FOUND"


def test_worker_rechecks_permission_after_package_generation(env, monkeypatch):
    response = request_export(env)
    job_id = response.json()["id"]
    write_package = exports._write_package

    def revoke_after_write(*arguments, **keywords):
        write_package(*arguments, **keywords)
        with env.database.sessions() as db:
            db.scalar(select(Member).where(Member.case_id == env.case_id, Member.user_id == env.user_id)).role = "read_only"
            db.commit()

    monkeypatch.setattr(exports, "_write_package", revoke_after_write)
    exports.process_pending_exports(env.database, env.settings, env.storage)
    with env.database.sessions() as db:
        job = db.get(Export, job_id)
        assert job.state == "failed"
        assert job.storage_key is None
        assert job.counts["error_code"] == "PERMISSION_DENIED"


@pytest.mark.parametrize("restriction", ["unreviewed", "privileged"])
def test_native_parent_cannot_disclose_restricted_embedded_attachment(env, restriction):
    with env.database.sessions() as db:
        user = db.get(User, env.user_id)
        child, _original = add_evidence(db, env.storage, user, env.case_id, filename="attachment.txt", raw=b"Contained child bytes")
        child.parent_id = env.evidence_id
        if restriction == "unreviewed":
            child.review_status = "unreviewed"
        else:
            child.privilege_status = "confirmed"
        db.commit()
    response = request_export(env, "zip")
    assert response.status_code == 409
    assert response.json()["error_code"] in {"REVIEW_REQUIRED", "PRIVILEGE_HOLDBACK"}


def test_native_parent_manifest_discloses_embedded_family_and_invalidates_changed_child(env):
    with env.database.sessions() as db:
        child, _original = add_evidence(db, env.storage, db.get(User, env.user_id), env.case_id, filename="attachment.txt", raw=b"Contained reviewed child bytes")
        child.parent_id = env.evidence_id
        db.commit()
        child_id = child.id
    job = complete_export(env, "zip")
    manifest = env.client.get(job["manifest_url"]).json()
    assert manifest["scope"]["selected_items"] == 1
    assert manifest["scope"]["contained_family_items"] == 1
    assert manifest["contained_family_review"][0]["evidence_id"] == child_id
    assert manifest["item_count"] == 1
    with env.database.sessions() as db:
        db.get(Evidence, child_id).privilege_status = "suspected"
        db.commit()
    assert env.client.get(job["download_url"]).status_code == 409


def test_new_embedded_family_after_snapshot_blocks_native_download(env):
    job = complete_export(env, "zip")
    with env.database.sessions() as db:
        child, _original = add_evidence(db, env.storage, db.get(User, env.user_id), env.case_id, filename="new-child.txt", raw=b"New contained bytes")
        child.parent_id = env.evidence_id
        db.commit()
    response = env.client.get(job["download_url"])
    assert response.status_code == 409
    assert response.json()["error_code"] == "EXPORT_FAMILY_CHANGED"


def test_quarantined_original_cannot_escape_through_native_export(env):
    with env.database.sessions() as db:
        db.get(Evidence, env.evidence_id).parser_state = "quarantined"
        db.commit()
    response = request_export(env, "zip")
    assert response.status_code == 409
    assert response.json()["error_code"] == "EVIDENCE_QUARANTINED"


def test_holds_release_is_authorized_audited_and_cannot_silently_reactivate(env):
    base = f"/api/v1/cases/{env.case_id}/holds"
    response = env.client.post(base, json={"name": "Synthetic preservation", "reason": "Attorney preservation request"})
    assert response.status_code == 201
    hold = response.json()
    assert hold["state"] == "active"
    released = env.client.post(f"{base}/{hold['id']}/release", json={"reason": "Authorized fictional release"})
    assert released.status_code == 200
    assert released.json()["state"] == "released"
    assert released.json()["released_by"] == env.user_id
    assert env.client.post(f"{base}/{hold['id']}/activate", json={"reason": "Do not rewrite history"}).status_code == 409
    with env.database.sessions() as db:
        assert verify_chain(db, env.tenant_id, env.case_id)["valid"]


def test_issue_links_cannot_attach_evidence_from_another_matter(env):
    base = f"/api/v1/cases/{env.case_id}/issues"
    response = env.client.post(base, json={"title": "Payment authorization", "description": "Synthetic allegation"})
    assert response.status_code == 201
    issue_id = response.json()["id"]
    denied = env.client.post(f"{base}/{issue_id}/evidence", json={"evidence_id": env.private_id, "side": "supports"})
    assert denied.status_code == 404
    for side in ("supports", "contradicts", "unclear"):
        linked = env.client.post(f"{base}/{issue_id}/evidence", json={"evidence_id": env.evidence_id, "side": side})
        assert linked.status_code == 201
    detail = env.client.get(f"{base}/{issue_id}").json()
    assert {item["side"] for item in detail["evidence"]} == {"supports", "contradicts", "unclear"}
    assert all(item["evidence_id"] == env.evidence_id for item in detail["evidence"])


def test_tasks_allow_only_authorized_matter_assignees_and_valid_states(env):
    base = f"/api/v1/cases/{env.case_id}/tasks"
    denied = env.client.post(base, json={"title": "Synthetic review", "assigned_to": "unknown-user"})
    assert denied.status_code == 404
    created = env.client.post(base, json={"title": "Synthetic review", "assigned_to": env.user_id})
    assert created.status_code == 201
    task_id = created.json()["id"]
    changed = env.client.patch(f"{base}/{task_id}", json={"state": "done", "assigned_to": None})
    assert changed.status_code == 200
    assert changed.json()["state"] == "done"
    assert changed.json()["assigned_to"] is None
    assert env.client.patch(f"{base}/{task_id}", json={"state": "invented"}).status_code == 422


def test_unimplemented_production_returns_truthful_unavailable_state(env):
    response = env.client.post(f"/api/v1/cases/{env.case_id}/productions", json={})
    assert response.status_code == 503
    assert response.json()["error_code"] == "PRODUCTION_UNAVAILABLE"
