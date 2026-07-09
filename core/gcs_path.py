"""GCS per-tenant path utilities (TRD-F5 §8).

All new GCS writes in F5+ must go through tenant_object_path() so that the
CI grep gate catches any direct bucket.blob() calls that bypass tenant prefixing.

Public API:
  tenant_object_path(tenant_id, relative_path) -> str
      Returns "tenants/{tenant_id}/{relative_path}" for all tenants.
      For tenant 1 this is the *new* tenanted path; existing legacy objects
      under the bucket root are handled by tenant_object_path_with_fallback().

  tenant_object_path_with_fallback(tenant_id, relative_path, gcs_client, bucket)
      -> str
      For tenant 1 only: checks whether the tenanted path exists in GCS; if not,
      falls back to the legacy root path (relative_path as-is). This backward-compat
      shim is removed in a future cleanup wave after a bulk copy job is run.
      For tenant_id != 1, always returns the tenanted path (no GCS check needed).

      The GCS check is an existence probe; the caller supplies the client and
      bucket so this module stays free of I/O singletons.

Design note (TRD-F5 §2.3):
  Existing Perkins videos are at the bucket root (e.g. "videos/abc123/…").
  New writes use "tenants/1/…". The shim bridges the gap during the transition
  period. It is not applied to non-Perkins tenants (id > 1) which always write
  under tenants/{id}/ from creation.
"""
from __future__ import annotations


def tenant_object_path(tenant_id: int, relative_path: str) -> str:
    """Return the GCS object path for a tenant-scoped asset.

    Always returns ``tenants/{tenant_id}/{relative_path}``.
    For tenant 1, this is the *intended* new path; use
    ``tenant_object_path_with_fallback`` when reading an object that may
    exist only at the legacy root.

    Args:
        tenant_id:     Numeric tenant ID.
        relative_path: Path relative to the tenant prefix, e.g. "brand/logo.png".

    Returns:
        Full GCS object key, e.g. "tenants/1/brand/logo.png".
    """
    return f"tenants/{tenant_id}/{relative_path}"


def tenant_object_path_with_fallback(
    tenant_id: int,
    relative_path: str,
    gcs_client,
    bucket: str,
) -> str:
    """Return the GCS object path, falling back to legacy root for tenant 1.

    For tenant_id == 1:
      - Checks whether ``tenants/1/{relative_path}`` exists in GCS.
      - If it exists, returns the tenanted path.
      - If it does not exist, returns ``relative_path`` (the legacy root path).

    For all other tenant IDs:
      - Always returns ``tenants/{tenant_id}/{relative_path}`` (no GCS check).

    Args:
        tenant_id:     Numeric tenant ID.
        relative_path: Path relative to the tenant prefix.
        gcs_client:    A GCS client object with a ``bucket(name)`` method.
                       The returned bucket object must support ``blob(key).exists()``.
        bucket:        GCS bucket name.

    Returns:
        The resolved GCS object key.
    """
    tenanted = tenant_object_path(tenant_id, relative_path)

    if tenant_id != 1:
        return tenanted

    # Tenant 1 legacy shim: probe for existence of the tenanted path.
    try:
        exists = gcs_client.bucket(bucket).blob(tenanted).exists()
    except Exception:
        # On any GCS error, default to the tenanted path to avoid masking bugs.
        return tenanted

    return tenanted if exists else relative_path
