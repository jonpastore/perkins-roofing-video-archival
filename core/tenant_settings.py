"""Tenant settings — authoritative Pydantic representation of tenants.settings JSONB.

TRD-F5 §2.1 + TRD-F0 §3a-1.

Key contracts:
- model_config extra="allow": unknown keys from future waves are preserved on
  round-trip. Writers must NEVER do a wholesale replace that discards keys they
  don't own.
- F3 keys (deposit / reminder_cadence_days / license_number) are top-level, not
  nested under brand/kb/marketing.
- Wrong-type values raise ValidationError immediately — no silent fallback to
  defaults, which would mask data corruption.
- TenantSettings.load(d) is a convenience alias for TenantSettings(**d).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class DepositPolicy(BaseModel):
    """F3 — deposit requirement for proposals.

    Defined here (not in core/proposal.py) to avoid a circular import and to
    serve as the Pydantic type for TenantSettings. The domain error class
    DepositPolicyError lives in core/proposal.py and is unrelated to this model.
    """

    model_config = ConfigDict(extra="allow")

    mode: str  # "percent" | "fixed"
    value: float


class BrandSettings(BaseModel):
    """Brand kit sub-model (TRD-F5 §2.1)."""

    model_config = ConfigDict(extra="allow")

    logo_gcs_uri: str | None = None
    primary_color: str | None = None
    accent_color: str | None = None
    font_heading: str | None = None
    font_body: str | None = None
    intro_gcs_uri: str | None = None
    outro_gcs_uri: str | None = None
    voice_sample_gcs_uri: str | None = None


class KbSettings(BaseModel):
    """Knowledge Base admin sub-model (TRD-F5 §2.1)."""

    model_config = ConfigDict(extra="allow")

    ingest_enabled: bool = True
    abstain_threshold: float = 0.35
    faq_policy: str = "auto"
    channel_sources: list[str] = []


class MarketingSettings(BaseModel):
    """Marketing admin sub-model (TRD-F5 §2.1)."""

    model_config = ConfigDict(extra="allow")

    caption_prompt_version: str = "v5"
    publish_cadence_days: int = 7
    seed_pct: float = 0.20
    social_accounts: dict[str, Any] = {}
    safety_denylist: list[str] = []
    royalty_free_music_catalog: str = "pixabay"


class MeteringCaps(BaseModel):
    """Per-tenant soft caps for metered resources (TRD-F5 §5.1)."""

    model_config = ConfigDict(extra="allow")

    llm_tokens_per_month: int | None = None
    stt_minutes_per_month: float | None = None
    render_minutes_per_month: float | None = None


# ---------------------------------------------------------------------------
# Top-level settings model
# ---------------------------------------------------------------------------

class TenantSettings(BaseModel):
    """Authoritative Pydantic form of tenants.settings JSONB.

    Registered keys (TRD-F0 §3a-1):
      F3:  deposit, reminder_cadence_days, license_number
      F5:  brand, kb, marketing, metering_caps

    extra="allow" preserves unknown keys from future waves without dropping them.
    """

    model_config = ConfigDict(extra="allow")

    # F3 keys — top-level, not nested
    deposit: DepositPolicy | None = None
    reminder_cadence_days: list[int] = [3, 7, 14]
    license_number: str | None = None

    # F5 keys
    brand: BrandSettings | None = None
    kb: KbSettings | None = None
    marketing: MarketingSettings | None = None
    metering_caps: MeteringCaps | None = None

    @classmethod
    def load(cls, settings_dict: dict[str, Any]) -> "TenantSettings":
        """Parse a settings dict from the DB. Alias for TenantSettings(**d).

        Raises ValidationError on structural type errors — no silent fallback.
        """
        return cls(**settings_dict)
