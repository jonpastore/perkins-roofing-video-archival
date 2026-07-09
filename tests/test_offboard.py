"""Tests for core/offboard.py — TDD red-first.

DB and GCS calls are mocked; no live connections.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_db(tenant_exists=True, tenant_id=2):
    """Build a minimal mock DB session for offboard tests.

    execute().fetchone() returns:
      - For the tenant existence check (first call): a row-like object with .id/.status
      - For COUNT(*) queries: a tuple (0,) so result[0] is JSON-serializable
    We use side_effect to distinguish calls by index.
    """
    mock_db = MagicMock()

    # Build the tenant row mock
    if tenant_exists:
        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id
        mock_tenant.status = "active"
        # Also support index access: row[0] for COUNT queries
        mock_tenant.__getitem__ = lambda self, i: tenant_id if i == 0 else "active"
    else:
        mock_tenant = None

    # COUNT queries return (0,); tenant lookup returns mock_tenant.
    # We use a counter via side_effect to return the right thing per call.
    call_count = [0]

    def fetchone_side_effect():
        call_count[0] += 1
        if call_count[0] == 1:
            # First call: tenant existence check
            return mock_tenant
        else:
            # Subsequent calls: COUNT(*) → return (0,)
            return (0,)

    mock_execute_result = MagicMock()
    mock_execute_result.fetchone.side_effect = fetchone_side_effect
    mock_execute_result.fetchall.return_value = []
    mock_db.execute.return_value = mock_execute_result
    return mock_db


# ---------------------------------------------------------------------------
# ProtectedTenantError guard
# ---------------------------------------------------------------------------

def test_offboard_blocks_tenant_1():
    """offboard_tenant(1, ...) raises ProtectedTenantError."""
    from core.offboard import ProtectedTenantError, offboard_tenant

    mock_db = _make_db(tenant_exists=True, tenant_id=1)
    mock_gcs = MagicMock()

    with pytest.raises(ProtectedTenantError):
        offboard_tenant(
            tenant_id=1,
            platform_admin_email="admin@degenito.ai",
            db=mock_db,
            gcs_client=mock_gcs,
            bucket_name="mybucket",
        )


def test_offboard_raises_when_tenant_not_found():
    """offboard_tenant raises ValueError when the tenant row does not exist."""
    from core.offboard import offboard_tenant

    mock_db = _make_db(tenant_exists=False)
    mock_gcs = MagicMock()

    with pytest.raises(ValueError, match="not found"):
        offboard_tenant(
            tenant_id=99,
            platform_admin_email="admin@degenito.ai",
            db=mock_db,
            gcs_client=mock_gcs,
            bucket_name="mybucket",
        )


# ---------------------------------------------------------------------------
# GCS prefix deletion
# ---------------------------------------------------------------------------

def test_offboard_deletes_gcs_prefix():
    """offboard_tenant lists and deletes all objects under tenants/{id}/."""
    from core.offboard import offboard_tenant

    mock_db = _make_db(tenant_exists=True, tenant_id=2)

    # GCS mock: bucket with 2 blobs under the prefix
    mock_blob1 = MagicMock()
    mock_blob1.name = "tenants/2/brand/logo.png"
    mock_blob2 = MagicMock()
    mock_blob2.name = "tenants/2/renders/out.mp4"

    mock_bucket = MagicMock()
    mock_bucket.list_blobs.return_value = [mock_blob1, mock_blob2]
    mock_gcs = MagicMock()
    mock_gcs.bucket.return_value = mock_bucket

    offboard_tenant(
        tenant_id=2,
        platform_admin_email="admin@degenito.ai",
        db=mock_db,
        gcs_client=mock_gcs,
        bucket_name="mybucket",
    )

    mock_gcs.bucket.assert_called_with("mybucket")
    mock_bucket.list_blobs.assert_called_once_with(prefix="tenants/2/")
    mock_blob1.delete.assert_called_once()
    mock_blob2.delete.assert_called_once()


def test_offboard_gcs_prefix_correct_for_tenant():
    """The GCS prefix used is exactly 'tenants/{tenant_id}/'."""
    from core.offboard import offboard_tenant

    mock_db = _make_db(tenant_exists=True, tenant_id=5)
    mock_bucket = MagicMock()
    mock_bucket.list_blobs.return_value = []
    mock_gcs = MagicMock()
    mock_gcs.bucket.return_value = mock_bucket

    offboard_tenant(
        tenant_id=5,
        platform_admin_email="admin@degenito.ai",
        db=mock_db,
        gcs_client=mock_gcs,
        bucket_name="mybucket",
    )

    mock_bucket.list_blobs.assert_called_once_with(prefix="tenants/5/")


# ---------------------------------------------------------------------------
# Audit log row
# ---------------------------------------------------------------------------

def test_offboard_inserts_audit_log_row():
    """offboard_tenant inserts a tenant_offboard_log row with status='complete'."""
    from core.offboard import offboard_tenant

    mock_db = _make_db(tenant_exists=True, tenant_id=2)
    mock_bucket = MagicMock()
    mock_bucket.list_blobs.return_value = []
    mock_gcs = MagicMock()
    mock_gcs.bucket.return_value = mock_bucket

    offboard_tenant(
        tenant_id=2,
        platform_admin_email="admin@degenito.ai",
        db=mock_db,
        gcs_client=mock_gcs,
        bucket_name="mybucket",
    )

    # Should have called db.execute at least twice: once to find the tenant,
    # once to insert the audit log row (and once to update status)
    assert mock_db.execute.call_count >= 2

    # Find the INSERT call — extract the SQL text from each execute() positional arg
    sql_calls = [str(c[0][0]) for c in mock_db.execute.call_args_list if c[0]]
    audit_calls = [s for s in sql_calls if "tenant_offboard_log" in s]
    assert len(audit_calls) >= 1, "Expected INSERT into tenant_offboard_log"


def test_offboard_sets_tenant_status_offboarded():
    """offboard_tenant updates the tenant row status to 'offboarded'."""
    from core.offboard import offboard_tenant

    mock_db = _make_db(tenant_exists=True, tenant_id=2)
    mock_bucket = MagicMock()
    mock_bucket.list_blobs.return_value = []
    mock_gcs = MagicMock()
    mock_gcs.bucket.return_value = mock_bucket

    offboard_tenant(
        tenant_id=2,
        platform_admin_email="admin@degenito.ai",
        db=mock_db,
        gcs_client=mock_gcs,
        bucket_name="mybucket",
    )

    sql_calls = [str(c[0][0]) for c in mock_db.execute.call_args_list if c[0]]
    offboard_calls = [s for s in sql_calls if "offboarded" in s]
    assert len(offboard_calls) >= 1, "Expected UPDATE setting status='offboarded'"


# ---------------------------------------------------------------------------
# GCIP stub
# ---------------------------------------------------------------------------

def test_offboard_gcip_delete_is_stub():
    """offboard_tenant completes without error even though GCIP delete is a stub."""
    from core.offboard import offboard_tenant

    mock_db = _make_db(tenant_exists=True, tenant_id=3)
    mock_bucket = MagicMock()
    mock_bucket.list_blobs.return_value = []
    mock_gcs = MagicMock()
    mock_gcs.bucket.return_value = mock_bucket

    # Should not raise
    offboard_tenant(
        tenant_id=3,
        platform_admin_email="admin@degenito.ai",
        db=mock_db,
        gcs_client=mock_gcs,
        bucket_name="mybucket",
    )


def test_offboard_tolerates_count_exception():
    """offboard_tenant continues if a COUNT(*) query fails (table absent in test DB)."""
    from core.offboard import offboard_tenant

    # DB that raises on COUNT queries but works for the other calls
    mock_bucket = MagicMock()
    mock_bucket.list_blobs.return_value = []
    mock_gcs = MagicMock()
    mock_gcs.bucket.return_value = mock_bucket

    def execute_side_effect(sql, params=None):
        sql_str = str(sql)
        result = MagicMock()
        if "SELECT id" in sql_str or "SELECT settings" in sql_str:
            row = MagicMock()
            row.id = 6
            row.status = "active"
            result.fetchone.return_value = row
        elif "COUNT(*)" in sql_str:
            raise Exception("table does not exist")
        else:
            result.fetchone.return_value = (0,)
        return result

    mock_db = MagicMock()
    mock_db.execute.side_effect = execute_side_effect

    # Should complete without raising
    offboard_tenant(
        tenant_id=6,
        platform_admin_email="admin@degenito.ai",
        db=mock_db,
        gcs_client=mock_gcs,
        bucket_name="mybucket",
    )


def test_offboard_tolerates_delete_exception():
    """offboard_tenant continues when a DELETE fails (table absent in test DB)."""
    from core.offboard import offboard_tenant

    def execute_side_effect(sql, params=None):
        sql_str = str(sql)
        result = MagicMock()
        if "SELECT id" in sql_str or "SELECT settings" in sql_str:
            row = MagicMock()
            row.id = 8
            row.status = "active"
            result.fetchone.return_value = row
        elif "COUNT(*)" in sql_str:
            result.fetchone.return_value = (0,)
        elif sql_str.startswith("DELETE"):
            raise Exception("table does not exist")
        else:
            result.fetchone.return_value = (0,)
        return result

    mock_db = MagicMock()
    mock_db.execute.side_effect = execute_side_effect
    mock_bucket = MagicMock()
    mock_bucket.list_blobs.return_value = []
    mock_gcs = MagicMock()
    mock_gcs.bucket.return_value = mock_bucket

    offboard_tenant(
        tenant_id=8,
        platform_admin_email="admin@degenito.ai",
        db=mock_db,
        gcs_client=mock_gcs,
        bucket_name="mybucket",
    )


def test_offboard_tolerates_set_local_exception():
    """offboard_tenant proceeds when SET LOCAL is not supported (SQLite)."""
    from core.offboard import offboard_tenant

    # DB where SET LOCAL raises but everything else succeeds
    def execute_side_effect(sql, params=None):
        sql_str = str(sql)
        result = MagicMock()
        if "SELECT id" in sql_str or "SELECT settings" in sql_str:
            row = MagicMock()
            row.id = 7
            row.status = "active"
            result.fetchone.return_value = row
        elif "SET LOCAL" in sql_str:
            raise Exception("SET LOCAL not supported in SQLite")
        elif "COUNT(*)" in sql_str:
            result.fetchone.return_value = (0,)
        else:
            result.fetchone.return_value = (0,)
        return result

    mock_db = MagicMock()
    mock_db.execute.side_effect = execute_side_effect
    mock_bucket = MagicMock()
    mock_bucket.list_blobs.return_value = []
    mock_gcs = MagicMock()
    mock_gcs.bucket.return_value = mock_bucket

    offboard_tenant(
        tenant_id=7,
        platform_admin_email="admin@degenito.ai",
        db=mock_db,
        gcs_client=mock_gcs,
        bucket_name="mybucket",
    )
