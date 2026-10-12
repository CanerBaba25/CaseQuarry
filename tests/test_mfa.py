import pyotp
import pytest
from casequarry.config import Settings
from casequarry.main import create_app
from casequarry.models import User
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.fixture
def mfa_client(tmp_path):
    application = create_app(Settings(environment="test", storage_path=tmp_path / "data", database_url=f"sqlite:///{tmp_path / 'mfa.sqlite'}", setup_token="synthetic-mfa-setup", worker_mode="disabled"))
    with TestClient(application) as client:
        setup = client.post("/api/v1/setup", json={"token": "synthetic-mfa-setup", "firm_name": "Synthetic MFA Firm", "name": "Synthetic Owner", "email": "mfa@example.test", "password": "Synthetic-mfa-password-42!"})
        assert setup.status_code == 201
        client.headers["X-CSRF-Token"] = setup.json()["csrf_token"]
        yield application, client


def test_mfa_encrypted_secret_and_login_second_factor(mfa_client):
    application, client = mfa_client
    response = client.post("/api/v1/auth/mfa/enroll", json={"password": "Synthetic-mfa-password-42!"})
    assert response.status_code == 200
    secret = response.json()["secret"]
    with application.state.db.sessions() as db:
        user = db.scalar(select(User).where(User.email == "mfa@example.test"))
        assert user.mfa_secret != secret
        assert secret not in user.mfa_secret
        assert not user.mfa_enabled
    code = pyotp.TOTP(secret).now()
    assert client.post("/api/v1/auth/mfa/confirm", json={"code": code}).json()["enabled"]
    assert client.post("/api/v1/auth/logout").status_code == 200
    payload = {"email": "mfa@example.test", "password": "Synthetic-mfa-password-42!"}
    assert client.post("/api/v1/auth/login", json=payload).status_code == 401
    login = client.post("/api/v1/auth/login", json={**payload, "totp_code": code})
    assert login.status_code == 200
    client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    assert client.post("/api/v1/auth/mfa/disable", json={"password": payload["password"], "code": code}).json()["enabled"] is False


def test_mfa_enrollment_password_and_csrf_guards(mfa_client):
    _, client = mfa_client
    assert client.post("/api/v1/auth/mfa/enroll", json={"password": "incorrect"}).status_code == 401
    assert client.post("/api/v1/auth/mfa/confirm", json={"code": "123456"}).status_code == 409
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.post("/api/v1/auth/mfa/enroll", json={"password": "Synthetic-mfa-password-42!"}).status_code == 403
    client.headers["X-CSRF-Token"] = csrf


def test_xlsx_parser_accepts_extensionless_protected_object(tmp_path):
    from casequarry.parsers import parse_document
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.append(["Synthetic invoice", "INV-2048", 1500])
    path = tmp_path / "content-addressed-sha256"
    workbook.save(path)
    parsed = parse_document(path, "invoice.xlsx", Settings())
    assert parsed.state == "indexed"
    assert "INV-2048" in parsed.text
    assert "1500" in parsed.text
