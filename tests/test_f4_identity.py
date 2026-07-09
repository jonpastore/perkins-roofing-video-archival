"""F4b identity tests — GCIP claim mapping, platform_admin session, tenant_default_admins.

All tests in this file run on SQLite (the in-memory seam). Postgres-dependent tests
(RLS bypass, timing probe, denial matrix) live in tests/api/test_f4_impersonation.py
and are marked @pytest.mark.postgres.

TDD contract: these tests were written RED first. They drive the implementations in:
  - api/auth.py  (_resolve_tenant, _platform_admin_emails, get_platform_db_session)
  - app/models.py (TenantGcipMap, TenantDefaultAdmin, PlatformAdmin, PlatformAuditLog)
  - core/authz.py (platform_admin in _MATRIX; effective_role updated signature)
"""
import os
import pytest

# ---------------------------------------------------------------------------
# Helpers / fake verifier
# ---------------------------------------------------------------------------

def _make_verifier(claims: dict):
    """Return a callable that echoes the given claims dict (fake Firebase token)."""
    def _v(token):
        return claims
    return _v


def _auth_header(token="fake"):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. Model presence tests — ORM models must exist and be importable
# ---------------------------------------------------------------------------

class TestIdentityModels:
    def test_tenant_gcip_map_importable(self):
        from app.models import TenantGcipMap
        assert TenantGcipMap.__tablename__ == "tenant_gcip_map"

    def test_tenant_default_admin_importable(self):
        from app.models import TenantDefaultAdmin
        assert TenantDefaultAdmin.__tablename__ == "tenant_default_admins"

    def test_platform_admin_importable(self):
        from app.models import PlatformAdmin
        assert PlatformAdmin.__tablename__ == "platform_admins"

    def test_platform_audit_log_importable(self):
        from app.models import PlatformAuditLog
        assert PlatformAuditLog.__tablename__ == "platform_audit_log"

    def test_tenant_gcip_map_has_required_columns(self):
        from app.models import TenantGcipMap
        cols = {c.key for c in TenantGcipMap.__table__.columns}
        assert "tenant_id" in cols
        assert "gcip_tenant" in cols

    def test_tenant_default_admin_has_required_columns(self):
        from app.models import TenantDefaultAdmin
        cols = {c.key for c in TenantDefaultAdmin.__table__.columns}
        assert "tenant_id" in cols
        assert "email" in cols

    def test_platform_admin_has_required_columns(self):
        from app.models import PlatformAdmin
        cols = {c.key for c in PlatformAdmin.__table__.columns}
        assert "email" in cols
        assert "granted_by" in cols
        assert "granted_at" in cols

    def test_platform_audit_log_has_required_columns(self):
        from app.models import PlatformAuditLog
        cols = {c.key for c in PlatformAuditLog.__table__.columns}
        assert "id" in cols
        assert "platform_admin_email" in cols
        assert "target_tenant_id" in cols
        assert "route" in cols
        assert "method" in cols
        assert "occurred_at" in cols

    def test_gcip_map_is_platform_level_no_tenant_id_on_self(self):
        """TenantGcipMap is platform-level; it has tenant_id as FK but no TenantMixin
        inheritance that would add a second tenant_id via the mixin FK pattern."""
        from app.models import TenantGcipMap
        # should not raise — the table has exactly one tenant_id column
        cols = [c.key for c in TenantGcipMap.__table__.columns]
        assert cols.count("tenant_id") == 1


# ---------------------------------------------------------------------------
# 2. Claim-mapping / _resolve_tenant tests
# ---------------------------------------------------------------------------

class TestResolveTenant:
    def test_no_firebase_tenant_claim_returns_1(self):
        """Token with no firebase.tenant → tenant_id 1 (Perkins project-level pool)."""
        from api.auth import _resolve_tenant
        claims = {"email": "user@perkins.com", "role": "sales"}
        db = _MockDb(rows=[])
        result = _resolve_tenant(claims, db)
        assert result == 1

    def test_firebase_tenant_claim_maps_correctly(self):
        """Token with firebase.tenant present → lookup in tenant_gcip_map."""
        from api.auth import _resolve_tenant
        claims = {"email": "user@tenant2.com", "firebase": {"tenant": "perkins-abc123"}}
        db = _MockDb(rows=[{"tenant_id": 2}])
        result = _resolve_tenant(claims, db)
        assert result == 2

    def test_unknown_gcip_tenant_raises_401(self):
        """Token with firebase.tenant not in map → HTTP 401."""
        from fastapi import HTTPException
        from api.auth import _resolve_tenant
        claims = {"email": "user@unknown.com", "firebase": {"tenant": "unknown-xyz"}}
        db = _MockDb(rows=[])
        with pytest.raises(HTTPException) as exc_info:
            _resolve_tenant(claims, db)
        assert exc_info.value.status_code == 401

    def test_nested_firebase_dict_with_no_tenant_key_returns_1(self):
        """firebase key present but no 'tenant' sub-key → still tenant 1."""
        from api.auth import _resolve_tenant
        claims = {"email": "user@perkins.com", "firebase": {"sign_in_provider": "google.com"}}
        db = _MockDb(rows=[])
        result = _resolve_tenant(claims, db)
        assert result == 1


