from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.app import app


def _client(email, role, email_verified=True):
    set_verifier(lambda token: {"uid": "u", "email": email, "role": role,
                                "email_verified": email_verified})
    return TestClient(app)


def test_me_default_admin_email_is_admin_without_claim():
    # tim is a default-admin (settings.DEFAULT_ADMINS) with a VERIFIED email, no assigned claim
    c = _client("tim@perkinsroofing.net", "")
    r = c.get("/me", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200 and r.json()["role"] == "admin"


def test_me_default_admin_email_NOT_admin_when_unverified():
    # security: an UNVERIFIED default-admin email must not be elevated (self-registration guard)
    c = _client("tim@perkinsroofing.net", "", email_verified=False)
    r = c.get("/me", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200 and r.json()["role"] is None


def test_me_regular_user_keeps_claim_role():
    c = _client("stranger@example.com", "sales")
    assert c.get("/me", headers={"Authorization": "Bearer x"}).json()["role"] == "sales"


def test_me_no_role_user_returns_null():
    c = _client("stranger@example.com", "")
    assert c.get("/me", headers={"Authorization": "Bearer x"}).json()["role"] is None


def test_me_requires_token():
    c = _client("stranger@example.com", "")
    assert c.get("/me").status_code == 401
