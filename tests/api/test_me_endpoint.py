from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.app import app


def _client(email, role):
    set_verifier(lambda token: {"uid": "u", "email": email, "role": role})
    return TestClient(app)


def test_me_default_admin_email_is_admin_without_claim():
    # tim is a default-admin (settings.DEFAULT_ADMINS) with no assigned claim
    c = _client("tim@perkinsroofing.net", "")
    r = c.get("/me", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200 and r.json()["role"] == "admin"


def test_me_regular_user_keeps_claim_role():
    c = _client("stranger@example.com", "sales")
    assert c.get("/me", headers={"Authorization": "Bearer x"}).json()["role"] == "sales"


def test_me_no_role_user_returns_null():
    c = _client("stranger@example.com", "")
    assert c.get("/me", headers={"Authorization": "Bearer x"}).json()["role"] is None


def test_me_requires_token():
    c = _client("stranger@example.com", "")
    assert c.get("/me").status_code == 401
