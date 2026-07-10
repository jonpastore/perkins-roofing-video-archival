"""W0 — Dynamic CORS middleware + IntegrationsSettings unit tests.

Tests run against SQLite (conftest.py sets DB_URL before any import).
The middleware logic is tested by calling the internal helpers directly
(no live HTTP server needed) and via a TestClient for end-to-end preflight/
actual-request parity.

Council hardening verified:
- Exact-match only (look-alike / suffix origins denied)
- Vary: Origin on EVERY response (allow and deny)
- Tenant/host/origin alignment (cross-tenant mismatch denied)
- Preflight (OPTIONS) allow-list equals actual-request allow-list
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers: build an in-memory origin table for testing middleware internals
# ---------------------------------------------------------------------------

def _origins(*pairs):
    """Build a list of origin dicts like the DB rows.

    Each pair is (origin, tenant_id).  tenant_id=None = platform-wide.
    """
    return [{"origin": o, "tenant_id": tid} for o, tid in pairs]


# ---------------------------------------------------------------------------
# Unit tests: _is_allowed + _resolve_host_tenant
# ---------------------------------------------------------------------------

class TestIsAllowed:
    """Exact-match allow/deny — no substring/suffix/regex."""

    def setup_method(self):
        from api.middleware.cors import _is_allowed, _resolve_host_tenant
        self._is_allowed = _is_allowed
        self._resolve_host_tenant = _resolve_host_tenant

    # ── basic allow ──────────────────────────────────────────────────────────

    def test_registered_origin_allowed_platform_wide(self):
        origins = _origins(
            ("https://app.example.com", None),
        )
        assert self._is_allowed("https://app.example.com", None, origins)

    def test_registered_tenant_origin_allowed_when_host_matches(self):
        origins = _origins(
            ("https://app.tenant1.com", 1),
        )
        assert self._is_allowed("https://app.tenant1.com", 1, origins)

    def test_platform_wide_origin_allowed_on_any_host_tenant(self):
        origins = _origins(
            ("http://localhost:5173", None),
        )
        assert self._is_allowed("http://localhost:5173", 1, origins)
        assert self._is_allowed("http://localhost:5173", 2, origins)
        assert self._is_allowed("http://localhost:5173", None, origins)

    # ── basic deny ───────────────────────────────────────────────────────────

    def test_unregistered_origin_denied(self):
        origins = _origins(("https://app.example.com", None))
        assert not self._is_allowed("https://evil.com", None, origins)

    def test_empty_origin_denied(self):
        origins = _origins(("https://app.example.com", None))
        assert not self._is_allowed("", None, origins)

    # ── exact-match: look-alike / suffix variants denied ─────────────────────

    def test_suffix_variant_denied(self):
        origins = _origins(("https://app.example.com", None))
        assert not self._is_allowed("https://evil-app.example.com", None, origins)

    def test_subdomain_of_registered_denied(self):
        origins = _origins(("https://app.example.com", None))
        assert not self._is_allowed("https://sub.app.example.com", None, origins)

    def test_http_vs_https_denied(self):
        origins = _origins(("https://app.example.com", None))
        assert not self._is_allowed("http://app.example.com", None, origins)

    def test_trailing_slash_variant_denied(self):
        origins = _origins(("https://app.example.com", None))
        assert not self._is_allowed("https://app.example.com/", None, origins)

    def test_registered_with_port_requires_port(self):
        origins = _origins(("http://localhost:5173", None))
        assert not self._is_allowed("http://localhost", None, origins)
        assert not self._is_allowed("http://localhost:5174", None, origins)

    # ── cross-tenant origin/host mismatch ────────────────────────────────────

    def test_tenant_a_origin_denied_on_tenant_b_host(self):
        """A valid origin for tenant A must be denied when Host belongs to tenant B."""
        origins = _origins(
            ("https://app.tenant1.com", 1),
            ("https://app.tenant2.com", 2),
        )
        host_tenant = 2  # host belongs to tenant 2
        # tenant 1's origin presented on tenant 2's host → denied
        assert not self._is_allowed("https://app.tenant1.com", host_tenant, origins)

    def test_tenant_b_origin_denied_on_tenant_a_host(self):
        origins = _origins(
            ("https://app.tenant1.com", 1),
            ("https://app.tenant2.com", 2),
        )
        assert not self._is_allowed("https://app.tenant2.com", 1, origins)

    def test_tenant_origin_denied_when_no_host_tenant(self):
        """Tenant-scoped origin denied when Host is platform-wide (no tenant context)."""
        origins = _origins(
            ("https://app.tenant1.com", 1),
        )
        assert not self._is_allowed("https://app.tenant1.com", None, origins)

    def test_tenant_origin_allowed_when_host_tenant_matches(self):
        origins = _origins(
            ("https://app.tenant1.com", 1),
        )
        assert self._is_allowed("https://app.tenant1.com", 1, origins)

    # ── resolve_host_tenant ──────────────────────────────────────────────────

    def test_resolve_host_returns_tenant_id_for_known_https_host(self):
        origins = _origins(("https://app.tenant1.com", 1))
        assert self._resolve_host_tenant("app.tenant1.com", origins) == 1

    def test_resolve_host_returns_none_for_platform_wide_origin(self):
        origins = _origins(("https://platform.degenito.ai", None))
        assert self._resolve_host_tenant("platform.degenito.ai", origins) is None

    def test_resolve_host_returns_none_for_unknown_host(self):
        origins = _origins(("https://app.tenant1.com", 1))
        assert self._resolve_host_tenant("unknown.example.com", origins) is None

    def test_resolve_host_with_port_matches_port_bearing_origin(self):
        """MEDIUM-B fix: Host: localhost:5173 must match origin http://localhost:5173.

        The middleware passes the raw Host header (including port) to
        _resolve_host_tenant so tenant-scoped origins that include a port resolve
        correctly.  Previously the port was stripped before this call, so
        http://localhost:5173 (tenant-scoped or platform-wide) could never match.
        """
        from api.middleware.cors import _resolve_host_tenant
        # Platform-wide origin with port — host with port should resolve to None (platform-wide)
        origins = _origins(("http://localhost:5173", None))
        result = _resolve_host_tenant("localhost:5173", origins)
        assert result is None  # platform-wide (tenant_id=None) — correct

    def test_resolve_host_with_port_matches_tenant_scoped_origin(self):
        """A tenant-scoped origin that includes a port must match when Host also has that port."""
        from api.middleware.cors import _resolve_host_tenant
        origins = _origins(("http://localhost:5173", 1))
        assert _resolve_host_tenant("localhost:5173", origins) == 1

    def test_resolve_portless_host_does_not_match_port_bearing_origin(self):
        """Host: localhost (no port) must NOT match http://localhost:5173 — exact-match."""
        from api.middleware.cors import _resolve_host_tenant
        origins = _origins(("http://localhost:5173", None))
        assert _resolve_host_tenant("localhost", origins) is None


