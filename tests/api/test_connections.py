"""Behavioral tests for api/routes/connections.py — the OAuth capture flow.

All provider HTTP + Secret Manager calls are faked; the signed-state + nonce
lifecycle runs for real against the shared SQLite DB (init_db).
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.routes.connections import router
from app.models import IntegrationStatus, OAuthStateNonce, SessionLocal, init_db

HMAC_KEY = "test-hmac-key-material"


def _make_client(role="admin"):
    set_verifier(lambda token: {
        "uid": "u1", "email": f"{role}@x.com", "role": role, "email_verified": True,
    })
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


AUTH = {"Authorization": "Bearer tok"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    init_db()
    monkeypatch.setenv("OAUTH_STATE_HMAC_KEY", HMAC_KEY)
    monkeypatch.setenv("OAUTH_REDIRECT_BASE", "https://api.example.com")
    monkeypatch.setenv("OAUTH_CLIENT_ID", "gclient")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET", "gsecret")
    yield
    with SessionLocal() as db:
        db.query(OAuthStateNonce).delete()
        db.query(IntegrationStatus).delete()
        db.commit()


class _FakeStore:
    calls: list = []

    def __init__(self, tenant_id, **kw):
        self.tenant_id = tenant_id

    def put(self, platform, account_id, access_token, refresh_token="", ttl=3600):
        _FakeStore.calls.append({
            "tenant_id": self.tenant_id, "platform": platform,
            "access_token": access_token, "refresh_token": refresh_token, "ttl": ttl,
        })


class _TokenResp:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"access_token": "AT", "refresh_token": "RT", "expires_in": 1234}


def _start(client):
    r = client.get("/oauth/youtube/start", headers=AUTH)
    assert r.status_code == 200, r.text
    auth_url = r.json()["auth_url"]
    q = parse_qs(urlparse(auth_url).query)
    return auth_url, q["state"][0], q


# ---------------------------------------------------------------------------
# GET /connections
# ---------------------------------------------------------------------------

class TestListConnections:
    def test_lists_registry_with_unconfigured_default(self):
        r = _make_client().get("/connections", headers=AUTH)
        assert r.status_code == 200
        by_key = {c["integration"]: c for c in r.json()["connections"]}
        assert by_key["youtube"]["oauth"] is True
        assert by_key["youtube"]["oauth_configured"] is True  # env set by fixture
        assert by_key["linkedin"]["oauth_configured"] is False  # no client env
        assert by_key["wordpress"]["secret_reenter"] is True
        assert by_key["wordpress"]["status"] == "unconfigured"

    def test_sales_forbidden(self):
        assert _make_client("sales").get("/connections", headers=AUTH).status_code == 403


# ---------------------------------------------------------------------------
# GET /oauth/{platform}/start
# ---------------------------------------------------------------------------

class TestOAuthStart:
    def test_unknown_platform_404(self):
        assert _make_client().get("/oauth/myspace/start", headers=AUTH).status_code == 404

    def test_unconfigured_platform_503(self, monkeypatch):
        monkeypatch.delenv("OAUTH_CLIENT_ID")
        assert _make_client().get("/oauth/youtube/start", headers=AUTH).status_code == 503

    def test_start_mints_state_and_persists_nonce(self):
        auth_url, state, q = _start(_make_client())
        assert auth_url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert q["redirect_uri"] == ["https://api.example.com/oauth/youtube/callback"]
        assert q["access_type"] == ["offline"]
        import time

        from core.oauth_state import verify_state
        parsed = verify_state(state, [HMAC_KEY.encode()], now=int(time.time()))
        assert parsed is not None and parsed["platform"] == "youtube"
        with SessionLocal() as db:
            assert db.get(OAuthStateNonce, parsed["nonce"]) is not None


# ---------------------------------------------------------------------------
# GET /oauth/{platform}/callback
# ---------------------------------------------------------------------------

class TestOAuthCallback:
    def _wire_fakes(self, monkeypatch):
        _FakeStore.calls = []
        monkeypatch.setattr(
            "adapters.distribution.oauth_store.SecretManagerOAuthStore", _FakeStore
        )
        monkeypatch.setattr("requests.post", lambda *a, **k: _TokenResp())

    def test_happy_path_stores_tokens_and_flips_healthy(self, monkeypatch):
        client = _make_client()
        _, state, _ = _start(client)
        self._wire_fakes(monkeypatch)
        r = client.get(f"/oauth/youtube/callback?code=abc&state={state}")
        assert r.status_code == 200
        assert "connected" in r.text
        assert len(_FakeStore.calls) == 1
        call = _FakeStore.calls[0]
        assert call["tenant_id"] == 1 and call["platform"] == "youtube"
        assert call["access_token"] == "AT" and call["refresh_token"] == "RT"
        with SessionLocal() as db:
            row = (db.query(IntegrationStatus)
                   .filter(IntegrationStatus.integration == "youtube").first())
            assert row is not None and row.status == "healthy" and row.tenant_id == 1

    def test_replayed_state_403(self, monkeypatch):
        client = _make_client()
        _, state, _ = _start(client)
        self._wire_fakes(monkeypatch)
        assert client.get(f"/oauth/youtube/callback?code=abc&state={state}").status_code == 200
        # Nonce burned — replay must die even with a valid signature.
        assert client.get(f"/oauth/youtube/callback?code=abc&state={state}").status_code == 403

    def test_tampered_state_403(self, monkeypatch):
        client = _make_client()
        _, state, _ = _start(client)
        self._wire_fakes(monkeypatch)
        p, m = state.split(".")
        bad = p + "." + ("A" if m[0] != "A" else "B") + m[1:]
        assert client.get(f"/oauth/youtube/callback?code=abc&state={bad}").status_code == 403
        assert _FakeStore.calls == []

    def test_platform_mismatch_403(self, monkeypatch):
        client = _make_client()
        _, state, _ = _start(client)  # state bound to youtube
        self._wire_fakes(monkeypatch)
        assert client.get(f"/oauth/tiktok/callback?code=abc&state={state}").status_code == 403

    def test_provider_cancel_is_graceful(self):
        r = _make_client().get("/oauth/youtube/callback?error=access_denied")
        assert r.status_code == 200
        assert "cancelled" in r.text

    def test_missing_code_400(self, monkeypatch):
        client = _make_client()
        _, state, _ = _start(client)
        assert client.get(f"/oauth/youtube/callback?state={state}").status_code == 400

    def test_exchange_failure_502_after_burn(self, monkeypatch):
        client = _make_client()
        _, state, _ = _start(client)
        _FakeStore.calls = []
        monkeypatch.setattr(
            "adapters.distribution.oauth_store.SecretManagerOAuthStore", _FakeStore
        )

        def _boom(*a, **k):
            raise RuntimeError("provider down")
        monkeypatch.setattr("requests.post", _boom)
        assert client.get(f"/oauth/youtube/callback?code=abc&state={state}").status_code == 502
        assert _FakeStore.calls == []


# ---------------------------------------------------------------------------
# POST /connections/{integration}/secret
# ---------------------------------------------------------------------------

class TestReenterSecret:
    def test_unknown_integration_404(self):
        r = _make_client().post(
            "/connections/db-password/secret", json={"value": "x"}, headers=AUTH
        )
        assert r.status_code == 404

    def test_empty_value_400(self):
        r = _make_client().post(
            "/connections/wordpress/secret", json={"value": "  "}, headers=AUTH
        )
        assert r.status_code == 400

    def test_writes_new_version_and_clears_last_checked(self, monkeypatch):
        calls = {}

        class _FakeSM:
            def add_secret_version(self, request):
                calls["parent"] = request["parent"]

        monkeypatch.setattr("api.routes.config._secret_manager_client", lambda: _FakeSM())
        monkeypatch.setattr("api.routes.config._gcp_project", lambda: "proj")
        # Seed a shared status row with last_checked set.
        from datetime import datetime
        with SessionLocal() as db:
            db.add(IntegrationStatus(
                integration="wordpress", tenant_id=None,
                status="broken", last_checked=datetime(2026, 7, 17),
            ))
            db.commit()
        r = _make_client().post(
            "/connections/wordpress/secret", json={"value": "new-pwd"}, headers=AUTH
        )
        assert r.status_code == 200
        assert calls["parent"] == "projects/proj/secrets/wordpress-app-password"
        with SessionLocal() as db:
            row = (db.query(IntegrationStatus)
                   .filter(IntegrationStatus.integration == "wordpress").first())
            assert row.last_checked is None
