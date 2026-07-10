"""Tests for email feature additions:
- POST /email/templates (create-template — auth already tested in test_email_proof)
- GET/PUT /me/signature
- PUT /admin/users/signature
- GET /admin/users includes signature field
- POST /email/send prepends EMAIL_HTML_HEADER from PlatformConfig
- EMAIL_HTML_HEADER in EDITABLE_KEYS
- POST /email/send uses claims email for From (sender identity)
- POST /email/preview returns branded HTML wrapper
- _claims_display_name / _sender_from_address helpers
"""
import types
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from api import app as appmod
from api.auth import set_verifier
from api.routes.users import router as users_router, me_router
from api.routes.email import (
    router as email_router,
    _claims_display_name,
    _sender_from_address,
)
from api.routes.config import EDITABLE_KEYS
from app.models import init_db, SessionLocal, UserSetting, PlatformConfig

# Mount routers idempotently
if not any(getattr(r, "path", None) == "/admin/users" for r in appmod.app.routes):
    appmod.app.include_router(users_router)
if not any(getattr(r, "path", None) == "/me" for r in appmod.app.routes):
    appmod.app.include_router(me_router)
if not any(getattr(r, "path", None) == "/email/templates" for r in appmod.app.routes):
    appmod.app.include_router(email_router)


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()
    # Clean up UserSetting and PlatformConfig rows between tests
    with SessionLocal() as db:
        db.query(UserSetting).delete()
        db.query(PlatformConfig).filter(PlatformConfig.key == "EMAIL_HTML_HEADER").delete()
        db.commit()


@pytest.fixture()
def admin_client():
    set_verifier(lambda t: {"uid": "u1", "email": "admin@test.com", "role": "admin"})
    return TestClient(appmod.app)


@pytest.fixture()
def user_client():
    set_verifier(lambda t: {"uid": "u2", "email": "alice@test.com", "role": "sales"})
    return TestClient(appmod.app)


@pytest.fixture()
def anon_client():
    set_verifier(lambda t: {})
    return TestClient(appmod.app)


def _make_user(uid, email, role=None, display_name=None):
    u = types.SimpleNamespace()
    u.uid = uid
    u.email = email
    u.display_name = display_name
    u.custom_claims = {"role": role} if role else {}
    return u


def _make_list_page(users):
    page = types.SimpleNamespace()
    page.iterate_all = lambda: iter(users)
    return page


# ---------------------------------------------------------------------------
# /me/signature — GET
# ---------------------------------------------------------------------------

