"""F4b impersonation tests.

Invariants under test (TRD-F4 §4.4):
  1. Auth gate: X-Tenant-ID is only read after a verified platform_admin claim.
  2. Route gate: X-Tenant-ID is ONLY honored on /internal/* routes.
  3. Audit: every impersonated request via require_internal_tenants writes a platform_audit_log row.
  4. No header leakage: regular tenant sessions unaffected by header.

Tests 1-3 use require_internal_tenants directly (unit-level) — the /internal/tenants route
is orchestrator-owned and not wired here. Tests 4 uses the HTTP test client for an existing
route to verify end-to-end header ignorance.
"""
import types

import pytest
from fastapi.testclient import TestClient


def _make_verifier(claims: dict):
    def _v(token):
        return claims
    return _v


def _make_request(path: str, method: str = "GET") -> types.SimpleNamespace:
    """Minimal fake Starlette Request with .url.path and .method."""
    url = types.SimpleNamespace(path=path)
    return types.SimpleNamespace(url=url, method=method)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client_with_app():
    """Fresh test client with schema initialised."""
    from app.models import init_db
    init_db()
    from api.app import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def reset_verifier():
    """Reset verifier after each test so state doesn't leak between tests."""
    from api.auth import set_verifier
    yield
    set_verifier(None)


# ---------------------------------------------------------------------------
# Test: X-Tenant-ID header ignored for non-platform_admin
# (unit-level: calls require_internal_tenants directly)
# ---------------------------------------------------------------------------

class TestXTenantIdIgnoredForNonAdmin:
    def test_regular_admin_with_x_tenant_id_header_is_ignored(self):
        """Regular admin (Perkins "*" wildcard) + X-Tenant-ID → 403 (H6 fix).

        require_internal_tenants gates on EXACT role == "platform_admin", NOT on
        can(role, "view_all_tenants"). The admin role carries "*", which would
        satisfy the action check and leak the cross-tenant tenant list to any
        Perkins admin. Only DeGenito platform_admins may reach /internal/*.
        """
        from fastapi import HTTPException

        from api.auth import require_internal_tenants, set_verifier
        set_verifier(_make_verifier({
            "email": "jon@perkinsroofing.net",
            "role": "admin",
            "email_verified": True,
        }))
        req = _make_request("/internal/tenants")
        with pytest.raises(HTTPException) as exc_info:
            require_internal_tenants(req, authorization="Bearer fake", x_tenant_id="2")
        assert exc_info.value.status_code == 403

    def test_sales_with_x_tenant_id_header_returns_403(self):
        """Sales user + X-Tenant-ID → require_internal_tenants raises 403."""
        from fastapi import HTTPException

        from api.auth import require_internal_tenants, set_verifier
        set_verifier(_make_verifier({
            "email": "rep@perkins.com",
            "role": "sales",
            "email_verified": True,
        }))
        req = _make_request("/internal/tenants")
        with pytest.raises(HTTPException) as exc_info:
            require_internal_tenants(req, authorization="Bearer fake", x_tenant_id="2")
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Test: X-Tenant-ID only honored on /internal/* routes
# (HTTP-level via /video/series — an existing route that requires tenant context)
# ---------------------------------------------------------------------------

class TestXTenantIdRouteGate:
    def test_platform_admin_with_header_on_non_internal_route_ignored(
        self, client_with_app
    ):
        """platform_admin + X-Tenant-ID on /video/series → header stripped, 403 (no tenant context)."""
        from api.auth import set_verifier
        set_verifier(_make_verifier({
            "email": "staff@degenito.ai",
            "role": "platform_admin",
            "email_verified": True,
        }))
        resp = client_with_app.get(
            "/video/series",
            headers={
                "Authorization": "Bearer fake",
                "X-Tenant-ID": "2",
            },
        )
        assert resp.status_code == 403

    def test_platform_admin_without_header_on_non_internal_route_gets_403(
        self, client_with_app
    ):
        """platform_admin without X-Tenant-ID on /video/series → 403 (no tenant context)."""
        from api.auth import set_verifier
        set_verifier(_make_verifier({
            "email": "staff@degenito.ai",
            "role": "platform_admin",
            "email_verified": True,
        }))
        resp = client_with_app.get(
            "/video/series",
            headers={"Authorization": "Bearer fake"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Test: Impersonation writes audit row
# (unit-level: calls require_internal_tenants directly with /internal/* path)
# ---------------------------------------------------------------------------

class TestImpersonationAudit:
    def test_impersonation_on_internal_route_writes_audit_row(self):
        """platform_admin + X-Tenant-ID on /internal/* → audit row written to platform_audit_log."""
        from api.auth import require_internal_tenants, set_verifier
        from app.models import PlatformAuditLog, SessionLocal, init_db
        init_db()
        set_verifier(_make_verifier({
            "email": "staff@degenito.ai",
            "role": "platform_admin",
            "email_verified": True,
        }))
        req = _make_request("/internal/tenants", method="GET")

        # Call the dependency — this should write the audit row
        result = require_internal_tenants(req, authorization="Bearer fake", x_tenant_id="1")

        assert result.get("impersonating") is True
        assert result.get("impersonating_as") == 1

        with SessionLocal() as db:
            db.info["tenant_id"] = 1
            rows = db.query(PlatformAuditLog).all()

        assert len(rows) >= 1
        audit = rows[-1]
        assert audit.platform_admin_email == "staff@degenito.ai"
        assert audit.target_tenant_id == 1
        assert audit.route == "/internal/tenants"
        assert audit.method == "GET"

    def test_non_impersonated_request_no_audit_row(self, client_with_app):
        """Regular admin request (no impersonation) → no audit row written."""
        from api.auth import set_verifier
        from app.models import PlatformAuditLog, SessionLocal
        set_verifier(_make_verifier({
            "email": "jon@perkinsroofing.net",
            "role": "admin",
            "email_verified": True,
        }))
        client_with_app.get("/video/series", headers={"Authorization": "Bearer fake"})

        with SessionLocal() as db:
            db.info["tenant_id"] = 1
            rows = db.query(PlatformAuditLog).all()

        assert all(r.platform_admin_email != "jon@perkinsroofing.net" for r in rows)


# ---------------------------------------------------------------------------
# Test: No header leakage — regular tenants unaffected
# ---------------------------------------------------------------------------

class TestNoHeaderLeakage:
    def test_regular_tenant_context_from_token_not_header(self, client_with_app):
        """Regular tenant's claims sourced from token, not X-Tenant-ID header."""
        from api.auth import set_verifier
        set_verifier(_make_verifier({
            "email": "jon@perkinsroofing.net",
            "role": "admin",
            "email_verified": True,
        }))
        resp = client_with_app.get(
            "/video/series",
            headers={
                "Authorization": "Bearer fake",
                "X-Tenant-ID": "99",
            },
        )
        assert resp.status_code != 500
        assert resp.status_code != 403
