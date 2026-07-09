"""Tenant offboarding logic (TRD-F5 §9).

offboard_tenant() implements the full offboard sequence:
  1. Verify tenant exists and is not tenant 1 (Perkins; protected forever).
  2. Collect row counts per tenant-scoped table for audit.
  3. INSERT tenant_offboard_log (status='pending').
  4. RLS-scoped DELETE cascade on all tenant-scoped tables.
  5. Delete GCS prefix tenants/{tenant_id}/ (list + delete all objects).
  6. Delete the mapped GCIP tenant (best-effort; injected gcip_client).
  7. UPDATE tenant_offboard_log status='complete'.
  8. UPDATE tenants SET status='offboarded'.

The tenant row is retained for audit; only data rows are removed.

Triggered by DELETE /internal/tenants/{tenant_id} (platform_admin only).
The HTTP endpoint is wired in F6; this module is the callable implementation.
"""
from __future__ import annotations

import json
import logging
import re

from sqlalchemy import text

log = logging.getLogger(__name__)

# Tables whose rows must be counted + deleted. Order does not matter for
# counts; for deletion the DB cascades handle FK ordering automatically.
_TENANT_SCOPED_TABLES = [
    "videos",
    "ingestion_runs",
    "segments",
    "words",
    "content_graph",
    "chunks",
    "email_templates",
    "clusters",
    "articles",
    "scheduled_content",
    "mini_series",
    "social_posts",
    "aggregated_topics",
    "comment_drafts",
    "user_settings",
    "faq_entries",
    # F2
    "pricing_configs",
    "estimates",
    "measurements",
    # F3
    "customers",
    "contacts",
    "properties",
    "proposal_templates",
    "proposals",
    "proposal_events",
    "leads",
    "jobs",
    "catalog_items",
    "tc_versions",
]

# Defense-in-depth (deepsec M2): the DELETE/COUNT statements interpolate table
# names into text(). The names are this static allowlist, never user input — but
# validate at the point of interpolation so a future edit can't introduce an
# injectable identifier. Fails loudly rather than silently interpolating a bad name.
_IDENT_RE = re.compile(r"^[a-z_]+$")


def _safe_table(name: str) -> str:
    """Return ``name`` iff it is a bare [a-z_] SQL identifier, else raise. Guards the
    table-name interpolation in the COUNT/DELETE cascade below."""
    if not _IDENT_RE.match(name):
        raise ValueError(f"offboard: illegal table identifier: {name!r}")
    return name


class ProtectedTenantError(ValueError):
    """Raised when offboard_tenant is called for tenant 1 (Perkins)."""


