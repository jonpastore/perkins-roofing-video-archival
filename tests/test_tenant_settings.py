"""Tests for core/tenant_settings.py — TDD: write red first, implement to green.

Tests for TenantSettings Pydantic model and gcs_path utility are co-located here
per the F5 test plan (§12).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# TenantSettings tests
# ---------------------------------------------------------------------------

def test_tenant_settings_defaults_for_missing_keys():
    """Missing top-level sections produce None / list defaults, not errors."""
    from core.tenant_settings import TenantSettings

    ts = TenantSettings()
    assert ts.brand is None
    assert ts.kb is None
    assert ts.marketing is None
    assert ts.metering_caps is None
    assert ts.deposit is None
    assert ts.reminder_cadence_days == [3, 7, 14]
    assert ts.license_number is None


def test_tenant_settings_parses_brand_section():
    """Brand sub-model parses colors and URIs correctly."""
    from core.tenant_settings import TenantSettings

    data = {
        "brand": {
            "primary_color": "#1a3c5e",
            "accent_color": "#f4a226",
            "logo_gcs_uri": "gs://bucket/tenants/1/brand/logo.png",
            "font_heading": "Montserrat",
            "font_body": "Open Sans",
        }
    }
    ts = TenantSettings(**data)
    assert ts.brand is not None
    assert ts.brand.primary_color == "#1a3c5e"
    assert ts.brand.logo_gcs_uri == "gs://bucket/tenants/1/brand/logo.png"


def test_tenant_settings_parses_kb_section():
    """KB sub-model parses ingest_enabled and thresholds."""
    from core.tenant_settings import TenantSettings

    data = {
        "kb": {
            "ingest_enabled": True,
            "abstain_threshold": 0.35,
            "faq_policy": "auto",
            "channel_sources": ["UCxxxxxxxx"],
        }
    }
    ts = TenantSettings(**data)
    assert ts.kb is not None
    assert ts.kb.ingest_enabled is True
    assert ts.kb.abstain_threshold == 0.35
    assert ts.kb.channel_sources == ["UCxxxxxxxx"]


def test_tenant_settings_parses_marketing_section():
    """Marketing sub-model parses cadence and seed_pct."""
    from core.tenant_settings import TenantSettings

    data = {
        "marketing": {
            "caption_prompt_version": "v5",
            "publish_cadence_days": 7,
            "seed_pct": 0.20,
        }
    }
    ts = TenantSettings(**data)
    assert ts.marketing is not None
    assert ts.marketing.publish_cadence_days == 7
    assert ts.marketing.seed_pct == pytest.approx(0.20)


def test_tenant_settings_parses_metering_caps():
    """Metering caps section parses correctly."""
    from core.tenant_settings import TenantSettings

    data = {
        "metering_caps": {
            "llm_tokens_per_month": 5_000_000,
            "stt_minutes_per_month": 500.0,
            "render_minutes_per_month": 120.0,
        }
    }
    ts = TenantSettings(**data)
    assert ts.metering_caps is not None
    assert ts.metering_caps.llm_tokens_per_month == 5_000_000
    assert ts.metering_caps.stt_minutes_per_month == pytest.approx(500.0)


def test_tenant_settings_f3_keys_at_top_level():
    """F3 keys deposit / reminder_cadence_days / license_number are top-level."""
    from core.tenant_settings import TenantSettings

    data = {
        "deposit": {"mode": "percent", "value": 25.0},
        "reminder_cadence_days": [3, 7, 14],
        "license_number": "CA-12345",
    }
    ts = TenantSettings(**data)
    assert ts.deposit is not None
    assert ts.deposit.mode == "percent"
    assert ts.deposit.value == pytest.approx(25.0)
    assert ts.reminder_cadence_days == [3, 7, 14]
    assert ts.license_number == "CA-12345"


def test_f3_settings_keys_preserved_through_f5_admin_model():
    """Write tenants.settings with F3 keys via TenantSettings; read back; confirm
    deposit/reminder_cadence_days/license_number are unchanged (the F3 A2 critic finding)."""
    from core.tenant_settings import TenantSettings

    original = {
        "deposit": {"mode": "fixed", "value": 500.0},
        "reminder_cadence_days": [5, 10],
        "license_number": "TX-99999",
        "brand": {"primary_color": "#ffffff"},
    }
    ts = TenantSettings(**original)
    dumped = ts.model_dump(exclude_none=False)

    # Re-parse the round-tripped dict
    ts2 = TenantSettings(**{k: v for k, v in dumped.items() if v is not None})
    assert ts2.deposit is not None
    assert ts2.deposit.mode == "fixed"
    assert ts2.deposit.value == pytest.approx(500.0)
    assert ts2.reminder_cadence_days == [5, 10]
    assert ts2.license_number == "TX-99999"


def test_tenant_settings_unknown_keys_preserved():
    """extra='allow' — unknown keys from future waves round-trip without loss."""
    from core.tenant_settings import TenantSettings

    data = {"future_wave_key": {"some": "config"}, "another_unknown": 42}
    ts = TenantSettings(**data)
    dumped = ts.model_dump()
    assert dumped.get("future_wave_key") == {"some": "config"}
    assert dumped.get("another_unknown") == 42


def test_tenant_settings_invalid_deposit_mode_raises():
    """Wrong type for deposit.mode raises ValidationError — no silent fallback."""
    from core.tenant_settings import TenantSettings

    with pytest.raises(ValidationError):
        TenantSettings(deposit={"mode": 123, "value": 25.0})


def test_tenant_settings_load_from_dict():
    """TenantSettings.load(d) is an alias for TenantSettings(**d)."""
    from core.tenant_settings import TenantSettings

    d = {"license_number": "OR-5678"}
    ts = TenantSettings.load(d)
    assert ts.license_number == "OR-5678"


# ---------------------------------------------------------------------------
# gcs_path tests (co-located per §12)
# ---------------------------------------------------------------------------

def test_gcs_path_tenant_prefix():
    """Non-tenant-1 paths are always tenants/{id}/{relative}."""
    from core.gcs_path import tenant_object_path

    result = tenant_object_path(2, "brand/logo.png")
    assert result == "tenants/2/brand/logo.png"


def test_gcs_path_tenant1_returns_tenanted_path():
    """tenant_object_path for tenant 1 returns the tenanted path (shim is GCS-check based)."""
    from core.gcs_path import tenant_object_path

    result = tenant_object_path(1, "brand/logo.png")
    # Must start with tenants/1/ — the shim only falls back when GCS object is absent
    assert result == "tenants/1/brand/logo.png"


def test_gcs_path_tenant1_legacy_fallback(monkeypatch):
    """For tenant 1, fall back to the legacy root path when a gcs_client says the
    tenanted object does not exist."""
    from core.gcs_path import tenant_object_path_with_fallback

    class FakeClient:
        def bucket(self, name):
            return self

        def blob(self, key):
            return self

        def exists(self):
            return False  # tenanted path does not exist

    result = tenant_object_path_with_fallback(1, "videos/abc/video.mp4", FakeClient(), bucket="mybucket")
    assert result == "videos/abc/video.mp4"


def test_gcs_path_tenant1_uses_tenanted_when_exists(monkeypatch):
    """For tenant 1, use tenants/1/... when GCS says the tenanted object exists."""
    from core.gcs_path import tenant_object_path_with_fallback

    class FakeClient:
        def bucket(self, name):
            return self

        def blob(self, key):
            self._last_key = key
            return self

        def exists(self):
            return True

    result = tenant_object_path_with_fallback(1, "videos/abc/video.mp4", FakeClient(), bucket="mybucket")
    assert result == "tenants/1/videos/abc/video.mp4"


def test_gcs_path_non_tenant1_no_fallback():
    """For non-tenant-1 IDs the simple function always returns the prefixed path."""
    from core.gcs_path import tenant_object_path

    assert tenant_object_path(5, "renders/out.mp4") == "tenants/5/renders/out.mp4"
    assert tenant_object_path(100, "brand/voice.wav") == "tenants/100/brand/voice.wav"


def test_gcs_path_with_fallback_non_tenant1_skips_gcs_check():
    """tenant_object_path_with_fallback for non-tenant-1 never hits GCS."""
    from core.gcs_path import tenant_object_path_with_fallback

    mock_gcs = MagicMock()
    result = tenant_object_path_with_fallback(7, "brand/logo.png", mock_gcs, bucket="b")
    assert result == "tenants/7/brand/logo.png"
    mock_gcs.bucket.assert_not_called()


def test_gcs_path_with_fallback_gcs_error_returns_tenanted():
    """On GCS error, tenant_object_path_with_fallback falls back to tenanted path."""
    from core.gcs_path import tenant_object_path_with_fallback

    class ErrorClient:
        def bucket(self, name):
            raise RuntimeError("GCS unavailable")

    result = tenant_object_path_with_fallback(1, "brand/logo.png", ErrorClient(), bucket="b")
    assert result == "tenants/1/brand/logo.png"
