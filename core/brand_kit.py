"""Brand kit storage helpers (TRD-F5 §6).

Pure-logic functions that wrap GCS operations for brand assets. All GCS clients
are injected by callers so this module is unit-testable without live GCS.

Public API:
  load_brand_kit(tenant_id, db) -> dict | None
      Read the brand dict from tenants.settings["brand"]. Returns None if the
      tenant row is absent or the brand key is not set.

  store_brand_asset(tenant_id, asset_name, local_path, content_type,
                    gcs_client, bucket_name) -> str
      Upload a local file to tenants/{id}/brand/{asset_name} in GCS.
      Returns the gs:// URI of the uploaded object.

  brand_upload_signed_url(tenant_id, asset_name, content_type,
                          gcs_client, bucket_name, ttl_seconds) -> str
      Generate a V4 signed PUT URL for the Admin UI to upload directly to GCS.
      Never streams through Cloud Run.

F5-a's render_job imports load_brand_kit(tenant_id, db) to obtain intro/outro URIs.
F5-c's Admin API calls brand_upload_signed_url() via an endpoint the orchestrator
wires; see endpoint description at module bottom.

Endpoint description for F5-c / orchestrator (DO NOT implement here):
  POST /admin/tenant/brand/upload-url
    Body: {"asset_name": "logo.png", "content_type": "image/png"}
    Response: {"upload_url": "<signed PUT URL>", "gcs_uri": "gs://..."}
    Auth: admin role required.
    Calls: brand_upload_signed_url(tenant_id_from_auth, asset_name, content_type, ...)
"""
from __future__ import annotations

import datetime

from sqlalchemy import text

from core.gcs_path import tenant_object_path


def load_brand_kit(tenant_id: int, db) -> dict | None:
    """Return the brand dict from tenants.settings["brand"], or None.

    Args:
        tenant_id: Numeric tenant ID.
        db:        SQLAlchemy session (platform-level; no RLS filter needed since
                   we're reading from the tenants table which has no RLS).

    Returns:
        The brand dict (may be empty dict {}) or None if not configured.
    """
    row = db.execute(
        text("SELECT settings FROM tenants WHERE id = :tid"),
        {"tid": tenant_id},
    ).fetchone()

    if row is None:
        return None

    settings = row.settings if hasattr(row, "settings") else row[0]
    if not isinstance(settings, dict):
        return None

    return settings.get("brand") or None


def store_brand_asset(
    tenant_id: int,
    asset_name: str,
    local_path: str,
    content_type: str,
    gcs_client,
    bucket_name: str,
) -> str:
    """Upload a local brand asset to GCS under tenants/{tenant_id}/brand/.

    Args:
        tenant_id:    Numeric tenant ID.
        asset_name:   Filename, e.g. "logo.png", "intro.mp4".
        local_path:   Absolute path to the local file to upload.
        content_type: MIME type, e.g. "image/png".
        gcs_client:   google.cloud.storage.Client instance (injected).
        bucket_name:  GCS bucket name.

    Returns:
        ``gs://{bucket_name}/tenants/{tenant_id}/brand/{asset_name}``
    """
    key = tenant_object_path(tenant_id, f"brand/{asset_name}")
    bucket = gcs_client.bucket(bucket_name)
    blob = bucket.blob(key)
    blob.upload_from_filename(local_path, content_type=content_type)
    return f"gs://{bucket_name}/{key}"


def brand_upload_signed_url(
    tenant_id: int,
    asset_name: str,
    content_type: str,
    gcs_client,
    bucket_name: str,
    ttl_seconds: int = 900,
) -> str:
    """Generate a V4 signed PUT URL for direct-to-GCS brand asset upload.

    The Admin UI uses this URL to PUT the file directly to GCS — the payload
    never passes through Cloud Run.

    Args:
        tenant_id:    Numeric tenant ID.
        asset_name:   Target filename under tenants/{id}/brand/, e.g. "logo.png".
        content_type: MIME type of the file being uploaded.
        gcs_client:   google.cloud.storage.Client instance (injected).
        bucket_name:  GCS bucket name.
        ttl_seconds:  Signed URL validity window (default 900 s = 15 min).

    Returns:
        HTTPS signed PUT URL string.
    """
    key = tenant_object_path(tenant_id, f"brand/{asset_name}")
    bucket = gcs_client.bucket(bucket_name)
    blob = bucket.blob(key)
    url = blob.generate_signed_url(
        version="v4",
        expiration=datetime.timedelta(seconds=ttl_seconds),
        method="PUT",
        content_type=content_type,
    )
    return url
