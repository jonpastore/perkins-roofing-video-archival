"""Tests for core/provision.py — TDD red-first.

All DB and GCIP calls are mocked; no live connections required.
Covers §9 unit tests for provision_tenant() and SSO logic.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(slug_exists=False, existing_tenant_id=None):
    """Build a minimal mock DB session for provision tests.

    First execute().fetchone() call: slug uniqueness check
      - slug_exists=True  → returns a row (conflict)
      - slug_exists=False → returns None (available)
    """
    mock_db = MagicMock()
    call_count = [0]

    def fetchone_side():
        call_count[0] += 1
        if call_count[0] == 1:
            # Slug uniqueness check
            if slug_exists:
                row = MagicMock()
                row.__getitem__ = lambda s, i: existing_tenant_id if i == 0 else "active"
                row[0] = existing_tenant_id
                return row
            return None
        # Subsequent calls (tenant insert returning id, etc.) return a simple row
        row = MagicMock()
        row.__getitem__ = lambda s, i: 42
        return row

    mock_result = MagicMock()
    mock_result.fetchone.side_effect = fetchone_side
    mock_result.fetchall.return_value = []
    mock_db.execute.return_value = mock_result
    return mock_db


def _make_gcip_client(raise_on_create=False, gcip_tenant_id="gcip-tenant-abc123"):
    """Return a mock gcip_client with injectable failure on create_gcip_tenant."""
    client = MagicMock()
    if raise_on_create:
        client.create_gcip_tenant.side_effect = RuntimeError("GCIP unavailable")
    else:
        client.create_gcip_tenant.return_value = gcip_tenant_id
    client.generate_signin_link.return_value = "https://example.com/signin?oob=XYZ"
    client.delete_gcip_tenant.return_value = None
    return client


# ---------------------------------------------------------------------------
# 1. provision_tenant creates a DB row and returns invite link
# ---------------------------------------------------------------------------

class TestProvisionTenantSuccess:
    def test_creates_db_row_and_returns_invite_link(self):
        """provision_tenant() inserts a tenant, seeds configs, creates GCIP tenant,
        seeds admin, generates invite link, sets status='active', returns dict."""
        from core.provision import provision_tenant

        db = _make_db(slug_exists=False)
        gcip = _make_gcip_client()

        result = provision_tenant(
            name="Acme Roofing",
            slug="acme",
            admin_email="admin@acme.com",
            db=db,
            gcip_client=gcip,
        )

        # GCIP tenant was created
        gcip.create_gcip_tenant.assert_called_once_with("Acme Roofing")

        # Invite link was generated
        gcip.generate_signin_link.assert_called_once()

        # Result has expected keys
        assert "tenant_id" in result
        assert "gcip_tenant_id" in result
        assert "invite_link" in result
        assert result["invite_link"] == "https://example.com/signin?oob=XYZ"
        assert result["gcip_tenant_id"] == "gcip-tenant-abc123"

    def test_db_execute_called_with_provisioning_status(self):
        """INSERT uses status='provisioning' before updating to 'active'."""
        from core.provision import provision_tenant

        db = _make_db(slug_exists=False)
        gcip = _make_gcip_client()

        provision_tenant(
            name="Beta Co",
            slug="beta",
            admin_email="admin@beta.com",
            db=db,
            gcip_client=gcip,
        )

        # Collect all SQL strings executed
        all_sql = " ".join(
            str(args[0]) for args, kwargs in db.execute.call_args_list
        )
        assert "provisioning" in all_sql.lower()
        assert "active" in all_sql.lower()


# ---------------------------------------------------------------------------
# 2. Idempotency on slug conflict
# ---------------------------------------------------------------------------

class TestProvisionTenantSlugConflict:
    def test_slug_conflict_raises_409_error(self):
        """Duplicate slug → SlugConflictError (no partial DB state)."""
        from core.provision import SlugConflictError, provision_tenant

        db = _make_db(slug_exists=True, existing_tenant_id=7)
        gcip = _make_gcip_client()

        with pytest.raises(SlugConflictError):
            provision_tenant(
                name="Dup",
                slug="acme",
                admin_email="admin@dup.com",
                db=db,
                gcip_client=gcip,
            )

    def test_slug_conflict_does_not_call_gcip(self):
        """No GCIP call when slug already exists."""
        from core.provision import SlugConflictError, provision_tenant

        db = _make_db(slug_exists=True, existing_tenant_id=7)
        gcip = _make_gcip_client()

        with pytest.raises(SlugConflictError):
            provision_tenant(
                name="Dup",
                slug="acme",
                admin_email="admin@dup.com",
                db=db,
                gcip_client=gcip,
            )

        gcip.create_gcip_tenant.assert_not_called()

    def test_slug_conflict_error_contains_existing_id(self):
        """SlugConflictError.existing_tenant_id is populated."""
        from core.provision import SlugConflictError, provision_tenant

        db = _make_db(slug_exists=True, existing_tenant_id=7)
        gcip = _make_gcip_client()

        with pytest.raises(SlugConflictError) as exc_info:
            provision_tenant(
                name="Dup",
                slug="acme",
                admin_email="admin@dup.com",
                db=db,
                gcip_client=gcip,
            )

        assert exc_info.value.existing_tenant_id == 7


# ---------------------------------------------------------------------------
# 3. Rollback on GCIP failure
# ---------------------------------------------------------------------------

class TestProvisionTenantRollbackOnGcipFailure:
    def test_rollback_sets_status_provisioning_failed(self):
        """If GCIP create raises, status is set to 'provisioning_failed' in DB."""
        from core.provision import ProvisioningError, provision_tenant

        db = _make_db(slug_exists=False)
        gcip = _make_gcip_client(raise_on_create=True)

        with pytest.raises(ProvisioningError):
            provision_tenant(
                name="Gamma",
                slug="gamma",
                admin_email="admin@gamma.com",
                db=db,
                gcip_client=gcip,
            )

        # Some execute call must contain 'provisioning_failed'
        all_sql = " ".join(
            str(args[0]) for args, kwargs in db.execute.call_args_list
        )
        assert "provisioning_failed" in all_sql

    def test_rollback_persists_provisioning_error_in_settings(self):
        """The failed-status UPDATE also records the error in settings.provisioning_error
        so GET /internal/tenants/{id}/status can surface it."""
        from core.provision import ProvisioningError, provision_tenant

        db = _make_db(slug_exists=False)
        gcip = _make_gcip_client(raise_on_create=True)

        with pytest.raises(ProvisioningError):
            provision_tenant(
                name="Gamma",
                slug="gamma",
                admin_email="admin@gamma.com",
                db=db,
                gcip_client=gcip,
            )

        # Find the failed-status UPDATE and confirm its params embed the error.
        failed_calls = [
            (args, kwargs) for args, kwargs in db.execute.call_args_list
            if "provisioning_failed" in str(args[0])
        ]
        assert failed_calls, "expected a provisioning_failed UPDATE"
        params = failed_calls[-1][0][1] if len(failed_calls[-1][0]) > 1 else failed_calls[-1][1]
        assert "provisioning_error" in params.get("s", ""), params

    def test_rollback_does_not_leave_gcip_orphan_if_not_created(self):
        """When GCIP create raises before returning, delete_gcip_tenant is not called
        (nothing to clean up)."""
        from core.provision import ProvisioningError, provision_tenant

        db = _make_db(slug_exists=False)
        gcip = _make_gcip_client(raise_on_create=True)

        with pytest.raises(ProvisioningError):
            provision_tenant(
                name="Gamma",
                slug="gamma",
                admin_email="admin@gamma.com",
                db=db,
                gcip_client=gcip,
            )

        gcip.delete_gcip_tenant.assert_not_called()

    def test_rollback_deletes_gcip_tenant_if_created_before_later_failure(self):
        """If GCIP tenant is created but a subsequent step raises, delete is called."""
        from core.provision import ProvisioningError, provision_tenant

        db = _make_db(slug_exists=False)
        gcip = _make_gcip_client(raise_on_create=False)
        # Make generate_signin_link fail after GCIP tenant is created
        gcip.generate_signin_link.side_effect = RuntimeError("link gen failed")

        with pytest.raises(ProvisioningError):
            provision_tenant(
                name="Delta",
                slug="delta",
                admin_email="admin@delta.com",
                db=db,
                gcip_client=gcip,
            )

        # GCIP tenant was created, then must be deleted on rollback
        gcip.delete_gcip_tenant.assert_called_once_with("gcip-tenant-abc123")

    def test_rollback_status_update_raises_does_not_swallow_original_error(self):
        """If the rollback status UPDATE itself raises, ProvisioningError still propagates.

        Sequence: slug check OK → INSERT OK → SELECT tenant_id OK → GCIP create raises
        → rollback UPDATE raises → ProvisioningError still raised.
        """
        from core.provision import ProvisioningError, provision_tenant

        db = _make_db(slug_exists=False)
        gcip = _make_gcip_client(raise_on_create=True)

        # The real mock already handles the first 3 execute calls fine (slug check,
        # INSERT, SELECT for tenant_id). We need the 4th call (rollback UPDATE) to raise.
        original_execute = db.execute
        call_count = [0]

        def flaky_execute(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 3:
                # slug check, INSERT, SELECT tenant_id — all succeed
                return original_execute(*args, **kwargs)
            # 4th call is the rollback UPDATE — raise to exercise the except handler
            raise RuntimeError("DB rollback write failed")

        db.execute = flaky_execute

        with pytest.raises(ProvisioningError):
            provision_tenant(
                name="Epsilon",
                slug="epsilon",
                admin_email="admin@epsilon.com",
                db=db,
                gcip_client=gcip,
            )

    def test_rollback_gcip_delete_raises_does_not_swallow_original_error(self):
        """If GCIP delete during rollback raises, ProvisioningError still propagates."""
        from core.provision import ProvisioningError, provision_tenant

        db = _make_db(slug_exists=False)
        gcip = _make_gcip_client(raise_on_create=False)
        # GCIP create succeeds, but link gen fails AND rollback delete also fails
        gcip.generate_signin_link.side_effect = RuntimeError("link gen failed")
        gcip.delete_gcip_tenant.side_effect = RuntimeError("GCIP delete also failed")

        with pytest.raises(ProvisioningError):
            provision_tenant(
                name="Zeta",
                slug="zeta",
                admin_email="admin@zeta.com",
                db=db,
                gcip_client=gcip,
            )

        # delete_gcip_tenant was attempted even though it raised
        gcip.delete_gcip_tenant.assert_called_once_with("gcip-tenant-abc123")


# ---------------------------------------------------------------------------
# 4. SSO helpers — list_sso_providers / add_sso_provider / remove_sso_provider
# ---------------------------------------------------------------------------

class TestSsoLogic:
    def test_add_saml_provider_calls_gcip(self):
        """add_sso_provider delegates to gcip_client.add_sso_provider for SAML."""
        from core.provision import add_sso_provider

        gcip = MagicMock()
        gcip.add_sso_provider.return_value = {"idp_id": "saml.acme", "type": "saml"}

        result = add_sso_provider(
            gcip_tenant_id="gcip-t-123",
            provider_type="saml",
            config={
                "entity_id": "urn:acme",
                "sso_url": "https://acme.okta.com/sso",
                "certificate": "-----BEGIN CERT-----\nXXX\n-----END CERT-----",
            },
            gcip_client=gcip,
        )

        gcip.add_sso_provider.assert_called_once()
        assert result["type"] == "saml"

    def test_add_oidc_provider_calls_gcip(self):
        """add_sso_provider delegates to gcip_client.add_sso_provider for OIDC."""
        from core.provision import add_sso_provider

        gcip = MagicMock()
        gcip.add_sso_provider.return_value = {"idp_id": "oidc.acme", "type": "oidc"}

        result = add_sso_provider(
            gcip_tenant_id="gcip-t-123",
            provider_type="oidc",
            config={
                "issuer": "https://acme.okta.com",
                "client_id": "abc",
                "client_secret": "secret",
            },
            gcip_client=gcip,
        )

        gcip.add_sso_provider.assert_called_once()
        assert result["type"] == "oidc"

    def test_add_sso_provider_rejects_invalid_type(self):
        """add_sso_provider raises ValueError for unknown provider type."""
        from core.provision import add_sso_provider

        gcip = MagicMock()

        with pytest.raises(ValueError, match="provider_type"):
            add_sso_provider(
                gcip_tenant_id="gcip-t-123",
                provider_type="ldap",
                config={},
                gcip_client=gcip,
            )

    def test_list_sso_providers_delegates_to_gcip(self):
        """list_sso_providers returns results from gcip_client."""
        from core.provision import list_sso_providers

        gcip = MagicMock()
        gcip.list_sso_providers.return_value = [
            {"idp_id": "saml.acme", "type": "saml"},
        ]

        providers = list_sso_providers(gcip_tenant_id="gcip-t-123", gcip_client=gcip)

        gcip.list_sso_providers.assert_called_once_with("gcip-t-123")
        assert len(providers) == 1

    def test_remove_sso_provider_delegates_to_gcip(self):
        """remove_sso_provider calls gcip_client.delete_sso_provider."""
        from core.provision import remove_sso_provider

        gcip = MagicMock()

        remove_sso_provider(
            gcip_tenant_id="gcip-t-123",
            idp_id="saml.acme",
            gcip_client=gcip,
        )

        gcip.delete_sso_provider.assert_called_once_with("gcip-t-123", "saml.acme")


# ---------------------------------------------------------------------------
# 5. resend_invite
# ---------------------------------------------------------------------------

class TestResendInvite:
    def test_resend_invite_generates_new_link(self):
        """resend_invite calls gcip_client.generate_signin_link and returns the link."""
        from core.provision import resend_invite

        gcip = MagicMock()
        gcip.generate_signin_link.return_value = "https://example.com/signin?oob=NEW"

        link = resend_invite(
            gcip_tenant_id="gcip-t-123",
            admin_email="admin@acme.com",
            gcip_client=gcip,
        )

        gcip.generate_signin_link.assert_called_once_with(
            "gcip-t-123", "admin@acme.com"
        )
        assert link == "https://example.com/signin?oob=NEW"
