"""Negative-path tests for the platform/admin API routes not yet covered elsewhere:
api/routes/{users,config,scheduling,measurements,squares,estimator,connections}.py.

For each POST/PUT/PATCH/DELETE endpoint this fills the gaps left by the existing
per-route test files (test_users.py, test_config.py, test_scheduling.py, test_squares.py,
test_estimator_f2.py, test_connections.py, test_email_features.py, test_knowify_api.py):
  1. missing required field -> 422
  2. wrong type for a field -> 422
  3. nonexistent resource id -> 404 (authed, valid body)
  4. unauthenticated -> 401
  5. insufficient role -> 403

Cases already covered by those files are intentionally skipped here (see the final
report for the full list). logs.py, dashboard.py, admin_metrics.py, and audit.py have
no POST/PUT/PATCH/DELETE endpoints and are out of scope. knowify.py's two POST routes
are already fully covered (401/403/200) in test_knowify_api.py.

All tests run against the shared api.app (every router here is mounted in api/app.py),
following the fixture pattern in tests/api/test_f3_customers.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.app as appmod
from api.auth import set_verifier
from app.models import init_db

AUTH = {"Authorization": "Bearer x"}


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()


@pytest.fixture()
def admin_client():
    set_verifier(lambda t: {"uid": "u1", "email": "admin@perkins.com",
                             "role": "admin", "email_verified": True})
    return TestClient(appmod.app)


@pytest.fixture()
def sales_client():
    set_verifier(lambda t: {"uid": "u2", "email": "sales@perkins.com",
                             "role": "sales", "email_verified": True})
    return TestClient(appmod.app)


@pytest.fixture()
def unauth_client():
    set_verifier(None)
    return TestClient(appmod.app)


def _no_role_client(role: str) -> TestClient:
    """A role with no standalone grants — used to hit 403 on actions every named
    role (admin/web_admin/sales) is otherwise permitted (e.g. estimating_view)."""
    set_verifier(lambda t: {"uid": "u3", "email": f"{role}@perkins.com",
                             "role": role, "email_verified": True})
    return TestClient(appmod.app)


# ---------------------------------------------------------------------------
# 1 + 2: missing required field / wrong type -> 422 (admin has "*", so a single
# authed-admin client covers every route's validation regardless of role gate).
# ---------------------------------------------------------------------------

MISSING_FIELD_CASES = [
    ("users_role_missing_email", "post", "/admin/users/role", {"role": "admin"}),
    ("users_invite_missing_email", "post", "/admin/users/invite", {"role": "admin"}),
    ("users_invite_missing_role", "post", "/admin/users/invite", {"email": "x@test.com"}),
    ("users_signature_missing_email", "put", "/admin/users/signature", {"signature": "hi"}),
    ("config_put_missing_value", "put", "/config", {"key": "WP_URL"}),
    ("config_put_missing_key", "put", "/config", {"value": "x"}),
    ("config_secrets_missing_value", "put", "/config/secrets", {"key": "youtube-api-key"}),
    ("scheduling_missing_kind", "post", "/scheduling",
     {"ref_id": "x", "publish_at": "2026-08-01T10:00:00"}),
    ("scheduling_missing_ref_id", "post", "/scheduling",
     {"kind": "reel", "publish_at": "2026-08-01T10:00:00"}),
    ("scheduling_missing_publish_at", "post", "/scheduling", {"kind": "reel", "ref_id": "x"}),
    ("estimator_quote_missing_num_squares", "post", "/estimator/quote",
     {"branch": "miami", "code_zone": "HVHZ", "roof_type": "13_tile"}),
    ("connections_secret_missing_value", "post", "/connections/wordpress/secret", {}),
]

WRONG_TYPE_CASES = [
    ("users_role_email_wrong_type", "post", "/admin/users/role", {"email": 123, "role": "admin"}),
    ("users_invite_email_wrong_type", "post", "/admin/users/invite", {"email": 123, "role": "admin"}),
    ("users_signature_email_wrong_type", "put", "/admin/users/signature",
     {"email": 123, "signature": "hi"}),
    ("me_signature_wrong_type", "put", "/me/signature", {"signature": 123}),
    ("config_put_value_wrong_type", "put", "/config", {"key": "WP_URL", "value": 123}),
    ("config_secrets_value_wrong_type", "put", "/config/secrets",
     {"key": "youtube-api-key", "value": 123}),
    ("scheduling_publish_at_wrong_type", "post", "/scheduling",
     {"kind": "reel", "ref_id": "x", "publish_at": "not-a-date"}),
    ("measurements_total_sq_wrong_type", "post", "/measurements", {"total_sq": "not-a-number"}),
    ("squares_latitude_wrong_type", "post", "/squares/measure",
     {"latitude": "abc", "longitude": -80.0}),
    ("estimator_quote_num_squares_wrong_type", "post", "/estimator/quote",
     {"branch": "miami", "code_zone": "HVHZ", "roof_type": "13_tile", "num_squares": "abc"}),
    ("connections_secret_value_wrong_type", "post", "/connections/wordpress/secret",
     {"value": 123}),
]


@pytest.mark.parametrize("case,method,path,payload", MISSING_FIELD_CASES,
                         ids=[c[0] for c in MISSING_FIELD_CASES])
def test_missing_required_field_returns_422(admin_client, case, method, path, payload):
    r = getattr(admin_client, method)(path, json=payload, headers=AUTH)
    assert r.status_code == 422, f"{case}: expected 422, got {r.status_code}: {r.text}"


@pytest.mark.parametrize("case,method,path,payload", WRONG_TYPE_CASES,
                         ids=[c[0] for c in WRONG_TYPE_CASES])
def test_wrong_type_field_returns_422(admin_client, case, method, path, payload):
    r = getattr(admin_client, method)(path, json=payload, headers=AUTH)
    assert r.status_code == 422, f"{case}: expected 422, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# DELETE /admin/users — has a request body, and httpx's Client.delete() (0.28)
# does not accept json=; use .request("DELETE", ...) instead.
# ---------------------------------------------------------------------------

def test_delete_user_missing_email_422(admin_client):
    r = admin_client.request("DELETE", "/admin/users", json={}, headers=AUTH)
    assert r.status_code == 422, r.text


def test_delete_user_email_wrong_type_422(admin_client):
    r = admin_client.request("DELETE", "/admin/users", json={"email": 123}, headers=AUTH)
    assert r.status_code == 422, r.text


def test_delete_user_not_found_404(admin_client, monkeypatch):
    import api.routes.users as users_mod
    from app.config import settings
    monkeypatch.setattr(settings, "DEFAULT_ADMINS", frozenset())
    monkeypatch.setattr(
        users_mod,
        "_firebase_auth",
        lambda: __import__("types").SimpleNamespace(
            get_user_by_email=lambda email: (_ for _ in ()).throw(Exception("not found")),
        ),
    )
    r = admin_client.request(
        "DELETE", "/admin/users", json={"email": "nobody@test.com"}, headers=AUTH
    )
    assert r.status_code == 404, r.text


def test_delete_user_sales_forbidden_403(sales_client):
    r = sales_client.request(
        "DELETE", "/admin/users", json={"email": "x@test.com"}, headers=AUTH
    )
    assert r.status_code == 403, r.text


def test_delete_user_unauthenticated_401(unauth_client):
    r = unauth_client.request("DELETE", "/admin/users", json={"email": "x@test.com"})
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# 4: unauthenticated -> 401 (not already covered by the per-route test files)
# ---------------------------------------------------------------------------

UNAUTH_CASES = [
    ("users_role", "post", "/admin/users/role", {"email": "a@b.com", "role": "admin"}),
    ("users_invite", "post", "/admin/users/invite", {"email": "a@b.com", "role": "admin"}),
    ("users_signature", "put", "/admin/users/signature", {"email": "a@b.com", "signature": "x"}),
    ("scheduling_create", "post", "/scheduling",
     {"kind": "reel", "ref_id": "vid-1", "publish_at": "2026-08-01T10:00:00"}),
    ("scheduling_update", "put", "/scheduling/1", {"target": "instagram"}),
    ("scheduling_delete", "delete", "/scheduling/1", None),
    ("connections_secret", "post", "/connections/wordpress/secret", {"value": "x"}),
]


@pytest.mark.parametrize("case,method,path,payload", UNAUTH_CASES,
                         ids=[c[0] for c in UNAUTH_CASES])
def test_unauthenticated_returns_401(unauth_client, case, method, path, payload):
    kwargs = {"headers": {}}
    if payload is not None:
        kwargs["json"] = payload
    r = getattr(unauth_client, method)(path, **kwargs)
    assert r.status_code == 401, f"{case}: expected 401, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# 5: insufficient role -> 403 (not already covered by the per-route test files)
# ---------------------------------------------------------------------------

def test_squares_measure_estimating_view_role_required_403():
    """estimating_view is granted to admin/web_admin/sales — use a role with no
    standalone grants (platform_admin) to exercise the reject path."""
    client = _no_role_client("platform_admin")
    r = client.post("/squares/measure", json={"address": "anywhere"}, headers=AUTH)
    assert r.status_code == 403, r.text


def test_estimator_quote_estimating_view_role_required_403():
    client = _no_role_client("platform_admin")
    r = client.post(
        "/estimator/quote",
        json={"branch": "miami", "code_zone": "HVHZ", "roof_type": "13_tile", "num_squares": 5.0},
        headers=AUTH,
    )
    assert r.status_code == 403, r.text


def test_connections_secret_sales_forbidden_403(sales_client):
    """POST /connections/{integration}/secret is gated on manage_config (admin-only
    via require_role_db); sales lacks it."""
    r = sales_client.post(
        "/connections/wordpress/secret", json={"value": "new-value"}, headers=AUTH
    )
    assert r.status_code == 403, r.text