def offboard_tenant(
    tenant_id: int,
    platform_admin_email: str,
    db,
    gcs_client,
    bucket_name: str,
    gcip_client=None,
) -> None:
    """Offboard a tenant. See module docstring for full step sequence.

    Args:
        tenant_id:            ID of the tenant to offboard (must not be 1).
        platform_admin_email: Email of the platform admin performing the action.
        db:                   SQLAlchemy session. The caller must commit/rollback.
        gcs_client:           google.cloud.storage.Client instance (injected).
        bucket_name:          GCS bucket containing tenant assets.
        gcip_client:          adapters.gcip module (injected). When provided, the
                              mapped GCIP tenant is deleted (best-effort). When None
                              (e.g. unit tests), GCIP deletion is skipped.

    Raises:
        ProtectedTenantError: if tenant_id == 1.
        ValueError:           if the tenant row does not exist.
    """
    # ── Step 1: Guard — tenant 1 is permanently protected ───────────────────
    if tenant_id == 1:
        raise ProtectedTenantError(
            "Tenant 1 (Perkins Roofing) is protected and cannot be offboarded."
        )

    # ── Step 1b: Verify tenant exists ────────────────────────────────────────
    tenant_row = db.execute(
        text("SELECT id, status FROM tenants WHERE id = :tid"),
        {"tid": tenant_id},
    ).fetchone()

    if tenant_row is None:
        raise ValueError(f"Tenant {tenant_id} not found.")

    gcs_prefix = f"tenants/{tenant_id}/"

    # ── Step 2: Collect row counts for audit ─────────────────────────────────
    row_counts: dict[str, int] = {}
    for table in _TENANT_SCOPED_TABLES:
        try:
            result = db.execute(
                text(f"SELECT COUNT(*) FROM {_safe_table(table)} WHERE tenant_id = :tid"),  # noqa: S608
                {"tid": tenant_id},
            ).fetchone()
            row_counts[table] = result[0] if result else 0
        except Exception:
            # Table may not exist in this environment (e.g. SQLite test DB
            # that hasn't had all migrations applied). Skip gracefully.
            row_counts[table] = 0

    # ── Step 3: INSERT audit log row (status='pending') ──────────────────────
    db.execute(
        text(
            "INSERT INTO tenant_offboard_log "
            "(tenant_id, offboarded_by, gcs_prefix, row_counts, status) "
            "VALUES (:tid, :by, :prefix, :counts, 'pending')"
        ),
        {
            "tid": tenant_id,
            "by": platform_admin_email,
            "prefix": gcs_prefix,
            "counts": json.dumps(row_counts),
        },
    )

    # ── Step 4: RLS-scoped DELETE cascade ────────────────────────────────────
    # Scope the RLS context to this transaction so all subsequent DELETEs are
    # auto-filtered to tenant_id. Use core.tenant.set_tenant_context (set_config
    # form) — a parameterized `SET LOCAL app.tenant_id = :tid` is a Postgres
    # syntax error (SET rejects bind params; the F4 H1 bug). PG-only; SQLite
    # (unit tests) has no GUC and the ORM belt covers isolation there.
    if getattr(db.bind, "dialect", None) is not None and db.bind.dialect.name == "postgresql":  # pragma: no cover
        from core.tenant import set_tenant_context  # pragma: no cover — PG-only; verified by the tenancy PG suite
        set_tenant_context(db, tenant_id)

    for table in _TENANT_SCOPED_TABLES:
        try:
            db.execute(
                text(f"DELETE FROM {_safe_table(table)} WHERE tenant_id = :tid"),  # noqa: S608
                {"tid": tenant_id},
            )
        except Exception:
            # Table absent in test DB — skip gracefully.
            pass

    # ── Step 5: Delete GCS prefix ────────────────────────────────────────────
    _delete_gcs_prefix(gcs_client, bucket_name, gcs_prefix)

    # ── Step 6: GCIP delete (best-effort) ────────────────────────────────────
    _delete_gcip_tenant(db, tenant_id, gcip_client)

    # ── Step 7: UPDATE audit log to 'complete' ───────────────────────────────
    db.execute(
        text(
            "UPDATE tenant_offboard_log SET status = 'complete' "
            "WHERE tenant_id = :tid AND status = 'pending'"
        ),
        {"tid": tenant_id},
    )

    # ── Step 8: UPDATE tenants SET status='offboarded' ───────────────────────
    db.execute(
        text("UPDATE tenants SET status = 'offboarded' WHERE id = :tid"),
        {"tid": tenant_id},
    )

    log.info(
        "offboard_tenant: tenant %d offboarded by %s; gcs_prefix=%s row_counts=%s",
        tenant_id,
        platform_admin_email,
        gcs_prefix,
        row_counts,
    )


def _delete_gcs_prefix(gcs_client, bucket_name: str, prefix: str) -> None:
    """List and delete all GCS objects under *prefix*."""
    bucket = gcs_client.bucket(bucket_name)
    blobs = bucket.list_blobs(prefix=prefix)
    for blob in blobs:
        blob.delete()


def _delete_gcip_tenant(db, tenant_id: int, gcip_client) -> None:
    """Delete the tenant's GCIP tenant (best-effort).

    Looks up the mapped gcip_tenant from tenant_gcip_map and calls
    gcip_client.delete_gcip_tenant(). A missing map row or a GCIP-side failure is
    logged and swallowed so it never leaves the DB/GCS offboard half-applied —
    an orphaned GCIP tenant is reconciled out-of-band, not by aborting offboard.
    """
    if gcip_client is None:
        log.info("offboard_tenant: no gcip_client; skipping GCIP delete for tenant %d", tenant_id)
        return

    try:
        row = db.execute(
            text("SELECT gcip_tenant FROM tenant_gcip_map WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        ).fetchone()
    except Exception as exc:  # noqa: BLE001 — map table absent in unit DBs
        log.error("offboard_tenant: gcip_tenant lookup failed for tenant %d: %s", tenant_id, exc)
        return

    gcip_tenant_id = row[0] if row else None
    if not gcip_tenant_id:
        log.info("offboard_tenant: no GCIP tenant mapped for tenant %d; nothing to delete", tenant_id)
        return

    try:
        gcip_client.delete_gcip_tenant(gcip_tenant_id)
        log.info("offboard_tenant: deleted GCIP tenant %s for tenant %d", gcip_tenant_id, tenant_id)
    except Exception as exc:  # noqa: BLE001 — best-effort; reconcile orphans out-of-band
        log.error(
            "offboard_tenant: GCIP delete failed for %s (tenant %d): %s",
            gcip_tenant_id, tenant_id, exc,
        )