def test_get_my_signature_empty(user_client):
    r = user_client.get("/me/signature", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    body = r.json()
    assert body["signature"] is None
    assert "alice@test.com" in body["email"]


def test_get_my_signature_after_set(user_client):
    # Seed directly
    with SessionLocal() as db:
        db.add(UserSetting(email="alice@test.com", signature="<p>Alice</p>"))
        db.commit()
    r = user_client.get("/me/signature", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json()["signature"] == "<p>Alice</p>"


def test_get_my_signature_unauthenticated(anon_client):
    # No auth header — must still get a response (current_claims allows no token gracefully)
    # The endpoint uses current_claims (not require_role), so it returns 200 with empty email.
    r = TestClient(appmod.app).get("/me/signature")
    assert r.status_code in (200, 401)


# ---------------------------------------------------------------------------
# /me/signature — PUT
# ---------------------------------------------------------------------------

def test_put_my_signature(user_client):
    r = user_client.put(
        "/me/signature",
        json={"signature": "<p>Best regards, Alice</p>"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["signature"] == "<p>Best regards, Alice</p>"
    assert "alice@test.com" in body["email"]


def test_put_my_signature_persists(user_client):
    user_client.put(
        "/me/signature",
        json={"signature": "<p>My sig</p>"},
        headers={"Authorization": "Bearer x"},
    )
    r = user_client.get("/me/signature", headers={"Authorization": "Bearer x"})
    assert r.json()["signature"] == "<p>My sig</p>"


def test_put_my_signature_update(user_client):
    user_client.put("/me/signature", json={"signature": "<p>v1</p>"}, headers={"Authorization": "Bearer x"})
    user_client.put("/me/signature", json={"signature": "<p>v2</p>"}, headers={"Authorization": "Bearer x"})
    r = user_client.get("/me/signature", headers={"Authorization": "Bearer x"})
    assert r.json()["signature"] == "<p>v2</p>"


def test_put_my_signature_clear(user_client):
    user_client.put("/me/signature", json={"signature": "<p>old</p>"}, headers={"Authorization": "Bearer x"})
    r = user_client.put("/me/signature", json={"signature": None}, headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json()["signature"] is None


# ---------------------------------------------------------------------------
# PUT /admin/users/signature
# ---------------------------------------------------------------------------

def test_admin_set_user_signature(admin_client):
    r = admin_client.put(
        "/admin/users/signature",
        json={"email": "alice@test.com", "signature": "<p>Admin-set sig</p>"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["signature"] == "<p>Admin-set sig</p>"
    assert body["email"] == "alice@test.com"


def test_admin_set_user_signature_persists(admin_client):
    admin_client.put(
        "/admin/users/signature",
        json={"email": "bob@test.com", "signature": "<p>Bob sig</p>"},
        headers={"Authorization": "Bearer x"},
    )
    with SessionLocal() as db:
        row = db.get(UserSetting, "bob@test.com")
    assert row is not None
    assert row.signature == "<p>Bob sig</p>"


def test_admin_set_user_signature_clear(admin_client):
    admin_client.put(
        "/admin/users/signature",
        json={"email": "alice@test.com", "signature": "<p>sig</p>"},
        headers={"Authorization": "Bearer x"},
    )
    r = admin_client.put(
        "/admin/users/signature",
        json={"email": "alice@test.com", "signature": None},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    assert r.json()["signature"] is None


def test_admin_set_signature_requires_manage_users(user_client):
    r = user_client.put(
        "/admin/users/signature",
        json={"email": "alice@test.com", "signature": "<p>x</p>"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET /admin/users includes signature field
# ---------------------------------------------------------------------------

def test_list_users_includes_signature(admin_client, monkeypatch):
    fake_users = [_make_user("uid1", "alice@test.com", "sales")]

    import api.routes.users as users_mod
    from app.config import settings
    monkeypatch.setattr(settings, "DEFAULT_ADMINS", frozenset())
    monkeypatch.setattr(
        users_mod,
        "_firebase_auth",
        lambda: types.SimpleNamespace(
            list_users=lambda max_results=200: _make_list_page(fake_users),
        ),
    )

    # Seed a signature
    with SessionLocal() as db:
        db.add(UserSetting(email="alice@test.com", signature="<p>Alice sig</p>"))
        db.commit()

    r = admin_client.get("/admin/users", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert "signature" in body[0]
    assert body[0]["signature"] == "<p>Alice sig</p>"


def test_list_users_signature_none_when_unset(admin_client, monkeypatch):
    fake_users = [_make_user("uid2", "bob@test.com", "admin")]

    import api.routes.users as users_mod
    from app.config import settings
    monkeypatch.setattr(settings, "DEFAULT_ADMINS", frozenset())
    monkeypatch.setattr(
        users_mod,
        "_firebase_auth",
        lambda: types.SimpleNamespace(
            list_users=lambda max_results=200: _make_list_page(fake_users),
        ),
    )

    r = admin_client.get("/admin/users", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json()[0]["signature"] is None


# ---------------------------------------------------------------------------
# POST /email/templates (create-template)
# ---------------------------------------------------------------------------

def test_create_template_admin(admin_client):
    r = admin_client.post(
        "/email/templates",
        json={"name": "Test Tpl", "subject": "Hello", "body": "<p>Hi</p>"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Test Tpl"
    assert body["subject"] == "Hello"
    assert body["body"] == "<p>Hi</p>"
    assert body["created_by"] == "admin@test.com"


def test_create_template_sales_allowed(user_client):
    # sales role has manage_templates permission in the authz matrix
    r = user_client.post(
        "/email/templates",
        json={"name": "T", "subject": "S", "body": "B"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 201


def test_created_template_appears_in_list(admin_client, user_client):
    admin_client.post(
        "/email/templates",
        json={"name": "My Tpl", "subject": "Subj", "body": "<b>body</b>"},
        headers={"Authorization": "Bearer x"},
    )
    r = user_client.get("/email/templates", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    names = [t["name"] for t in r.json()]
    assert "My Tpl" in names


# ---------------------------------------------------------------------------
# EMAIL_HTML_HEADER in EDITABLE_KEYS
# ---------------------------------------------------------------------------

def test_email_html_header_in_editable_keys():
    assert "EMAIL_HTML_HEADER" in EDITABLE_KEYS


# ---------------------------------------------------------------------------
# POST /email/send prepends EMAIL_HTML_HEADER
# ---------------------------------------------------------------------------

def _mock_resend_send(*, from_name, from_email, reply_to, to, subject, html):
    # Store call args in a mutable container for assertions
    _mock_resend_send.last_call = {
        "from_name": from_name,
        "from_email": from_email,
        "reply_to": reply_to,
        "to": to,
        "subject": subject,
        "html": html,
    }
    return "msg_test_id"


def test_send_email_prepends_header(admin_client):
    # Seed a header in PlatformConfig
    with SessionLocal() as db:
        db.add(PlatformConfig(key="EMAIL_HTML_HEADER", value="<header>BRAND</header>"))
        db.commit()

    _mock_resend_send.last_call = {}
    with patch("api.routes.email.resend_adapter.send", side_effect=_mock_resend_send):
        r = admin_client.post(
            "/email/send",
            json={"to": "recipient@example.com", "subject": "Hello", "html": "<p>body</p>"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200
    assert r.json()["id"] == "msg_test_id"
    sent_html = _mock_resend_send.last_call["html"]
    # wrap_email produces a full HTML doc; the header and body must both be present
    assert "<header>BRAND</header>" in sent_html
    assert "<p>body</p>" in sent_html
    assert "<!DOCTYPE html>" in sent_html


def test_send_email_no_header_when_unset(admin_client):
    # No PlatformConfig row, no env — wrap_email uses fallback company-name header
    _mock_resend_send.last_call = {}
    with patch("api.routes.email.resend_adapter.send", side_effect=_mock_resend_send):
        r = admin_client.post(
            "/email/send",
            json={"to": "recipient@example.com", "subject": "Hi", "html": "<p>clean</p>"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200
    sent_html = _mock_resend_send.last_call["html"]
    # Body fragment must be present inside the branded wrapper
    assert "<p>clean</p>" in sent_html
    assert "<!DOCTYPE html>" in sent_html


def test_send_email_header_env_fallback(admin_client, monkeypatch):
    # No DB row but EMAIL_HTML_HEADER env is set
    monkeypatch.setattr("app.config.settings.EMAIL_HTML_HEADER", "<div>ENV HEADER</div>")
    _mock_resend_send.last_call = {}
    with patch("api.routes.email.resend_adapter.send", side_effect=_mock_resend_send):
        r = admin_client.post(
            "/email/send",
            json={"to": "r@example.com", "subject": "S", "html": "<p>body</p>"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200
    sent_html = _mock_resend_send.last_call["html"]
    assert "<div>ENV HEADER</div>" in sent_html
    assert "<p>body</p>" in sent_html
    assert "<!DOCTYPE html>" in sent_html


# ---------------------------------------------------------------------------
# _claims_display_name — pure helper unit tests
# ---------------------------------------------------------------------------

class TestClaimsDisplayName:
    def test_uses_name_claim_when_present(self):
        assert _claims_display_name({"name": "Jane Smith", "email": "jane@example.com"}) == "Jane Smith"

    def test_falls_back_to_email_local_part(self):
        result = _claims_display_name({"email": "john.doe@example.com"})
        assert result == "John Doe"

    def test_underscore_in_local_part(self):
        result = _claims_display_name({"email": "tim_perkins@example.com"})
        assert result == "Tim Perkins"

    def test_empty_name_claim_uses_email(self):
        result = _claims_display_name({"name": "", "email": "admin@test.com"})
        assert result == "Admin"

    def test_no_email_no_name_returns_fallback(self):
        result = _claims_display_name({})
        assert result == "Perkins Roofing"

    def test_email_without_at_sign(self):
        result = _claims_display_name({"email": "noemail"})
        assert result == "Noemail"


# ---------------------------------------------------------------------------
# _sender_from_address — pure helper unit tests
# ---------------------------------------------------------------------------

class TestSenderFromAddress:
    def test_builds_perkinsroofing_address(self):
        result = _sender_from_address("jane@gmail.com")
        assert result == "jane@perkinsroofing.net"

    def test_strips_invalid_chars(self):
        result = _sender_from_address("bad chars!#$@gmail.com")
        assert result.endswith("@perkinsroofing.net")
        local = result.split("@")[0]
        assert "!" not in local and "#" not in local

    def test_empty_email_returns_default(self):
        from adapters.resend import _DEFAULT_FROM_EMAIL
        assert _sender_from_address("") == _DEFAULT_FROM_EMAIL

    def test_preserves_dots_and_plus(self):
        result = _sender_from_address("first.last+tag@gmail.com")
        assert result == "first.last+tag@perkinsroofing.net"

    def test_local_part_only_special_chars_becomes_noreply(self):
        result = _sender_from_address("!!!@example.com")
        assert result == "noreply@perkinsroofing.net"


# ---------------------------------------------------------------------------
# POST /email/send — sender identity (From/reply-to from claims)
# ---------------------------------------------------------------------------

def test_send_uses_claims_email_as_reply_to(admin_client):
    _mock_resend_send.last_call = {}
    with patch("api.routes.email.resend_adapter.send", side_effect=_mock_resend_send):
        r = admin_client.post(
            "/email/send",
            json={"to": "recipient@example.com", "subject": "Hi", "html": "<p>x</p>"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200
    # reply_to must be the authenticated user's own email (from verified claims)
    assert _mock_resend_send.last_call["reply_to"] == "admin@test.com"


def test_send_from_email_is_perkinsroofing_domain(admin_client):
    _mock_resend_send.last_call = {}
    with patch("api.routes.email.resend_adapter.send", side_effect=_mock_resend_send):
        r = admin_client.post(
            "/email/send",
            json={"to": "r@example.com", "subject": "S", "html": "<p>x</p>"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200
    assert _mock_resend_send.last_call["from_email"].endswith("@perkinsroofing.net")


def test_send_from_name_derived_from_claims(admin_client):
    _mock_resend_send.last_call = {}
    with patch("api.routes.email.resend_adapter.send", side_effect=_mock_resend_send):
        r = admin_client.post(
            "/email/send",
            json={"to": "r@example.com", "subject": "S", "html": "<p>x</p>"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200
    # admin@test.com → local part "admin" → title-cased "Admin"
    assert _mock_resend_send.last_call["from_name"] == "Admin"


def test_send_from_name_uses_name_claim(user_client):
    set_verifier(lambda t: {"uid": "u2", "email": "alice@test.com", "name": "Alice Smith", "role": "sales"})
    _mock_resend_send.last_call = {}
    with patch("api.routes.email.resend_adapter.send", side_effect=_mock_resend_send):
        r = user_client.post(
            "/email/send",
            json={"to": "r@example.com", "subject": "S", "html": "<p>x</p>"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 200
    assert _mock_resend_send.last_call["from_name"] == "Alice Smith"


# ---------------------------------------------------------------------------
# POST /email/preview
# ---------------------------------------------------------------------------

def test_preview_returns_branded_html(admin_client):
    r = admin_client.post(
        "/email/preview",
        json={"to": "ignored@example.com", "subject": "ignored", "html": "<p>Preview body</p>"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<!DOCTYPE html>" in r.text
    assert "<p>Preview body</p>" in r.text
    assert "Perkins Roofing" in r.text


def test_preview_includes_db_header(admin_client):
    with SessionLocal() as db:
        db.add(PlatformConfig(key="EMAIL_HTML_HEADER", value="<div>Preview Header</div>"))
        db.commit()
    r = admin_client.post(
        "/email/preview",
        json={"to": "x@x.com", "subject": "s", "html": "<p>body</p>"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 200
    assert "<div>Preview Header</div>" in r.text


def test_preview_requires_email_compose_role(anon_client):
    r = anon_client.post(
        "/email/preview",
        json={"to": "x@x.com", "subject": "s", "html": "<p>body</p>"},
        headers={"Authorization": "Bearer x"},
    )
    assert r.status_code == 403