# ---------------------------------------------------------------------------
# Unit tests: IntegrationsSettings + TenantSettings helpers
# ---------------------------------------------------------------------------

class TestIntegrationsSettings:
    def test_load_empty_settings_returns_none_integrations(self):
        from core.tenant_settings import TenantSettings
        ts = TenantSettings.load({})
        assert ts.integrations is None

    def test_load_integrations_sub_key(self):
        from core.tenant_settings import TenantSettings
        ts = TenantSettings.load({
            "integrations": {
                "wp_url": "https://blog.example.com/",
                "yt_owner_channel_id": "UCabc123",
                "workspace_admin_subject": "admin@example.com",
            }
        })
        assert ts.integrations is not None
        assert ts.integrations.wp_url == "https://blog.example.com/"
        assert ts.integrations.yt_owner_channel_id == "UCabc123"
        assert ts.integrations.workspace_admin_subject == "admin@example.com"

    def test_get_wp_url_strips_trailing_slash(self):
        from core.tenant_settings import TenantSettings
        ts = TenantSettings.load({"integrations": {"wp_url": "https://blog.example.com/"}})
        assert ts.get_wp_url() == "https://blog.example.com"

    def test_get_wp_url_returns_empty_when_unset(self):
        from core.tenant_settings import TenantSettings
        ts = TenantSettings.load({})
        assert ts.get_wp_url() == ""

    def test_get_yt_owner_channel_id_returns_value(self):
        from core.tenant_settings import TenantSettings
        ts = TenantSettings.load({"integrations": {"yt_owner_channel_id": "UCxyz"}})
        assert ts.get_yt_owner_channel_id() == "UCxyz"

    def test_get_yt_owner_channel_id_returns_empty_when_unset(self):
        from core.tenant_settings import TenantSettings
        ts = TenantSettings.load({})
        assert ts.get_yt_owner_channel_id() == ""

    def test_get_workspace_admin_subject_returns_value(self):
        from core.tenant_settings import TenantSettings
        ts = TenantSettings.load({"integrations": {"workspace_admin_subject": "jon@example.com"}})
        assert ts.get_workspace_admin_subject() == "jon@example.com"

    def test_get_workspace_admin_subject_returns_empty_when_unset(self):
        from core.tenant_settings import TenantSettings
        ts = TenantSettings.load({})
        assert ts.get_workspace_admin_subject() == ""

    def test_existing_keys_preserved_on_round_trip(self):
        """extra='allow' must preserve unknown keys from future waves."""
        from core.tenant_settings import TenantSettings
        ts = TenantSettings.load({
            "deposit": {"mode": "percent", "value": 10.0},
            "integrations": {"wp_url": "https://wp.example.com"},
            "future_wave_key": "preserved",
        })
        dumped = ts.model_dump()
        assert dumped["future_wave_key"] == "preserved"
        assert dumped["deposit"]["mode"] == "percent"


