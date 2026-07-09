"""Tenant provisioning logic (TRD-F6 §3.2).

provision_tenant() implements the full provision sequence:
  1. Validate slug uniqueness → SlugConflictError if taken.
  2. INSERT into tenants (status='provisioning').
  3. Seed tenant_settings defaults (brand/kb/marketing/metering_caps sub-objects).
  4. Create GCIP tenant via gcip_client.
  5. INSERT into tenant_gcip_map.
  6. INSERT into tenant_default_admins (admin_email for the new tenant).
  7. Generate invite sign-in link via gcip_client.
  8. UPDATE tenants SET status='active'.
  9. Return {tenant_id, gcip_tenant_id, invite_link}.

Rollback on failure (any step after INSERT):
  - UPDATE tenants SET status='provisioning_failed'.
  - If GCIP tenant was created: delete it via gcip_client.
  - Raise ProvisioningError wrapping the original exception.

SSO helpers (callable logic for /admin/sso/providers routes):
  add_sso_provider(gcip_tenant_id, provider_type, config, gcip_client) -> dict
  list_sso_providers(gcip_tenant_id, gcip_client) -> list[dict]
  remove_sso_provider(gcip_tenant_id, idp_id, gcip_client) -> None
  resend_invite(gcip_tenant_id, admin_email, gcip_client) -> str

The HTTP routes are wired in api/app.py (F6-c scope). This module owns the
callable logic; api/app.py owns only the route registration.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import text

log = logging.getLogger(__name__)

# Default settings seeded into every new tenant (mirrors 0019 seed for tenant 1).
_DEFAULT_SETTINGS: dict = {
    "brand": {
        "logo_gcs_uri": None,
        "primary_color": "#1a3c5e",
        "accent_color": "#f4a226",
        "font_heading": "Montserrat",
        "font_body": "Open Sans",
        "intro_gcs_uri": None,
        "outro_gcs_uri": None,
        "voice_sample_gcs_uri": None,
    },
    "kb": {
        "ingest_enabled": True,
        "abstain_threshold": 0.35,
        "faq_policy": "auto",
        "channel_sources": [],
    },
    "marketing": {
        "caption_prompt_version": "v5",
        "publish_cadence_days": 7,
        "seed_pct": 0.20,
        "social_accounts": {},
        "safety_denylist": [],
        "royalty_free_music_catalog": "pixabay",
    },
    "metering_caps": {
        "llm_tokens_per_month": None,
        "stt_minutes_per_month": None,
        "render_minutes_per_month": None,
    },
    "reminder_cadence_days": [3, 7, 14],
    "deposit": None,
    "license_number": None,
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SlugConflictError(ValueError):
    """Raised when the requested slug is already taken."""

    def __init__(self, slug: str, existing_tenant_id: int | None = None):
        super().__init__(f"Slug {slug!r} is already in use")
        self.slug = slug
        self.existing_tenant_id = existing_tenant_id


class ProvisioningError(RuntimeError):
    """Raised when provisioning fails after INSERT (rollback already applied)."""


# ---------------------------------------------------------------------------
# Main provisioning function
# ---------------------------------------------------------------------------

def provision_tenant(
    name: str,
    slug: str,
    admin_email: str,
    db,
    gcip_client,
) -> dict:
    """Create a new tenant end-to-end.

    Args:
        name:         Display name for the tenant (used as GCIP tenant display_name).
        slug:         URL-safe identifier; must be unique across tenants.
        admin_email:  Email of the first tenant admin (seeded into tenant_default_admins).
        db:           SQLAlchemy session (platform-scoped; no RLS GUC). The caller
                      must commit/rollback — this function does not commit.
        gcip_client:  Object with the adapters.gcip interface:
                        .create_gcip_tenant(name) -> str
                        .delete_gcip_tenant(gcip_tenant_id) -> None
                        .generate_signin_link(gcip_tenant_id, email) -> str

    Returns:
        dict with keys: tenant_id (int), gcip_tenant_id (str), invite_link (str).

    Raises:
        SlugConflictError: slug already exists (no DB row created).
        ProvisioningError: any failure after the INSERT (rollback applied).
    """
    # ── Step 1: Validate slug uniqueness ────────────────────────────────────
    existing = db.execute(
        text("SELECT id FROM tenants WHERE slug = :slug"),
        {"slug": slug},
    ).fetchone()
    if existing is not None:
        raise SlugConflictError(slug, existing_tenant_id=existing[0])

    # ── Step 2: INSERT tenants (status='provisioning') ───────────────────────
    db.execute(
        text(
            "INSERT INTO tenants (name, slug, status, settings) "
            "VALUES (:name, :slug, 'provisioning', :settings)"
        ),
        {"name": name, "slug": slug, "settings": json.dumps(_DEFAULT_SETTINGS)},
    )

    # Fetch the new tenant_id (SQLite / Postgres compatible)
    tenant_row = db.execute(
        text("SELECT id FROM tenants WHERE slug = :slug"),
        {"slug": slug},
    ).fetchone()
    tenant_id: int = tenant_row[0]

    gcip_tenant_id: str | None = None

    try:
        # ── Step 3: Settings already seeded in the INSERT above ─────────────
        # _DEFAULT_SETTINGS is embedded in the INSERT value; no separate step needed.

        # ── Step 4: Create GCIP tenant ───────────────────────────────────────
        gcip_tenant_id = gcip_client.create_gcip_tenant(name)

        # ── Step 5: INSERT tenant_gcip_map ───────────────────────────────────
        db.execute(
            text(
                "INSERT INTO tenant_gcip_map (tenant_id, gcip_tenant) "
                "VALUES (:tid, :gcip)"
            ),
            {"tid": tenant_id, "gcip": gcip_tenant_id},
        )

        # ── Step 6: Seed tenant_default_admins ──────────────────────────────
        db.execute(
            text(
                "INSERT INTO tenant_default_admins (tenant_id, email) "
                "VALUES (:tid, :email)"
            ),
            {"tid": tenant_id, "email": admin_email.lower()},
        )

        # ── Step 7: Generate invite sign-in link ─────────────────────────────
        invite_link = gcip_client.generate_signin_link(gcip_tenant_id, admin_email)

        # ── Step 8: UPDATE tenants SET status='active' ───────────────────────
        db.execute(
            text("UPDATE tenants SET status = 'active' WHERE id = :tid"),
            {"tid": tenant_id},
        )

        log.info(
            "provision_tenant: tenant %d (%s) provisioned; gcip=%s",
            tenant_id, slug, gcip_tenant_id,
        )
        return {
            "tenant_id": tenant_id,
            "gcip_tenant_id": gcip_tenant_id,
            "invite_link": invite_link,
        }

    except Exception as exc:
        # ── Rollback ─────────────────────────────────────────────────────────
        log.error(
            "provision_tenant: failed for slug=%s tenant_id=%s gcip=%s: %s",
            slug, tenant_id, gcip_tenant_id, exc,
        )
        try:
            failed_settings = {**_DEFAULT_SETTINGS, "provisioning_error": str(exc)}
            db.execute(
                text(
                    "UPDATE tenants SET status = 'provisioning_failed', settings = :s "
                    "WHERE id = :tid"
                ),
                {"s": json.dumps(failed_settings), "tid": tenant_id},
            )
        except Exception as rollback_exc:
            log.error("provision_tenant: status rollback failed: %s", rollback_exc)

        if gcip_tenant_id is not None:
            try:
                gcip_client.delete_gcip_tenant(gcip_tenant_id)
            except Exception as gcip_del_exc:
                log.error(
                    "provision_tenant: GCIP rollback delete failed for %s: %s",
                    gcip_tenant_id, gcip_del_exc,
                )

        raise ProvisioningError(f"Provisioning failed for slug={slug!r}: {exc}") from exc


# ---------------------------------------------------------------------------
# SSO helpers (callable logic for /admin/sso/providers routes)
# ---------------------------------------------------------------------------

def add_sso_provider(
    gcip_tenant_id: str,
    provider_type: str,
    config: dict,
    gcip_client,
) -> dict:
    """Add a SAML or OIDC IdP to a GCIP tenant.

    Delegates to gcip_client.add_sso_provider. Raises ValueError for unknown
    provider_type (validated here before calling the adapter).

    Returns dict with keys: idp_id, type.
    """
    if provider_type not in ("saml", "oidc"):
        raise ValueError(
            f"provider_type must be 'saml' or 'oidc', got {provider_type!r}"
        )
    return gcip_client.add_sso_provider(gcip_tenant_id, provider_type, config)


def list_sso_providers(gcip_tenant_id: str, gcip_client) -> list[dict]:
    """List all configured SSO providers for a GCIP tenant."""
    return gcip_client.list_sso_providers(gcip_tenant_id)


def remove_sso_provider(gcip_tenant_id: str, idp_id: str, gcip_client) -> None:
    """Remove an SSO provider from a GCIP tenant."""
    gcip_client.delete_sso_provider(gcip_tenant_id, idp_id)


def resend_invite(gcip_tenant_id: str, admin_email: str, gcip_client) -> str:
    """Generate a new invite sign-in link for an existing tenant admin.

    Returns the new invite link string.
    """
    return gcip_client.generate_signin_link(gcip_tenant_id, admin_email)
