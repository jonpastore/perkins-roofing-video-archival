"""Tests for core/brand_kit.py — TDD red-first.

GCS calls are mocked throughout; no live GCS access in unit tests.
"""
from __future__ import annotations

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# load_brand_kit
# ---------------------------------------------------------------------------

def test_load_brand_kit_returns_none_when_no_brand_settings():
    """load_brand_kit returns None when tenant has no 'brand' key in settings."""
    from core.brand_kit import load_brand_kit

    mock_db = MagicMock()
    mock_tenant = MagicMock()
    mock_tenant.settings = {}
    mock_db.execute.return_value.fetchone.return_value = mock_tenant

    result = load_brand_kit(1, db=mock_db)
    assert result is None


def test_load_brand_kit_returns_brand_dict_when_present():
    """load_brand_kit returns the brand dict from tenant settings."""
    from core.brand_kit import load_brand_kit

    brand_data = {
        "logo_gcs_uri": "gs://bucket/tenants/1/brand/logo.png",
        "primary_color": "#1a3c5e",
        "accent_color": "#f4a226",
    }
    mock_db = MagicMock()
    mock_tenant = MagicMock()
    mock_tenant.settings = {"brand": brand_data}
    mock_db.execute.return_value.fetchone.return_value = mock_tenant

    result = load_brand_kit(1, db=mock_db)
    assert result == brand_data


def test_load_brand_kit_none_when_tenant_not_found():
    """load_brand_kit returns None when the tenant row does not exist."""
    from core.brand_kit import load_brand_kit

    mock_db = MagicMock()
    mock_db.execute.return_value.fetchone.return_value = None

    result = load_brand_kit(99, db=mock_db)
    assert result is None


# ---------------------------------------------------------------------------
# store_brand_asset
# ---------------------------------------------------------------------------

def test_store_brand_asset_uploads_to_correct_path():
    """store_brand_asset writes to tenants/{id}/brand/{asset_name}."""
    from core.brand_kit import store_brand_asset

    mock_gcs = MagicMock()
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    mock_gcs.bucket.return_value = mock_bucket
    mock_bucket.blob.return_value = mock_blob

    store_brand_asset(
        tenant_id=2,
        asset_name="logo.png",
        local_path="/tmp/logo.png",
        content_type="image/png",
        gcs_client=mock_gcs,
        bucket_name="mybucket",
    )

    mock_gcs.bucket.assert_called_once_with("mybucket")
    mock_bucket.blob.assert_called_once_with("tenants/2/brand/logo.png")
    mock_blob.upload_from_filename.assert_called_once_with("/tmp/logo.png", content_type="image/png")


def test_store_brand_asset_returns_gcs_uri():
    """store_brand_asset returns a gs:// URI."""
    from core.brand_kit import store_brand_asset

    mock_gcs = MagicMock()
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    mock_gcs.bucket.return_value = mock_bucket
    mock_bucket.blob.return_value = mock_blob

    uri = store_brand_asset(
        tenant_id=1,
        asset_name="intro.mp4",
        local_path="/tmp/intro.mp4",
        content_type="video/mp4",
        gcs_client=mock_gcs,
        bucket_name="mybucket",
    )

    assert uri == "gs://mybucket/tenants/1/brand/intro.mp4"


# ---------------------------------------------------------------------------
# brand_upload_signed_url
# ---------------------------------------------------------------------------

def test_brand_upload_signed_url_returns_url():
    """brand_upload_signed_url returns a signed PUT URL for the correct GCS path."""

    from core.brand_kit import brand_upload_signed_url

    mock_gcs = MagicMock()
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    mock_gcs.bucket.return_value = mock_bucket
    mock_bucket.blob.return_value = mock_blob
    mock_blob.generate_signed_url.return_value = "https://storage.googleapis.com/signed"

    url = brand_upload_signed_url(
        tenant_id=3,
        asset_name="voice.wav",
        content_type="audio/wav",
        gcs_client=mock_gcs,
        bucket_name="mybucket",
        ttl_seconds=900,
    )

    assert url == "https://storage.googleapis.com/signed"
    mock_bucket.blob.assert_called_once_with("tenants/3/brand/voice.wav")
    call_kwargs = mock_blob.generate_signed_url.call_args
    assert call_kwargs.kwargs.get("method") == "PUT" or call_kwargs[1].get("method") == "PUT"


def test_brand_upload_signed_url_correct_path_tenant1():
    """brand_upload_signed_url uses tenants/1/brand/ path for tenant 1."""
    from core.brand_kit import brand_upload_signed_url

    mock_gcs = MagicMock()
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    mock_gcs.bucket.return_value = mock_bucket
    mock_bucket.blob.return_value = mock_blob
    mock_blob.generate_signed_url.return_value = "https://signed-url"

    brand_upload_signed_url(
        tenant_id=1,
        asset_name="logo.png",
        content_type="image/png",
        gcs_client=mock_gcs,
        bucket_name="mybucket",
    )

    mock_bucket.blob.assert_called_once_with("tenants/1/brand/logo.png")


def test_load_brand_kit_non_dict_settings_returns_none():
    """load_brand_kit returns None when settings column is not a dict (data corruption guard)."""
    from core.brand_kit import load_brand_kit

    mock_db = MagicMock()
    mock_row = MagicMock()
    # settings attr returns a non-dict value
    mock_row.settings = "corrupted-string"
    mock_db.execute.return_value.fetchone.return_value = mock_row

    result = load_brand_kit(1, db=mock_db)
    assert result is None
