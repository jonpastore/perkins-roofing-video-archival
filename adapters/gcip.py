"""GCIP (Firebase Identity Platform) adapter — thin wrappers over firebase_admin.

All public functions accept injectable client/manager arguments so tests can
mock without touching the real SDK. The real SDK is only imported at call time
(lazy) so the module is importable in test environments without firebase_admin
credentials.

firebase-admin>=7.5 is required (pinned in app/requirements.txt). That version
supports auth.Client(...).tenant_manager() and all multi-tenant operations used
here. No version-specific fallbacks are needed or provided.

Public API:
  create_gcip_tenant(display_name, *, tenant_manager=None) -> str
  delete_gcip_tenant(gcip_tenant_id, *, tenant_manager=None) -> None
  generate_signin_link(gcip_tenant_id, email, *, tenant_auth=None) -> str
  add_sso_provider(gcip_tenant_id, provider_type, config, *, tenant_manager=None) -> dict
  list_sso_providers(gcip_tenant_id, *, tenant_manager=None) -> list[dict]
  delete_sso_provider(gcip_tenant_id, idp_id, *, tenant_manager=None) -> None
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_DEFAULT_CONTINUE_URL = "https://app.perkinsroofing.net/signin"

_VALID_PROVIDER_TYPES = ("saml", "oidc")


# ---------------------------------------------------------------------------
# Internal: lazy SDK helpers
# ---------------------------------------------------------------------------

def _get_tenant_manager(tenant_manager=None):
    """Return the injected manager, or build one from the default Firebase app."""
    if tenant_manager is not None:
        return tenant_manager
    import firebase_admin
    from firebase_admin import auth
    return auth.Client(firebase_admin.get_app()).tenant_manager()


def _get_tenant_auth(gcip_tenant_id: str, tenant_auth=None):
    """Return the injected tenant-scoped auth client, or build one from the default app."""
    if tenant_auth is not None:
        return tenant_auth
    import firebase_admin
    from firebase_admin import auth
    return auth.Client(firebase_admin.get_app()).tenant_manager().auth_for_tenant(gcip_tenant_id)


# ---------------------------------------------------------------------------
# Tenant lifecycle
# ---------------------------------------------------------------------------

def create_gcip_tenant(display_name: str, *, tenant_manager=None) -> str:
    """Create a GCIP multi-tenant tenant and return its tenant_id string.

    Enables email-link (passwordless) sign-in for the invite flow per TRD-F6 §3.2.
    Raises any firebase_admin exception on failure — caller handles rollback.
    """
    mgr = _get_tenant_manager(tenant_manager)
    tenant = mgr.create_tenant(
        display_name=display_name,
        enable_email_link_sign_in=True,
        email_privacy_config={"enable_improved_email_privacy": True},
    )
    log.info("gcip: created tenant %s (%s)", tenant.tenant_id, display_name)
    return tenant.tenant_id


def delete_gcip_tenant(gcip_tenant_id: str, *, tenant_manager=None) -> None:
    """Delete a GCIP tenant by its tenant_id.

    Used by provision_tenant() rollback and by offboard_tenant() (replacing the F5 stub).
    Raises any firebase_admin exception on failure.
    """
    mgr = _get_tenant_manager(tenant_manager)
    mgr.delete_tenant(gcip_tenant_id)
    log.info("gcip: deleted tenant %s", gcip_tenant_id)


# ---------------------------------------------------------------------------
# Invite link
# ---------------------------------------------------------------------------

def generate_signin_link(
    gcip_tenant_id: str,
    email: str,
    *,
    tenant_auth=None,
    continue_url: str = _DEFAULT_CONTINUE_URL,
) -> str:
    """Generate a passwordless email sign-in link for a new admin invite.

    The link embeds the GCIP tenantId so the SPA sign-in flow picks up the
    correct tenant context (TRD-F4 §4.3).

    Returns the full sign-in-with-email-link URL string.
    """
    from firebase_admin.auth import ActionCodeSettings
    ta = _get_tenant_auth(gcip_tenant_id, tenant_auth)
    settings = ActionCodeSettings(url=continue_url)
    link = ta.generate_sign_in_with_email_link(email, settings)
    log.info("gcip: generated sign-in link for %s in tenant %s", email, gcip_tenant_id)
    return link


# ---------------------------------------------------------------------------
# SSO provider management (SAML / OIDC)
# ---------------------------------------------------------------------------

def add_sso_provider(
    gcip_tenant_id: str,
    provider_type: str,
    config: dict,
    *,
    tenant_manager=None,
) -> dict:
    """Add a SAML or OIDC IdP to a GCIP tenant.

    Args:
        gcip_tenant_id: Target GCIP tenant.
        provider_type:  "saml" or "oidc".
        config:
          SAML keys: entity_id, sso_url, certificate, display_name, idp_id
          OIDC keys: issuer, client_id, client_secret, display_name, idp_id

    Returns:
        dict with keys: idp_id, type, display_name.

    Raises:
        ValueError: if provider_type is not "saml" or "oidc".
    """
    if provider_type not in _VALID_PROVIDER_TYPES:
        raise ValueError(
            f"provider_type must be one of {_VALID_PROVIDER_TYPES!r}, got {provider_type!r}"
        )

    mgr = _get_tenant_manager(tenant_manager)

    if provider_type == "saml":
        # SPA sends 'certificate_pem'; the SDK-native key is 'certificate'. Accept both.
        certificate = config.get("certificate") or config["certificate_pem"]
        result = mgr.create_inbound_saml_config(
            tenant_id=gcip_tenant_id,
            display_name=config.get("display_name", ""),
            enabled=True,
            idp_entity_id=config["entity_id"],
            sso_url=config["sso_url"],
            x509_certificates=[certificate],
            rp_entity_id=config.get("idp_id", ""),
            callback_url=_DEFAULT_CONTINUE_URL,
        )
        idp_id = config.get("idp_id") or result.name.rsplit("/", 1)[-1]
        log.info("gcip: added SAML provider %s to tenant %s", idp_id, gcip_tenant_id)
        return {"idp_id": idp_id, "type": "saml", "display_name": config.get("display_name", "")}

    # provider_type == "oidc"
    # SPA sends 'issuer_url'; the SDK-native key is 'issuer'. Accept both.
    issuer = config.get("issuer") or config["issuer_url"]
    result = mgr.create_oidc_provider_config(
        tenant_id=gcip_tenant_id,
        display_name=config.get("display_name", ""),
        enabled=True,
        client_id=config["client_id"],
        client_secret=config.get("client_secret"),
        issuer=issuer,
        id_token_response_type=True,
    )
    idp_id = config.get("idp_id") or result.name.rsplit("/", 1)[-1]
    log.info("gcip: added OIDC provider %s to tenant %s", idp_id, gcip_tenant_id)
    return {"idp_id": idp_id, "type": "oidc", "display_name": config.get("display_name", "")}


def list_sso_providers(gcip_tenant_id: str, *, tenant_manager=None) -> list[dict]:
    """List all configured SSO IdPs (SAML + OIDC) for a GCIP tenant.

    Returns list of dicts with keys: idp_id, type, display_name.
    """
    mgr = _get_tenant_manager(tenant_manager)
    results: list[dict] = []

    for cfg in mgr.list_inbound_saml_configs(tenant_id=gcip_tenant_id).iterate_all():
        idp_id = cfg.name.rsplit("/", 1)[-1]
        results.append({"idp_id": idp_id, "type": "saml", "display_name": cfg.display_name})

    for cfg in mgr.list_oidc_provider_configs(tenant_id=gcip_tenant_id).iterate_all():
        idp_id = cfg.name.rsplit("/", 1)[-1]
        results.append({"idp_id": idp_id, "type": "oidc", "display_name": cfg.display_name})

    return results


def delete_sso_provider(
    gcip_tenant_id: str,
    idp_id: str,
    *,
    tenant_manager=None,
) -> None:
    """Delete a SAML or OIDC provider from a GCIP tenant.

    idp_id prefix selects the SDK call:
      "saml.*" → delete_inbound_saml_config
      "oidc.*" → delete_oidc_provider_config

    Raises:
        ValueError: if idp_id doesn't start with "saml." or "oidc.".
    """
    if idp_id.startswith("saml."):
        provider_type = "saml"
    elif idp_id.startswith("oidc."):
        provider_type = "oidc"
    else:
        raise ValueError(f"idp_id must start with 'saml.' or 'oidc.', got {idp_id!r}")

    mgr = _get_tenant_manager(tenant_manager)

    if provider_type == "saml":
        mgr.delete_inbound_saml_config(gcip_tenant_id, idp_id)
    else:
        mgr.delete_oidc_provider_config(gcip_tenant_id, idp_id)

    log.info("gcip: deleted %s provider %s from tenant %s", provider_type, idp_id, gcip_tenant_id)