class _MockDb:
    """Minimal DB mock for _resolve_tenant / _platform_admin_emails tests."""
    def __init__(self, rows):
        self._rows = rows
        self._executed = []

    def execute(self, stmt, params=None):
        self._executed.append((stmt, params))
        return _MockResult(self._rows)


class _MockResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        if self._rows:
            row = self._rows[0]
            # Support dict-like rows (for easy test authoring)
            if isinstance(row, dict):
                return _DictRow(row)
            return row
        return None

    def fetchall(self):
        return [_DictRow(r) if isinstance(r, dict) else r for r in self._rows]

    def scalars(self):
        return self

    def all(self):
        return [r.get("email") if isinstance(r, dict) else r[0] for r in self._rows]


class _DictRow:
    def __init__(self, d):
        self._d = d

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self._d.values())[key]
        return self._d[key]

    def get(self, key, default=None):
        return self._d.get(key, default)


# ---------------------------------------------------------------------------
# 3. platform_admin role resolution tests
# ---------------------------------------------------------------------------

class TestPlatformAdminResolution:
    def test_platform_admin_role_in_matrix(self):
        """platform_admin is in _MATRIX with the correct action set."""
        from core.authz import _MATRIX
        assert "platform_admin" in _MATRIX
        perms = _MATRIX["platform_admin"]
        assert "provision_tenant" in perms
        assert "view_all_tenants" in perms
        assert "manage_platform_config" in perms
        assert "impersonate_tenant" in perms

    def test_platform_admin_can_provision_tenant(self):
        from core.authz import can
        assert can("platform_admin", "provision_tenant") is True

    def test_platform_admin_can_view_all_tenants(self):
        from core.authz import can
        assert can("platform_admin", "view_all_tenants") is True

    def test_platform_admin_can_impersonate_tenant(self):
        from core.authz import can
        assert can("platform_admin", "impersonate_tenant") is True

    def test_platform_admin_cannot_do_wildcard_actions(self):
        """platform_admin has no wildcard; it cannot do arbitrary admin actions."""
        from core.authz import can
        assert can("platform_admin", "manage_estimates") is False
        assert can("platform_admin", "article_read") is False

    def test_claims_has_platform_admin_role_when_in_table(self, tmp_path):
        """When email is in platform_admins table, _verify sets role=platform_admin, tenant_id=None."""
        import os
        from app.models import Base, PlatformAdmin, init_db
        from app.config import settings
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        # Isolated in-memory DB for this test
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        with Session() as db:
            db.add(PlatformAdmin(email="staff@degenito.ai", granted_by="jon@degenito.ai"))
            db.commit()

        from api.auth import set_verifier, _verify_with_db
        set_verifier(_make_verifier({"email": "staff@degenito.ai", "email_verified": True, "role": ""}))

        with Session() as db:
            claims = _verify_with_db("Bearer fake", db)

        assert claims["role"] == "platform_admin"
        assert claims["tenant_id"] is None

    def test_regular_user_is_not_elevated_to_platform_admin(self, tmp_path):
        """Email not in platform_admins table → normal role flow."""
        from app.models import Base, PlatformAdmin, init_db
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        from api.auth import set_verifier, _verify_with_db
        set_verifier(_make_verifier({"email": "sales@perkins.com", "email_verified": True, "role": "sales"}))

        with Session() as db:
            claims = _verify_with_db("Bearer fake", db)

        assert claims["role"] == "sales"
        assert claims.get("tenant_id") == 1


# ---------------------------------------------------------------------------
# 4. tenant_default_admins — effective_role with DB lookup
# ---------------------------------------------------------------------------