# ---------------------------------------------------------------------------
# Unit tests: Ez-Bids platform brand constants
# ---------------------------------------------------------------------------

class TestEzBidsBrandConstants:
    def test_platform_name(self):
        from core.tenant_settings import EZBIDS_PLATFORM_NAME
        assert EZBIDS_PLATFORM_NAME == "Ez-Bids"

    def test_platform_domain(self):
        from core.tenant_settings import EZBIDS_PLATFORM_DOMAIN
        assert EZBIDS_PLATFORM_DOMAIN == "ezbids.degenito.ai"

    def test_platform_from_domain(self):
        from core.tenant_settings import EZBIDS_PLATFORM_FROM_DOMAIN
        assert "ezbids-mail" in EZBIDS_PLATFORM_FROM_DOMAIN

    def test_platform_support_email(self):
        from core.tenant_settings import EZBIDS_PLATFORM_SUPPORT_EMAIL
        assert "@" in EZBIDS_PLATFORM_SUPPORT_EMAIL


# ---------------------------------------------------------------------------
# Unit tests: CorsOrigin model in schema
# ---------------------------------------------------------------------------

class TestCorsOriginModel:
    def setup_method(self):
        from sqlalchemy import create_engine, inspect
        from app.models import Base
        self.engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.insp = inspect(self.engine)

    def test_cors_origins_table_exists(self):
        assert "cors_origins" in self.insp.get_table_names()

    def test_cors_origins_has_required_columns(self):
        cols = {c["name"] for c in self.insp.get_columns("cors_origins")}
        for expected in ("id", "origin", "tenant_id", "created_at"):
            assert expected in cols, f"cors_origins.{expected} missing"

    def test_cors_origins_has_no_tenant_id_rls(self):
        """cors_origins is RLS-exempt — it has no tenant_id NOT NULL constraint
        (tenant_id is nullable; platform-wide rows have NULL tenant_id)."""
        cols = {c["name"]: c for c in self.insp.get_columns("cors_origins")}
        assert cols["tenant_id"]["nullable"] is True


# ---------------------------------------------------------------------------
# Integration tests: CORS middleware via ASGI TestClient
# ---------------------------------------------------------------------------

