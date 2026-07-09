"""Tests for adapters/gcip.py — TDD red-first.

The Firebase Admin SDK is fully mocked; no live GCP connections required.
Each function under test accepts an injectable client so the real SDK is
never imported during tests.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_tenant(tenant_id: str, display_name: str = "Test Tenant"):
    t = MagicMock()
    t.tenant_id = tenant_id
    t.display_name = display_name
    return t


def _mock_saml_config(name: str, display_name: str = "Acme SAML"):
    c = MagicMock()
    c.name = name  # e.g. "projects/p/tenants/t/inboundSamlConfigs/saml.acme"
    c.display_name = display_name
    # Derive idp_id from the name suffix
    c.idp_id = name.rsplit("/", 1)[-1]
    return c


def _mock_oidc_config(name: str, display_name: str = "Acme OIDC"):
    c = MagicMock()
    c.name = name
    c.display_name = display_name
    c.idp_id = name.rsplit("/", 1)[-1]
    return c


# ---------------------------------------------------------------------------
# create_gcip_tenant
# ---------------------------------------------------------------------------

class TestCreateGcipTenant:
    def test_create_returns_tenant_id(self):
        """create_gcip_tenant returns the GCIP tenant_id string."""
        from adapters.gcip import create_gcip_tenant

        mock_mgr = MagicMock()
        mock_mgr.create_tenant.return_value = _mock_tenant("GCIP-T-001")

        result = create_gcip_tenant("Acme Roofing", tenant_manager=mock_mgr)

        mock_mgr.create_tenant.assert_called_once()
        assert result == "GCIP-T-001"

    def test_create_passes_display_name(self):
        """create_gcip_tenant passes display_name to the SDK."""
        from adapters.gcip import create_gcip_tenant

        mock_mgr = MagicMock()
        mock_mgr.create_tenant.return_value = _mock_tenant("GCIP-T-002")

        create_gcip_tenant("Beta Roofing Co", tenant_manager=mock_mgr)

        call_kwargs = mock_mgr.create_tenant.call_args
        # display_name must appear either as positional or keyword arg
        all_args = str(call_kwargs)
        assert "Beta Roofing Co" in all_args

    def test_create_enables_email_link_sign_in(self):
        """create_gcip_tenant enables email-link sign-in (passwordless invite flow)."""
        from adapters.gcip import create_gcip_tenant

        mock_mgr = MagicMock()
        mock_mgr.create_tenant.return_value = _mock_tenant("GCIP-T-003")

        create_gcip_tenant("Gamma Corp", tenant_manager=mock_mgr)

        call_kwargs = mock_mgr.create_tenant.call_args
        all_args = str(call_kwargs)
        assert "enable_email_link_sign_in" in all_args

    def test_create_propagates_sdk_errors(self):
        """SDK errors bubble up as-is (caller handles rollback)."""
        from adapters.gcip import create_gcip_tenant

        mock_mgr = MagicMock()
        mock_mgr.create_tenant.side_effect = RuntimeError("quota exceeded")

        with pytest.raises(RuntimeError, match="quota exceeded"):
            create_gcip_tenant("Err Corp", tenant_manager=mock_mgr)


# ---------------------------------------------------------------------------
# delete_gcip_tenant
# ---------------------------------------------------------------------------

class TestDeleteGcipTenant:
    def test_delete_calls_sdk(self):
        """delete_gcip_tenant calls tenant_manager.delete_tenant with the tenant_id."""
        from adapters.gcip import delete_gcip_tenant

        mock_mgr = MagicMock()

        delete_gcip_tenant("GCIP-T-001", tenant_manager=mock_mgr)

        mock_mgr.delete_tenant.assert_called_once_with("GCIP-T-001")

    def test_delete_propagates_sdk_errors(self):
        """SDK errors on delete bubble up."""
        from adapters.gcip import delete_gcip_tenant

        mock_mgr = MagicMock()
        mock_mgr.delete_tenant.side_effect = RuntimeError("not found")

        with pytest.raises(RuntimeError):
            delete_gcip_tenant("GCIP-T-999", tenant_manager=mock_mgr)


# ---------------------------------------------------------------------------
# generate_signin_link
# ---------------------------------------------------------------------------

class TestGenerateSigninLink:
    def test_returns_link_string(self):
        """generate_signin_link returns the oob link string."""
        from adapters.gcip import generate_signin_link

        mock_tenant_auth = MagicMock()
        mock_tenant_auth.generate_sign_in_with_email_link.return_value = (
            "https://example.com/signin?oobCode=ABC&tenantId=GCIP-T-001"
        )

        result = generate_signin_link(
            "GCIP-T-001",
            "admin@acme.com",
            tenant_auth=mock_tenant_auth,
        )

        mock_tenant_auth.generate_sign_in_with_email_link.assert_called_once()
        assert result.startswith("https://")
        assert "ABC" in result

    def test_passes_email_to_sdk(self):
        """generate_signin_link passes the admin email to the SDK call."""
        from adapters.gcip import generate_signin_link

        mock_tenant_auth = MagicMock()
        mock_tenant_auth.generate_sign_in_with_email_link.return_value = (
            "https://example.com/link"
        )

        generate_signin_link(
            "GCIP-T-001",
            "admin@acme.com",
            tenant_auth=mock_tenant_auth,
        )

        call_args = str(mock_tenant_auth.generate_sign_in_with_email_link.call_args)
        assert "admin@acme.com" in call_args

    def test_propagates_sdk_errors(self):
        """SDK errors from sign-in link generation bubble up."""
        from adapters.gcip import generate_signin_link

        mock_tenant_auth = MagicMock()
        mock_tenant_auth.generate_sign_in_with_email_link.side_effect = (
            RuntimeError("invalid email")
        )

        with pytest.raises(RuntimeError):
            generate_signin_link("GCIP-T-001", "bad@", tenant_auth=mock_tenant_auth)


# ---------------------------------------------------------------------------
# add_sso_provider
# ---------------------------------------------------------------------------

class TestAddSsoProvider:
    def test_add_saml_returns_idp_id(self):
        """add_sso_provider for SAML creates config and returns idp_id."""
        from adapters.gcip import add_sso_provider

        mock_mgr = MagicMock()
        mock_mgr.create_inbound_saml_config.return_value = _mock_saml_config(
            "projects/p/tenants/GCIP-T-001/inboundSamlConfigs/saml.acme"
        )

        result = add_sso_provider(
            gcip_tenant_id="GCIP-T-001",
            provider_type="saml",
            config={
                "entity_id": "urn:acme",
                "sso_url": "https://acme.okta.com/sso",
                "certificate": "-----BEGIN CERT-----\nXXX\n-----END CERT-----",
                "display_name": "Acme SSO",
                "idp_id": "saml.acme",
            },
            tenant_manager=mock_mgr,
        )

        mock_mgr.create_inbound_saml_config.assert_called_once()
        assert result["type"] == "saml"
        assert "idp_id" in result

    def test_add_oidc_returns_idp_id(self):
        """add_sso_provider for OIDC creates config and returns idp_id."""
        from adapters.gcip import add_sso_provider

        mock_mgr = MagicMock()
        mock_mgr.create_oidc_provider_config.return_value = _mock_oidc_config(
            "projects/p/tenants/GCIP-T-001/oauthIdpConfigs/oidc.acme"
        )

        result = add_sso_provider(
            gcip_tenant_id="GCIP-T-001",
            provider_type="oidc",
            config={
                "issuer": "https://acme.okta.com",
                "client_id": "abc",
                "client_secret": "secret",
                "display_name": "Acme OIDC",
                "idp_id": "oidc.acme",
            },
            tenant_manager=mock_mgr,
        )

        mock_mgr.create_oidc_provider_config.assert_called_once()
        assert result["type"] == "oidc"
        assert "idp_id" in result

    def test_add_saml_accepts_spa_certificate_pem_field(self):
        """SPA sends 'certificate_pem' (not 'certificate'); adapter must accept it."""
        from adapters.gcip import add_sso_provider

        mock_mgr = MagicMock()
        mock_mgr.create_inbound_saml_config.return_value = _mock_saml_config(
            "projects/p/tenants/GCIP-T-001/inboundSamlConfigs/saml.acme"
        )
        cert = "-----BEGIN CERT-----\nSPA\n-----END CERT-----"
        add_sso_provider(
            gcip_tenant_id="GCIP-T-001",
            provider_type="saml",
            config={
                "entity_id": "urn:acme",
                "sso_url": "https://acme.okta.com/sso",
                "certificate_pem": cert,  # SPA field name
                "display_name": "Acme SSO",
            },
            tenant_manager=mock_mgr,
        )
        _, kwargs = mock_mgr.create_inbound_saml_config.call_args
        assert kwargs["x509_certificates"] == [cert]

    def test_add_oidc_accepts_spa_issuer_url_field(self):
        """SPA sends 'issuer_url' (not 'issuer'); adapter must accept it."""
        from adapters.gcip import add_sso_provider

        mock_mgr = MagicMock()
        mock_mgr.create_oidc_provider_config.return_value = _mock_oidc_config(
            "projects/p/tenants/GCIP-T-001/oauthIdpConfigs/oidc.acme"
        )
        add_sso_provider(
            gcip_tenant_id="GCIP-T-001",
            provider_type="oidc",
            config={
                "issuer_url": "https://acme.okta.com",  # SPA field name
                "client_id": "abc",
                "client_secret": "secret",
                "display_name": "Acme OIDC",
            },
            tenant_manager=mock_mgr,
        )
        _, kwargs = mock_mgr.create_oidc_provider_config.call_args
        assert kwargs["issuer"] == "https://acme.okta.com"

    def test_add_unknown_type_raises(self):
        """add_sso_provider raises ValueError for unsupported provider_type."""
        from adapters.gcip import add_sso_provider

        mock_mgr = MagicMock()

        with pytest.raises(ValueError, match="provider_type"):
            add_sso_provider(
                gcip_tenant_id="GCIP-T-001",
                provider_type="ldap",
                config={},
                tenant_manager=mock_mgr,
            )


# ---------------------------------------------------------------------------
# list_sso_providers
# ---------------------------------------------------------------------------

class TestListSsoProviders:
    def test_returns_combined_saml_and_oidc(self):
        """list_sso_providers returns both SAML and OIDC configs merged."""
        from adapters.gcip import list_sso_providers

        mock_mgr = MagicMock()
        mock_mgr.list_inbound_saml_configs.return_value = MagicMock(
            iterate_all=lambda: [
                _mock_saml_config(
                    "projects/p/tenants/T/inboundSamlConfigs/saml.acme"
                )
            ]
        )
        mock_mgr.list_oidc_provider_configs.return_value = MagicMock(
            iterate_all=lambda: [
                _mock_oidc_config(
                    "projects/p/tenants/T/oauthIdpConfigs/oidc.acme"
                )
            ]
        )

        results = list_sso_providers("GCIP-T-001", tenant_manager=mock_mgr)

        types = {r["type"] for r in results}
        assert "saml" in types
        assert "oidc" in types
        assert len(results) == 2

    def test_returns_empty_when_none_configured(self):
        """list_sso_providers returns [] when no providers exist."""
        from adapters.gcip import list_sso_providers

        mock_mgr = MagicMock()
        mock_mgr.list_inbound_saml_configs.return_value = MagicMock(
            iterate_all=lambda: []
        )
        mock_mgr.list_oidc_provider_configs.return_value = MagicMock(
            iterate_all=lambda: []
        )

        results = list_sso_providers("GCIP-T-001", tenant_manager=mock_mgr)

        assert results == []


# ---------------------------------------------------------------------------
# delete_sso_provider
# ---------------------------------------------------------------------------

class TestDeleteSsoProvider:
    def test_delete_saml_calls_correct_sdk_method(self):
        """delete_sso_provider for saml.* prefix calls delete_inbound_saml_config."""
        from adapters.gcip import delete_sso_provider

        mock_mgr = MagicMock()

        delete_sso_provider("GCIP-T-001", "saml.acme", tenant_manager=mock_mgr)

        mock_mgr.delete_inbound_saml_config.assert_called_once_with(
            "GCIP-T-001", "saml.acme"
        )
        mock_mgr.delete_oidc_provider_config.assert_not_called()

    def test_delete_oidc_calls_correct_sdk_method(self):
        """delete_sso_provider for oidc.* prefix calls delete_oidc_provider_config."""
        from adapters.gcip import delete_sso_provider

        mock_mgr = MagicMock()

        delete_sso_provider("GCIP-T-001", "oidc.acme", tenant_manager=mock_mgr)

        mock_mgr.delete_oidc_provider_config.assert_called_once_with(
            "GCIP-T-001", "oidc.acme"
        )
        mock_mgr.delete_inbound_saml_config.assert_not_called()

    def test_delete_unknown_prefix_raises(self):
        """delete_sso_provider raises ValueError for non-saml/non-oidc idp_id."""
        from adapters.gcip import delete_sso_provider

        mock_mgr = MagicMock()

        with pytest.raises(ValueError, match="idp_id"):
            delete_sso_provider("GCIP-T-001", "ldap.acme", tenant_manager=mock_mgr)