class TestEffectiveRoleDefaultAdmins:
    def test_email_in_tenant_default_admins_returns_admin(self):
        """Email in tenant_default_admins for tenant 1 → effective_role returns 'admin'."""
        from core.authz import effective_role
        db = _MockDb(rows=[{"email": "jon@perkinsroofing.net"}])
        result = effective_role(
            email="jon@perkinsroofing.net",
            role="sales",
            tenant_id=1,
            db_session=db,
            email_verified=True,
        )
        assert result == "admin"

    def test_email_not_in_table_returns_original_role(self):
        """Email not in tenant_default_admins → role unchanged."""
        from core.authz import effective_role
        db = _MockDb(rows=[])
        result = effective_role(
            email="other@perkins.com",
            role="sales",
            tenant_id=1,
            db_session=db,
            email_verified=True,
        )
        assert result == "sales"

    def test_unverified_email_not_elevated(self):
        """email_verified=False → no table lookup; role unchanged even if in table."""
        from core.authz import effective_role
        db = _MockDb(rows=[{"email": "jon@perkinsroofing.net"}])
        result = effective_role(
            email="jon@perkinsroofing.net",
            role="sales",
            tenant_id=1,
            db_session=db,
            email_verified=False,
        )
        assert result == "sales"

    def test_none_email_not_elevated(self):
        """email=None → role unchanged."""
        from core.authz import effective_role
        db = _MockDb(rows=[])
        result = effective_role(
            email=None,
            role="sales",
            tenant_id=1,
            db_session=db,
            email_verified=True,
        )
        assert result == "sales"

    def test_fallback_to_frozenset_when_db_session_is_none(self):
        """When db_session is None (SQLite fallback path), falls back to config frozenset."""
        from core.authz import effective_role
        from app.config import settings
        # Pick an email that IS in DEFAULT_ADMINS
        admin_email = next(iter(settings.DEFAULT_ADMINS))
        result = effective_role(
            email=admin_email,
            role="sales",
            tenant_id=1,
            db_session=None,
            email_verified=True,
        )
        assert result == "admin"

    def test_fallback_frozenset_non_admin_email(self):
        """db_session=None + email not in DEFAULT_ADMINS → role unchanged."""
        from core.authz import effective_role
        result = effective_role(
            email="nobody@external.com",
            role="sales",
            tenant_id=1,
            db_session=None,
            email_verified=True,
        )
        assert result == "sales"


# ---------------------------------------------------------------------------
# 5. get_platform_db_session — platform-scoped session (no GUC)
# ---------------------------------------------------------------------------

class TestPlatformDbSession:
    def test_get_platform_db_session_importable(self):
        from api.auth import get_platform_db_session
        assert callable(get_platform_db_session)

    def test_platform_session_sets_platform_scope_flag(self):
        """Platform session dependency marks session.info['platform_scope'] = True."""
        from app.models import Base, PlatformAdmin
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from api.auth import set_verifier, get_platform_db_session

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        with Session() as db:
            db.add(PlatformAdmin(email="staff@degenito.ai", granted_by="jon@degenito.ai"))
            db.commit()

        set_verifier(_make_verifier({"email": "staff@degenito.ai", "role": "platform_admin",
                                     "email_verified": True}))
        # We test the generator directly
        from api.auth import require_role
        claims = {"role": "platform_admin", "email": "staff@degenito.ai", "tenant_id": None}
        gen = get_platform_db_session(claims)
        session = next(gen)
        assert session.info.get("platform_scope") is True
        try:
            next(gen)
        except StopIteration:
            pass

    def test_platform_session_does_not_set_tenant_id_guc(self):
        """PlatformSessionLocal has no after_begin event that sets app.tenant_id GUC.
        Using it with tenant_id=None must NOT raise RuntimeError."""
        from api.auth import get_platform_db_session
        claims = {"role": "platform_admin", "email": "staff@degenito.ai", "tenant_id": None}
        gen = get_platform_db_session(claims)
        session = next(gen)
        # On SQLite there's no GUC anyway, but the session must not blow up on commit
        try:
            session.commit()
        except Exception as e:
            pytest.fail(f"platform session commit raised: {e}")
        finally:
            try:
                next(gen)
            except StopIteration:
                pass


# ---------------------------------------------------------------------------
# 6. X-Tenant-ID impersonation invariants (SQLite-level, no HTTP client needed)
# ---------------------------------------------------------------------------