class TestCORSMiddlewareIntegration:
    """Hit the middleware through a minimal ASGI app to verify HTTP behaviour."""

    def setup_method(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.models import Base, CorsOrigin
        import api.middleware.cors as cors_mod

        # Fresh in-memory SQLite with cors_origins seeded.
        # localhost:5173 is NOT seeded here — it is a dev-only origin served by
        # _get_dev_origins() when PERKINS_ENV != 'prod', not stored in the DB.
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, future=True)

        with Session() as db:
            db.add(CorsOrigin(origin="https://app.tenant1.com", tenant_id=1))
            db.add(CorsOrigin(origin="https://app.tenant2.com", tenant_id=2))
            db.commit()

        # Monkey-patch _load_origins to use our test DB, then force-populate the cache
        # so the module-global TTL cache never uses stale data from earlier tests.
        def _patched_load():
            with Session() as db:
                db.info["platform_scope"] = True
                from app.models import CorsOrigin as CO
                rows = db.query(CO).all()
                return [{"origin": r.origin, "tenant_id": r.tenant_id} for r in rows]

        cors_mod._load_origins = _patched_load
        cors_mod.invalidate_cache()
        # Force-populate cache now so the TTL doesn't use stale rows from a prior test.
        loaded = _patched_load()
        cors_mod._cache.populate(loaded)
        self._patched_rows = loaded  # used by cold-cache-fail-closed test to restore

        from fastapi import FastAPI
        from starlette.responses import JSONResponse
        mini_app = FastAPI()

        @mini_app.get("/ping")
        def ping():
            return JSONResponse({"ok": True})

        mini_app.add_middleware(cors_mod.DynamicCORSMiddleware)

        from starlette.testclient import TestClient
        self.client = TestClient(mini_app, raise_server_exceptions=True)

    # ── Vary: Origin on every response ───────────────────────────────────────

    def test_vary_origin_present_on_allowed_response(self):
        r = self.client.get("/ping", headers={"origin": "https://app.tenant1.com",
                                               "host": "app.tenant1.com"})
        assert r.headers.get("vary") == "Origin"

    def test_vary_origin_present_on_denied_response(self):
        r = self.client.get("/ping", headers={"origin": "https://evil.com",
                                               "host": "app.tenant1.com"})
        assert r.headers.get("vary") == "Origin"

    def test_vary_origin_present_even_without_origin_header(self):
        r = self.client.get("/ping")
        assert r.headers.get("vary") == "Origin"

    # ── Allow / deny ─────────────────────────────────────────────────────────

    def test_registered_origin_gets_acao_header(self):
        r = self.client.get("/ping", headers={"origin": "https://app.tenant1.com",
                                               "host": "app.tenant1.com"})
        assert r.headers.get("access-control-allow-origin") == "https://app.tenant1.com"

    def test_unregistered_origin_no_acao_header(self):
        r = self.client.get("/ping", headers={"origin": "https://evil.com",
                                               "host": "app.tenant1.com"})
        assert "access-control-allow-origin" not in r.headers

    def test_localhost_platform_wide_allowed_from_any_host(self):
        r = self.client.get("/ping", headers={"origin": "http://localhost:5173",
                                               "host": "app.tenant1.com"})
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"

    # ── Exact-match only ─────────────────────────────────────────────────────

    def test_suffix_origin_denied(self):
        r = self.client.get("/ping", headers={"origin": "https://evil-app.tenant1.com",
                                               "host": "app.tenant1.com"})
        assert "access-control-allow-origin" not in r.headers

    def test_subdomain_of_registered_denied(self):
        r = self.client.get("/ping", headers={"origin": "https://sub.app.tenant1.com",
                                               "host": "app.tenant1.com"})
        assert "access-control-allow-origin" not in r.headers

    # ── Cross-tenant mismatch ─────────────────────────────────────────────────

    def test_tenant1_origin_denied_on_tenant2_host(self):
        r = self.client.get("/ping", headers={"origin": "https://app.tenant1.com",
                                               "host": "app.tenant2.com"})
        assert "access-control-allow-origin" not in r.headers

    def test_tenant2_origin_denied_on_tenant1_host(self):
        r = self.client.get("/ping", headers={"origin": "https://app.tenant2.com",
                                               "host": "app.tenant1.com"})
        assert "access-control-allow-origin" not in r.headers

    # ── Preflight vs actual-request parity ───────────────────────────────────

    def test_preflight_allowed_same_as_actual_request(self):
        """OPTIONS and GET on the same (allowed) origin must both succeed."""
        headers = {"origin": "https://app.tenant1.com", "host": "app.tenant1.com",
                   "access-control-request-method": "POST"}
        preflight = self.client.options("/ping", headers=headers)
        actual = self.client.get("/ping", headers={"origin": "https://app.tenant1.com",
                                                    "host": "app.tenant1.com"})
        assert preflight.headers.get("access-control-allow-origin") == \
               actual.headers.get("access-control-allow-origin")

    def test_preflight_denied_same_as_actual_request(self):
        """OPTIONS and GET on the same (denied) origin must both be denied."""
        headers = {"origin": "https://evil.com", "host": "app.tenant1.com",
                   "access-control-request-method": "POST"}
        preflight = self.client.options("/ping", headers=headers)
        actual = self.client.get("/ping", headers={"origin": "https://evil.com",
                                                    "host": "app.tenant1.com"})
        assert "access-control-allow-origin" not in preflight.headers
        assert "access-control-allow-origin" not in actual.headers

    def test_preflight_cross_tenant_mismatch_denied(self):
        """Preflight for a cross-tenant mismatch must be denied just like the actual request."""
        headers = {"origin": "https://app.tenant1.com", "host": "app.tenant2.com",
                   "access-control-request-method": "GET"}
        preflight = self.client.options("/ping", headers=headers)
        assert "access-control-allow-origin" not in preflight.headers

    def test_preflight_returns_204(self):
        headers = {"origin": "https://app.tenant1.com", "host": "app.tenant1.com",
                   "access-control-request-method": "GET"}
        r = self.client.options("/ping", headers=headers)
        assert r.status_code == 204

    def test_preflight_vary_origin(self):
        headers = {"origin": "https://app.tenant1.com", "host": "app.tenant1.com",
                   "access-control-request-method": "GET"}
        r = self.client.options("/ping", headers=headers)
        assert r.headers.get("vary") == "Origin"

    # ── LOW: credentials header absent on denied responses ────────────────────

    def test_no_credentials_header_on_denied_response(self):
        """Access-Control-Allow-Credentials must NOT appear on denied responses."""
        r = self.client.get("/ping", headers={"origin": "https://evil.com",
                                               "host": "app.tenant1.com"})
        assert "access-control-allow-credentials" not in r.headers

    def test_no_credentials_header_on_cross_tenant_mismatch(self):
        r = self.client.get("/ping", headers={"origin": "https://app.tenant1.com",
                                               "host": "app.tenant2.com"})
        assert "access-control-allow-credentials" not in r.headers

    # ── MEDIUM-A: Vary: Origin on 5xx paths ───────────────────────────────────

    def test_vary_origin_present_on_500_response(self):
        """Vary: Origin must be stamped even when the inner app returns a 500.

        BaseHTTPMiddleware converts inner-app exceptions to Response objects before
        they reach our dispatch, so call_next returns a 500 Response rather than
        raising — our header-stamping loop covers it.
        """
        import api.middleware.cors as cors_mod
        from fastapi import FastAPI
        from starlette.responses import JSONResponse
        from starlette.testclient import TestClient

        error_app = FastAPI()

        @error_app.get("/boom")
        def boom():
            raise RuntimeError("deliberate 500")

        error_app.add_middleware(cors_mod.DynamicCORSMiddleware)
        # Force cache with the same origins as setup_method
        cors_mod._cache.populate([
            {"origin": "https://app.tenant1.com", "tenant_id": 1},
        ])

        c = TestClient(error_app, raise_server_exceptions=False)
        r = c.get("/boom", headers={"origin": "https://app.tenant1.com",
                                     "host": "app.tenant1.com"})
        assert r.status_code == 500
        assert r.headers.get("vary") == "Origin"

    # ── MEDIUM-B: localhost with port resolves correctly ─────────────────────

    def test_localhost_with_port_gets_acao_when_platform_wide(self):
        """http://localhost:5173 (platform-wide) must get ACAO when Host: localhost:5173.

        MEDIUM-B fix: dispatch now passes the raw Host header (with port) to
        _resolve_host_tenant so port-bearing origins can match their host.
        """
        import api.middleware.cors as cors_mod
        from fastapi import FastAPI
        from starlette.responses import JSONResponse
        from starlette.testclient import TestClient

        dev_app = FastAPI()

        @dev_app.get("/ping")
        def ping():
            return JSONResponse({"ok": True})

        dev_app.add_middleware(cors_mod.DynamicCORSMiddleware)
        # Seed cache with localhost:5173 as platform-wide
        cors_mod._cache.populate([
            {"origin": "http://localhost:5173", "tenant_id": None},
        ])

        c = TestClient(dev_app, raise_server_exceptions=True)
        r = c.get("/ping", headers={"origin": "http://localhost:5173",
                                     "host": "localhost:5173"})
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
        assert r.headers.get("vary") == "Origin"

    # ── LOW: cold-cache DB-failure → fail-closed ─────────────────────────────

    def test_cold_cache_db_failure_fail_closed(self):
        """If the DB is unavailable on a cold cache, all origins are denied
        (empty cache — not an exception that crashes the request).
        """
        import api.middleware.cors as cors_mod

        original_load = cors_mod._load_origins

        def _always_fail():
            raise RuntimeError("DB unavailable")

        cors_mod._load_origins = _always_fail
        cors_mod.invalidate_cache()
        try:
            origins = cors_mod._get_origins()
            # Exception is swallowed; cache stays empty; all origins denied
            db_rows = [r for r in origins if r["tenant_id"] is not None or
                       r["origin"] == "https://app.tenant1.com"]
            assert not cors_mod._is_allowed("https://app.tenant1.com", 1, origins), \
                "cold-cache DB failure must deny all origins (fail-closed)"
        finally:
            cors_mod._load_origins = original_load
            # Restore cache so subsequent tests are unaffected
            cors_mod._cache.populate(self._patched_rows)

