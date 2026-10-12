"""Regression checks for confidentiality boundaries beneath API route wiring."""

from datetime import timedelta

import pytest
from casequarry.config import Settings
from casequarry.database import Database
from casequarry.models import Case, Member, Tenant, User, now
from casequarry.security import PASSWORDS, authorize_case, create_session, current_actor, password_valid
from fastapi import HTTPException
from starlette.requests import Request


@pytest.fixture
def identities(tmp_path):
    database = Database(Settings(database_url=f"sqlite:///{tmp_path / 'security.sqlite'}"))
    database.initialize()
    with database.sessions() as db:
        tenants = [Tenant(name="Synthetic firm A"), Tenant(name="Synthetic firm B")]
        db.add_all(tenants)
        db.flush()
        users = [
            User(tenant_id=tenant.id, email=f"user-{number}@example.test", name="Synthetic user", password_hash="unused", role="firm_admin")
            for number, tenant in enumerate(tenants)
        ]
        db.add_all(users)
        db.flush()
        cases = [
            Case(tenant_id=tenant.id, matter_number=f"MATTER-{number}", title="Synthetic private matter", created_by=user.id)
            for number, (tenant, user) in enumerate(zip(tenants, users, strict=True))
        ]
        db.add_all(cases)
        db.flush()
        yield db, users, cases
    database.dispose()


def request(*, method="GET", token=None, csrf=None, bearer=False):
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()) if bearer else (b"cookie", f"cq_session={token}".encode()))
    if csrf:
        headers.append((b"x-csrf-token", csrf.encode()))
    return Request({"type": "http", "method": method, "headers": headers})


def assert_denied(code, callback):
    with pytest.raises(HTTPException) as error:
        callback()
    assert error.value.status_code == code
    assert error.value.detail["error_code"]


def test_firm_administrator_has_no_implicit_matter_content_access(identities):
    db, users, cases = identities
    assert_denied(404, lambda: authorize_case(db, users[0], cases[0].id))


def test_forged_membership_does_not_cross_tenant_boundary(identities):
    db, users, cases = identities
    db.add(Member(tenant_id=users[0].tenant_id, case_id=cases[1].id, user_id=users[0].id, role="matter_lead"))
    db.flush()
    assert_denied(404, lambda: authorize_case(db, users[0], cases[1].id))


def test_grant_with_wrong_tenant_is_ignored(identities):
    db, users, cases = identities
    db.add(Member(tenant_id=users[1].tenant_id, case_id=cases[0].id, user_id=users[0].id, role="matter_lead"))
    db.flush()
    assert_denied(404, lambda: authorize_case(db, users[0], cases[0].id))


def test_unknown_permission_denies_and_archived_matter_blocks_mutation(identities):
    db, users, cases = identities
    db.add(Member(tenant_id=users[0].tenant_id, case_id=cases[0].id, user_id=users[0].id, role="matter_lead"))
    db.flush()
    assert_denied(403, lambda: authorize_case(db, users[0], cases[0].id, "unknown-permission"))
    cases[0].archived_at = now()
    db.flush()
    assert authorize_case(db, users[0], cases[0].id, "view")[0].id == cases[0].id
    assert_denied(409, lambda: authorize_case(db, users[0], cases[0].id, "import"))
    assert_denied(409, lambda: authorize_case(db, users[0], cases[0].id, "review"))


def test_cookie_session_mutation_requires_matching_csrf_and_bearer_is_authenticated(identities):
    db, users, _cases = identities
    login, token, csrf = create_session(db, users[0], 3600)
    assert login.token_hash != token
    assert login.csrf_hash != csrf
    assert current_actor(request(token=token), db).user.id == users[0].id
    assert_denied(403, lambda: current_actor(request(method="POST", token=token), db))
    assert_denied(403, lambda: current_actor(request(method="POST", token=token, csrf="forged-csrf"), db))
    assert current_actor(request(method="POST", token=token, csrf=csrf), db).user.id == users[0].id
    assert current_actor(request(method="POST", token=token, bearer=True), db).bearer is True
    assert_denied(401, lambda: current_actor(request(token="invented-session", bearer=True), db))


@pytest.mark.parametrize("condition", ["revoked", "expired", "disabled"])
def test_revoked_expired_or_disabled_identity_cannot_authenticate(identities, condition):
    db, users, _cases = identities
    login, token, _csrf = create_session(db, users[0], 3600)
    if condition == "revoked":
        login.revoked = True
    elif condition == "expired":
        login.expires_at = now() - timedelta(seconds=1)
    else:
        users[0].active = False
    db.flush()
    assert_denied(401, lambda: current_actor(request(token=token), db))


def test_password_validation_handles_wrong_password_and_corrupt_hash():
    encoded = PASSWORDS.hash("Synthetic-password-42!")
    assert encoded.startswith("$argon2id$")
    assert password_valid("Synthetic-password-42!", encoded)
    assert not password_valid("Wrong-password", encoded)
    assert not password_valid("Synthetic-password-42!", "not-a-valid-password-hash")