class TestImpersonationInvariants:
    def test_x_tenant_id_ignored_non_platform_admin(self):
        """Non-platform_admin token with X-Tenant-ID header → header is ignored.
        claims['tenant_id'] remains what the token says (1), not what the header says."""
        from api.auth import _apply_impersonation
        claims = {"role": "admin", "tenant_id": 1, "email": "jon@perkinsroofing.net"}
        result = _apply_impersonation(claims, x_tenant_id="2", path="/api/videos")
        assert result["tenant_id"] == 1

    def test_x_tenant_id_only_on_internal_routes(self):
        """platform_admin + X-Tenant-ID on a non-/internal route → header ignored (tenant_id stays None)."""
        from api.auth import _apply_impersonation
        claims = {"role": "platform_admin", "tenant_id": None, "email": "staff@degenito.ai"}
        result = _apply_impersonation(claims, x_tenant_id="2", path="/api/videos")
        assert result["tenant_id"] is None

    def test_x_tenant_id_honored_on_internal_route(self):
        """platform_admin + X-Tenant-ID on /internal route → tenant_id set from header."""
        from api.auth import _apply_impersonation
        claims = {"role": "platform_admin", "tenant_id": None, "email": "staff@degenito.ai"}
        result = _apply_impersonation(claims, x_tenant_id="3", path="/internal/tenants/3/videos")
        assert result["tenant_id"] == 3

    def test_x_tenant_id_header_invalid_int_raises(self):
        """Non-integer X-Tenant-ID on internal route → 400."""
        from fastapi import HTTPException
        from api.auth import _apply_impersonation
        claims = {"role": "platform_admin", "tenant_id": None, "email": "staff@degenito.ai"}
        with pytest.raises(HTTPException) as exc_info:
            _apply_impersonation(claims, x_tenant_id="not-a-number", path="/internal/tenants/foo")
        assert exc_info.value.status_code == 400

    def test_impersonated_claims_include_impersonating_flag(self):
        """After impersonation is applied, claims carry impersonating=True for audit use."""
        from api.auth import _apply_impersonation
        claims = {"role": "platform_admin", "tenant_id": None, "email": "staff@degenito.ai"}
        result = _apply_impersonation(claims, x_tenant_id="5", path="/internal/tenants/5/data")
        assert result.get("impersonating") is True
        assert result.get("impersonating_as") == 5

    def test_non_platform_admin_impersonation_flag_not_set(self):
        """Regular user + header → impersonating flag never set."""
        from api.auth import _apply_impersonation
        claims = {"role": "admin", "tenant_id": 1, "email": "jon@perkinsroofing.net"}
        result = _apply_impersonation(claims, x_tenant_id="5", path="/internal/tenants/5/data")
        assert result.get("impersonating") is not True


# ---------------------------------------------------------------------------
# 7. Terraform content checks (validate-only; no apply)
# ---------------------------------------------------------------------------

class TestTerraformContent:
    def test_pitr_enabled_in_main_tf(self):
        """infra/main.tf must contain point_in_time_recovery_enabled = true."""
        tf_path = os.path.join(
            os.path.dirname(__file__), "..", "infra", "main.tf"
        )
        content = open(tf_path).read()
        assert "point_in_time_recovery_enabled" in content, \
            "PITR not found in infra/main.tf — add point_in_time_recovery_enabled = true"
        # Check the value is 'true' (strip spaces from each line for comment-resilience)
        for line in content.splitlines():
            stripped = line.replace(" ", "")
            if "point_in_time_recovery_enabled" in stripped:
                assert "=true" in stripped, \
                    f"point_in_time_recovery_enabled not set to true: {line!r}"
                break

    def test_identitytoolkit_in_required_apis(self):
        """infra/main.tf must list identitytoolkit.googleapis.com in required_apis."""
        tf_path = os.path.join(
            os.path.dirname(__file__), "..", "infra", "main.tf"
        )
        content = open(tf_path).read()
        assert "identitytoolkit.googleapis.com" in content

    def test_identity_platform_config_resource_present(self):
        """google_identity_platform_config resource must exist in main.tf."""
        tf_path = os.path.join(
            os.path.dirname(__file__), "..", "infra", "main.tf"
        )
        content = open(tf_path).read()
        assert "google_identity_platform_config" in content


# ---------------------------------------------------------------------------
# 8. Migration content checks
# ---------------------------------------------------------------------------

class TestMigrationContent:
    def _get_migration(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "infra", "migrations", "0018_rls_gcip.sql"
        )
        return open(path).read()

    def test_tenant_gcip_map_in_migration(self):
        assert "CREATE TABLE" in self._get_migration()
        assert "tenant_gcip_map" in self._get_migration()

    def test_tenant_default_admins_in_migration(self):
        assert "tenant_default_admins" in self._get_migration()

    def test_platform_admins_in_migration(self):
        assert "platform_admins" in self._get_migration()

    def test_platform_audit_log_in_migration(self):
        assert "platform_audit_log" in self._get_migration()

    def test_seed_default_admins_in_migration(self):
        """Migration must seed tenant_default_admins with DEFAULT_ADMINS values."""
        content = self._get_migration()
        assert "INSERT" in content
        assert "tenant_default_admins" in content
        assert "jon@perkinsroofing.net" in content

    def test_identity_section_marker_present(self):
        content = self._get_migration()
        assert "IDENTITY TABLES" in content or "GCIP IDENTITY" in content
