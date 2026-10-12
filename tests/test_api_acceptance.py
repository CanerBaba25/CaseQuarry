"""Exercise real API workflows and confidentiality boundaries using synthetic evidence."""

import hashlib
import time
from pathlib import Path

import pytest
from casequarry.config import Settings
from casequarry.database import Database
from casequarry.ingestion import claim_import, run_batch
from casequarry.main import create_app
from casequarry.models import Evidence, ImportBatch, Member, User
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from .evidence_fixtures import eml_bytes, mbox_bytes, pdf_bytes, zip_bytes


class Session:
    def __init__(self, app):
        self.client = TestClient(app)
        self.csrf = ""

    def request(self, method, path, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        if self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        return self.client.request(method, "/api/v1" + path, headers=headers, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def login(self, email, password="Synthetic-test-password-42!"):
        response = self.post("/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, response.text
        self.csrf = response.json()["csrf_token"]


@pytest.fixture
def app(tmp_path, request):
    values = dict(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'acceptance.sqlite'}",
        storage_path=tmp_path / "objects",
        setup_token="acceptance-bootstrap-token",
        worker_mode="embedded",
        session_ttl_seconds=3600,
        allow_insecure_local_cookies=True,
        max_upload_bytes=4 * 1024 * 1024,
    )
    values.update(getattr(request, "param", {}))
    settings = Settings(**values)
    application = create_app(settings)
    application.state.test_storage_path = settings.storage_path
    with TestClient(application):
        yield application


@pytest.fixture
def owner(app):
    session = Session(app)
    response = session.post(
        "/setup",
        json={
            "token": "acceptance-bootstrap-token",
            "firm_name": "Synthetic Example Firm",
            "name": "Morgan Example",
            "email": "owner@example.test",
            "password": "Synthetic-test-password-42!",
        },
    )
    assert response.status_code in {200, 201}, response.text
    session.csrf = response.json()["csrf_token"]
    session.bootstrap_cookies = response.headers.get_list("set-cookie")
    yield session
    session.client.close()


def create_case(session, suffix="A"):
    response = session.post(
        "/cases", json={"matter_number": f"SYNTHETIC-{suffix}", "title": f"Fictional Matter {suffix}"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def create_reviewer(owner, app):
    response = owner.post(
        "/users",
        json={
            "email": "reviewer@example.test",
            "name": "Jordan Example",
            "password": "Synthetic-test-password-42!",
            "role": "reviewer",
        },
    )
    assert response.status_code == 201, response.text
    reviewer = Session(app)
    reviewer.login("reviewer@example.test")
    return response.json()["id"], reviewer


def import_files(session, case_id, files, **fields):
    response = session.post(f"/cases/{case_id}/imports", files=files, data=fields)
    assert response.status_code in {201, 202}, response.text
    batch_id = response.json()["batch_id"]
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        status = session.get(f"/cases/{case_id}/imports/{batch_id}")
        assert status.status_code == 200, status.text
        payload = status.json()
        if payload["state"] in {"completed", "partial", "failed", "cancelled"}:
            return payload
        time.sleep(0.025)
    pytest.fail(f"Import did not finish: {payload}")


def search(session, case_id, **changes):
    body = {"query": "", "page_size": 50, "sort": [{"field": "evidence_id", "order": "asc"}]}
    body.update(changes)
    response = session.post(f"/cases/{case_id}/search", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def imported_item(owner, case_id, content=None, filename="mail.eml"):
    raw = content or eml_bytes()
    batch = import_files(owner, case_id, [("files", (filename, raw, "application/octet-stream"))])
    assert batch["state"] == "completed", batch
    results = search(owner, case_id)
    return results["items"][0]["evidence_id"], raw


def test_authenticated_setup_is_one_time_and_mutations_require_csrf(app, owner):
    assert owner.get("/me").status_code == 200
    csrf_missing = owner.client.post(
        "/api/v1/cases", json={"matter_number": "FORBIDDEN", "title": "Missing CSRF"}
    )
    assert csrf_missing.status_code == 403
    repeated = owner.post(
        "/setup",
        json={
            "token": "acceptance-bootstrap-token",
            "firm_name": "Other Firm",
            "name": "Other Admin",
            "email": "other@example.test",
            "password": "Synthetic-test-password-42!",
        },
    )
    assert repeated.status_code in {403, 409}
    anonymous = Session(app)
    assert anonymous.get("/cases").status_code == 401
    cookie_headers = owner.client.cookies
    assert "cq_session" in cookie_headers
    assert "cq_csrf" in cookie_headers
    session_cookie = next(value for value in owner.bootstrap_cookies if value.startswith("cq_session="))
    assert "httponly" in session_cookie.lower()
    assert "samesite=" in session_cookie.lower()


def test_cross_case_ids_search_counts_originals_and_audit_are_not_disclosed(app, owner):
    case_a = create_case(owner, "A")
    case_b = create_case(owner, "B")
    private_id, _ = imported_item(owner, case_b)
    user_id, reviewer = create_reviewer(owner, app)
    membership = owner.post(f"/cases/{case_a}/members", json={"user_id": user_id, "role": "reviewer"})
    assert membership.status_code in {200, 201}, membership.text
    assert search(reviewer, case_a)["total_hits"] == 0
    assert reviewer.post(f"/cases/{case_b}/search", json={"query": ""}).status_code == 404
    for path in (
        f"/cases/{case_b}",
        f"/cases/{case_b}/stats",
        f"/cases/{case_b}/evidence/{private_id}",
        f"/cases/{case_b}/evidence/{private_id}/original",
        f"/cases/{case_b}/audit",
        f"/cases/{case_a}/evidence/{private_id}",
        f"/cases/{case_a}/evidence/{private_id}/original",
    ):
        assert reviewer.get(path).status_code == 404, path
    assert reviewer.post(
        f"/cases/{case_b}/exports",
        json={"format": "json", "confirmed": True, "reason": "Synthetic authorization check"},
    ).status_code == 404
    assert reviewer.post(
        "/users",
        json={
            "email": "attacker@example.test",
            "name": "Unauthorized Example",
            "password": "Synthetic-test-password-42!",
            "role": "reviewer",
        },
    ).status_code == 403


def test_original_bytes_hash_and_duplicate_occurrences_are_preserved(owner):
    case_id = create_case(owner)
    raw = eml_bytes()
    import_files(owner, case_id, [("files", ("source-one.eml", raw, "message/rfc822"))])
    import_files(owner, case_id, [("files", ("source-two.eml", raw, "message/rfc822"))])
    results = search(owner, case_id)
    assert results["total_hits"] == 2
    evidence_ids = {item["evidence_id"] for item in results["items"]}
    assert len(evidence_ids) == 2
    digest = hashlib.sha256(raw).hexdigest()
    for evidence_id in evidence_ids:
        detail = owner.get(f"/cases/{case_id}/evidence/{evidence_id}").json()
        assert detail["sha256"] == digest
        original = owner.get(f"/cases/{case_id}/evidence/{evidence_id}/original")
        assert original.status_code == 200
        assert original.content == raw
        verified = owner.post(f"/cases/{case_id}/evidence/{evidence_id}/verify")
        assert verified.status_code == 200
        assert verified.json()["valid"] is True


def test_attachment_family_and_pdf_citations_resolve_to_derived_pages(owner):
    case_id = create_case(owner)
    import_files(
        owner,
        case_id,
        [
            ("files", ("parent.eml", eml_bytes(attachment=True), "message/rfc822")),
            ("files", ("two-pages.pdf", pdf_bytes(), "application/pdf")),
        ],
    )
    results = search(owner, case_id)
    assert results["total_hits"] == 3
    parent = next(item for item in results["items"] if item["type"] == "email")
    family = owner.get(f"/cases/{case_id}/evidence/{parent['evidence_id']}/family")
    assert family.status_code == 200
    assert "invoice.txt" in family.text
    pdf = next(item for item in results["items"] if item["type"] == "pdf")
    detail = owner.get(f"/cases/{case_id}/evidence/{pdf['evidence_id']}").json()
    spans = detail["spans"]
    assert {span["page"] for span in spans} == {1, 2}
    assert all(span["artifact_id"] and span["text_hash"] for span in spans)


def test_boolean_phrase_field_and_date_search_find_expected_evidence(owner):
    case_id = create_case(owner)
    import_files(
        owner,
        case_id,
        [
            ("files", ("approved.eml", eml_bytes(1), "message/rfc822")),
            ("files", ("rejected.eml", eml_bytes(2, sender="carol@example.test", body="Payment rejected."), "message/rfc822")),
            ("files", ("other.eml", eml_bytes(3, subject="Shipping", body="Shipment delayed."), "message/rfc822")),
        ],
    )
    assert search(owner, case_id, query='"payment approved"')["total_hits"] == 1
    assert search(owner, case_id, query='(approved OR rejected) AND NOT delayed')["total_hits"] == 2
    assert search(owner, case_id, query="from:alice@example.test AND after:2025-01-01 before:2025-01-03")["total_hits"] == 1
    assert search(owner, case_id, query='subject:"Shipping"')["total_hits"] == 1
    invalid = owner.post(f"/cases/{case_id}/search", json={"query": "(approved AND"})
    assert invalid.status_code == 422
    assert invalid.json()["error_code"]


def test_group_counts_cover_all_results_and_cursors_are_stable(owner):
    case_id = create_case(owner)
    count = 19
    files = [
        ("files", (f"{number:03}.eml", eml_bytes(number), "message/rfc822"))
        for number in range(1, count + 1)
    ]
    import_files(owner, case_id, files)
    first = search(owner, case_id, page_size=4, group_by="sender")
    assert first["total_hits"] == count
    assert sum(group["count"] for group in first["groups"]) == count
    seen = []
    page = first
    while True:
        seen.extend(item["evidence_id"] for item in page["items"])
        if not page["next_cursor"]:
            break
        page = search(owner, case_id, page_size=4, group_by="sender", cursor=page["next_cursor"])
    assert len(seen) == len(set(seen)) == count
    repeated = search(owner, case_id, page_size=4, group_by="sender")
    assert [item["evidence_id"] for item in repeated["items"]] == seen[:4]
    oversized = owner.post(f"/cases/{case_id}/search", json={"query": "", "page_size": 201})
    assert oversized.status_code == 422


def test_ai_without_provider_returns_actionable_unavailable_error(owner):
    case_id = create_case(owner)
    evidence_id, _ = imported_item(owner, case_id)
    response = owner.post(
        f"/cases/{case_id}/ai/ask", json={"question": "Was the payment approved?", "evidence_ids": [evidence_id]}
    )
    assert response.status_code == 503
    assert response.json()["error_code"]
    assert "local" in response.text.lower()
    assert search(owner, case_id, query="approved")["total_hits"] == 1


@pytest.mark.parametrize("app", [{"session_ttl_seconds": 1}], indirect=True)
def test_expired_sessions_cannot_access_matters(app, owner):
    create_case(owner)
    time.sleep(1.1)
    assert owner.get("/me").status_code == 401
    assert owner.get("/cases").status_code == 401


def test_invalid_logins_are_throttled_without_disclosing_account_existence(app, owner):
    visitor = Session(app)
    last = None
    for _attempt in range(12):
        last = visitor.post(
            "/auth/login", json={"email": "absent@example.test", "password": "Invalid-test-password-42!"}
        )
        assert last.status_code in {401, 429}, last.text
        if last.status_code == 429:
            break
    assert last.status_code == 429, "Repeated invalid login attempts must be rate limited"


def test_original_tampering_is_detected_and_download_is_blocked(owner, app):
    case_id = create_case(owner)
    evidence_id, raw = imported_item(owner, case_id)
    storage_root = Path(app.state.test_storage_path)
    original_path = next(path for path in storage_root.rglob("*") if path.is_file() and path.read_bytes() == raw)
    original_path.write_bytes(b"Changed bytes cannot be represented as the preserved original")
    verification = owner.post(f"/cases/{case_id}/evidence/{evidence_id}/verify")
    assert verification.status_code in {200, 409}, verification.text
    assert verification.json()["valid"] is False
    download = owner.get(f"/cases/{case_id}/evidence/{evidence_id}/original")
    assert download.status_code == 409
    assert download.json()["error_code"]


def test_human_review_uses_optimistic_versions_and_blocks_privileged_export(owner):
    case_id = create_case(owner)
    evidence_id, _ = imported_item(owner, case_id)
    first = owner.post(
        f"/cases/{case_id}/evidence/{evidence_id}/reviews",
        json={"expected_version": 0, "review_status": "responsive", "note": "Synthetic acceptance review"},
    )
    assert first.status_code == 200, first.text
    stale = owner.post(
        f"/cases/{case_id}/evidence/{evidence_id}/reviews",
        json={"expected_version": 0, "review_status": "non-responsive"},
    )
    assert stale.status_code == 409
    privileged = owner.post(
        f"/cases/{case_id}/evidence/{evidence_id}/reviews",
        json={
            "expected_version": 1,
            "privilege_status": "confirmed",
            "note": "Synthetic attorney privilege determination",
        },
    )
    assert privileged.status_code == 200, privileged.text
    blocked = owner.post(
        f"/cases/{case_id}/exports",
        json={"format": "zip", "evidence_ids": [evidence_id], "confirmed": True, "reason": "Acceptance check"},
    )
    assert blocked.status_code == 409, blocked.text


def test_audit_chain_is_attributed_and_verifiable(owner):
    case_id = create_case(owner)
    evidence_id, _ = imported_item(owner, case_id)
    owner.post(f"/cases/{case_id}/evidence/{evidence_id}/verify")
    response = owner.get(f"/cases/{case_id}/audit")
    assert response.status_code == 200
    assert "actor_id" in response.text
    verified = owner.post(f"/cases/{case_id}/audit/verify")
    assert verified.status_code == 200, verified.text
    assert verified.json()["valid"] is True


def test_html_email_preserves_original_but_preview_has_no_executable_content(owner):
    case_id = create_case(owner)
    evidence_id, raw = imported_item(owner, case_id, content=eml_bytes(html=True))
    detail = owner.get(f"/cases/{case_id}/evidence/{evidence_id}").json()
    rendered_text = detail["text"]
    assert "Project Atlas" in rendered_text
    assert "<script" not in rendered_text.lower()
    assert "<img" not in rendered_text.lower()
    assert "javascript:" not in rendered_text.lower()
    assert "<script" in raw.decode()
    assert owner.get(f"/cases/{case_id}/evidence/{evidence_id}/original").content == raw


def test_unsupported_file_keeps_original_and_records_actionable_failure(owner, app):
    case_id = create_case(owner)
    raw = b"SYNTHETIC proprietary file; no supported text extraction"
    batch = import_files(owner, case_id, [("files", ("unsupported.xyz", raw, "application/octet-stream"))])
    assert batch["state"] in {"partial", "failed"}, batch
    errors = owner.get(f"/cases/{case_id}/imports/{batch['id']}/errors")
    assert errors.status_code == 200
    assert errors.json()
    assert "unsupported" in errors.text.lower()
    root = Path(app.state.test_storage_path)
    assert any(path.read_bytes() == raw for path in root.rglob("*") if path.is_file())


def test_mbox_escaped_from_lines_do_not_create_phantom_messages(owner):
    case_id = create_case(owner)
    batch = import_files(owner, case_id, [("files", ("mailbox.mbox", mbox_bytes(), "application/mbox"))])
    assert batch["state"] == "completed", batch
    results = search(owner, case_id, filters={"item_types": ["email"]})
    assert results["total_hits"] == 2
    assert search(owner, case_id, query='"first mailbox record"')["total_hits"] == 1
    assert search(owner, case_id, query='"second mailbox record"')["total_hits"] == 1


@pytest.mark.parametrize("app", [{"worker_mode": "disabled"}], indirect=True)
def test_import_idempotency_reuses_batch_without_extra_occurrences(app, owner):
    case_id = create_case(owner)
    raw = eml_bytes()
    responses = [
        owner.post(
            f"/cases/{case_id}/imports",
            files=[("files", ("mail.eml", raw, "message/rfc822"))],
            headers={"Idempotency-Key": "synthetic-import-request"},
        )
        for _ in range(2)
    ]
    assert all(response.status_code == 202 for response in responses)
    ids = {response.json()["batch_id"] for response in responses}
    assert len(ids) == 1
    assert claim_import(app.state.db) == next(iter(ids))
    run_batch(app.state.db, app.state.settings, app.state.storage, next(iter(ids)))
    assert search(owner, case_id)["total_hits"] == 1


@pytest.mark.parametrize("app", [{"worker_mode": "disabled"}], indirect=True)
@pytest.mark.parametrize("revocation", ["membership", "disabled-account"])
def test_import_worker_rechecks_permission_after_each_committed_record(app, owner, monkeypatch, revocation):
    from casequarry import ingestion

    case_id = create_case(owner)
    response = owner.post(
        f"/cases/{case_id}/imports",
        files=[("files", (f"{number}.eml", eml_bytes(number), "message/rfc822")) for number in (1, 2)],
    )
    assert response.status_code == 202
    batch_id = response.json()["batch_id"]
    owner_id = owner.get("/me").json()["id"]
    ingest = ingestion.ingest_tree
    changed = False

    def revoke_after_first(*args, **kwargs):
        nonlocal changed
        result = ingest(*args, **kwargs)
        if not changed:
            changed = True
            with app.state.db.sessions() as db:
                if revocation == "membership":
                    db.scalar(select(Member).where(Member.case_id == case_id, Member.user_id == owner_id)).role = "read_only"
                else:
                    db.get(User, owner_id).active = False
                db.commit()
        return result

    monkeypatch.setattr(ingestion, "ingest_tree", revoke_after_first)
    assert claim_import(app.state.db) == batch_id
    run_batch(app.state.db, app.state.settings, app.state.storage, batch_id)
    with app.state.db.sessions() as db:
        batch = db.get(ImportBatch, batch_id)
        assert batch.state == "failed"
        assert db.scalar(select(func.count()).select_from(Evidence).where(Evidence.case_id == case_id)) == 1
        assert any(error["code"] == "WORKER_PERMISSION_REVOKED" for error in batch.errors)


@pytest.mark.parametrize("app", [{"worker_mode": "disabled"}], indirect=True)
def test_paused_import_resumes_from_durable_checkpoint_in_restarted_worker(app, owner, monkeypatch):
    from casequarry import ingestion

    case_id = create_case(owner)
    response = owner.post(
        f"/cases/{case_id}/imports",
        files=[("files", (f"{number}.eml", eml_bytes(number), "message/rfc822")) for number in (1, 2)],
    )
    batch_id = response.json()["batch_id"]
    ingest = ingestion.ingest_tree
    paused = False

    def pause_after_first(*args, **kwargs):
        nonlocal paused
        result = ingest(*args, **kwargs)
        if not paused:
            paused = True
            db, batch = args[0], args[3]
            batch.state = "paused"
            db.commit()
        return result

    monkeypatch.setattr(ingestion, "ingest_tree", pause_after_first)
    assert claim_import(app.state.db) == batch_id
    run_batch(app.state.db, app.state.settings, app.state.storage, batch_id)
    status = owner.get(f"/cases/{case_id}/imports/{batch_id}").json()
    assert status["state"] == "paused"
    assert status["checkpoint"]["file_index"] == 1
    assert search(owner, case_id)["total_hits"] == 1
    monkeypatch.setattr(ingestion, "ingest_tree", ingest)
    resumed = owner.post(f"/cases/{case_id}/imports/{batch_id}/resume")
    assert resumed.status_code == 200
    restarted = Database(app.state.settings)
    try:
        assert claim_import(restarted) == batch_id
        run_batch(restarted, app.state.settings, app.state.storage, batch_id)
    finally:
        restarted.dispose()
    status = owner.get(f"/cases/{case_id}/imports/{batch_id}").json()
    assert status["state"] == "completed"
    assert status["counts"]["accepted"] == 2
    assert search(owner, case_id)["total_hits"] == 2


@pytest.mark.parametrize("app", [{"worker_mode": "disabled"}], indirect=True)
def test_resumable_upload_accepts_out_of_order_parts_hashes_and_idempotent_completion(app, owner):
    case_id = create_case(owner)
    raw = eml_bytes(body="Synthetic chunked evidence. " + "x" * 1600)
    started = owner.post(
        f"/cases/{case_id}/upload-sessions",
        json={"filename": "chunked.eml", "byte_size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "part_size": 1024},
    )
    assert started.status_code == 201, started.text
    upload = started.json()
    assert upload["part_count"] >= 2
    base = f"/cases/{case_id}/upload-sessions/{upload['id']}"
    chunk = raw[:1024]
    wrong_hash = owner.request("PUT", base + "/parts/0", content=chunk, headers={"X-Chunk-SHA256": "0" * 64})
    assert wrong_hash.status_code == 422
    assert owner.post(base + "/complete").status_code == 409
    for number in reversed(range(upload["part_count"])):
        chunk = raw[number * 1024:(number + 1) * 1024]
        accepted = owner.request("PUT", f"{base}/parts/{number}", content=chunk, headers={"X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest()})
        assert accepted.status_code == 200, accepted.text
    repeated = owner.request("PUT", base + "/parts/0", content=raw[:1024])
    assert repeated.status_code == 200
    completed = owner.post(base + "/complete")
    assert completed.status_code == 202, completed.text
    batch_id = completed.json()["batch_id"]
    assert owner.post(base + "/complete").json()["batch_id"] == batch_id
    assert claim_import(app.state.db) == batch_id
    run_batch(app.state.db, app.state.settings, app.state.storage, batch_id)
    results = search(owner, case_id)
    assert results["total_hits"] == 1
    evidence_id = results["items"][0]["evidence_id"]
    assert owner.get(f"/cases/{case_id}/evidence/{evidence_id}/original").content == raw


def test_active_legal_hold_blocks_archive_until_authorized_release(owner):
    case_id = create_case(owner)
    held = owner.post(f"/cases/{case_id}/holds", json={"name": "Synthetic preservation", "reason": "Attorney preservation instruction"})
    assert held.status_code == 201
    hold_id = held.json()["id"]
    archived = owner.post(f"/cases/{case_id}/archive", json={"reason": "Synthetic closure attempt"})
    assert archived.status_code == 409
    released = owner.post(f"/cases/{case_id}/holds/{hold_id}/release", json={"reason": "Authorized fictional release"})
    assert released.status_code == 200
    archived = owner.post(f"/cases/{case_id}/archive", json={"reason": "Synthetic matter closure"})
    assert archived.status_code == 200


@pytest.mark.parametrize(
    "raw",
    [
        zip_bytes({"../../escaped.txt": b"Do not write outside protected storage"}),
        zip_bytes({"/absolute.txt": b"Absolute archive entry"}),
        zip_bytes({}, symlink="link.txt"),
        zip_bytes({"expansion.txt": b"x" * (2 * 1024 * 1024)}),
    ],
    ids=["traversal", "absolute-path", "symlink", "expansion-ratio"],
)
def test_hostile_archives_are_retained_and_reported_without_unsafe_extraction(owner, app, raw):
    case_id = create_case(owner)
    batch = import_files(owner, case_id, [("files", ("hostile.zip", raw, "application/zip"))])
    assert batch["state"] in {"partial", "failed"}, batch
    errors = owner.get(f"/cases/{case_id}/imports/{batch['id']}/errors")
    assert errors.status_code == 200
    assert errors.json()
    storage_root = Path(app.state.test_storage_path)
    assert not (storage_root.parent / "escaped.txt").exists()
    assert any(path.read_bytes() == raw for path in storage_root.rglob("*") if path.is_file())
