"""RLS bypass probe — tests that the database-layer RLS cannot be circumvented.

All tests here are marked @pytest.mark.postgres. They verify:
  1. Switching the GUC mid-transaction to another tenant returns 0 rows.
  2. The after_begin event on SessionLocal fires before any query (full-stack path).
  3. A session missing tenant_id raises before issuing SQL.
  4. The timing differential between own-resource and cross-tenant requests is ≤100 ms.
"""
from __future__ import annotations

import time

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker  # noqa: F401

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_guc(conn, tenant_id: int):
    # set_config(..., is_local => true) instead of `SET LOCAL app.tenant_id = :tid`:
    # Postgres SET rejects extended-protocol bind params (syntax error near "$1").
    conn.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)})


# ---------------------------------------------------------------------------
# RLS bypass via wrong GUC in the same transaction
# ---------------------------------------------------------------------------

@pytest.mark.postgres
def test_rls_blocks_raw_sql_wrong_tenant(seeded_rows, pg_engine):
    """Setting GUC to tenant 2 within a transaction hides tenant 1 rows entirely."""
    with pg_engine.begin() as conn:
        _set_guc(conn, 2)
        rows = conn.execute(text("SELECT * FROM videos")).fetchall()
    assert rows == [], (
        f"RLS should return 0 rows for tenant 2 (no tenant-2 data seeded); got {rows}"
    )


@pytest.mark.postgres
def test_rls_blocks_wrong_tenant_after_guc_switch(seeded_rows, pg_engine):
    """Even after explicitly querying tenant 1 data, switching GUC hides it."""
    vid_id = seeded_rows["video_id"]
    with pg_engine.begin() as conn:
        # Start as tenant 1 — row should be visible
        _set_guc(conn, 1)
        count_before = conn.execute(
            text("SELECT COUNT(*) FROM videos WHERE id = :id"), {"id": vid_id}
        ).scalar()

        # Switch GUC to tenant 2 — SET LOCAL changes GUC for remainder of transaction
        conn.execute(text("SET LOCAL app.tenant_id = '2'"))
        count_after = conn.execute(
            text("SELECT COUNT(*) FROM videos WHERE id = :id"), {"id": vid_id}
        ).scalar()

    assert count_before == 1, "Tenant 1 should see its own video"
    assert count_after == 0, "After GUC switch to tenant 2, tenant 1 video must be hidden"


@pytest.mark.postgres
def test_rls_table_without_tenant_data_returns_empty(pg_engine):
    """Tenant 2 with no rows of its own sees an empty result, not tenant 1 rows."""
    with pg_engine.begin() as conn:
        _set_guc(conn, 2)
        rows = conn.execute(text("SELECT * FROM comment_drafts")).fetchall()
    assert rows == []


@pytest.mark.postgres
def test_rls_blocks_cross_tenant_update(seeded_rows, pg_engine):
    """UPDATE with wrong GUC affects 0 rows (RLS USING clause filters the target set)."""
    vid_id = seeded_rows["video_id"]
    with pg_engine.begin() as conn:
        _set_guc(conn, 2)
        result = conn.execute(
            text("UPDATE videos SET title = 'Hacked' WHERE id = :id"), {"id": vid_id}
        )
        assert result.rowcount == 0, (
            f"UPDATE should affect 0 rows under wrong GUC; got {result.rowcount}"
        )

    # Verify the row is unchanged from tenant 1's perspective
    with pg_engine.begin() as conn:
        _set_guc(conn, 1)
        row = conn.execute(
            text("SELECT title FROM videos WHERE id = :id"), {"id": vid_id}
        ).fetchone()
    assert row is not None
    assert row[0] != "Hacked", "Row title must be unchanged after cross-tenant UPDATE attempt"


# ---------------------------------------------------------------------------
# Full-stack session path: after_begin event fires before SQL
# ---------------------------------------------------------------------------

@pytest.mark.postgres
def test_after_begin_sets_guc_before_query(seeded_rows, pg_engine):
    """The production session path (after_begin event) correctly gates queries."""
    from core.tenant import register_tenant_session_events

    rls_factory = sessionmaker(bind=pg_engine, future=True)
    register_tenant_session_events(rls_factory)

    # Tenant 1 session — should see its own data
    session = rls_factory()
    session.info["tenant_id"] = 1
    try:
        result = session.execute(text("SELECT COUNT(*) FROM videos")).scalar()
        assert result >= 1, "Tenant 1 session should see at least 1 video"
        session.rollback()
    finally:
        session.close()


@pytest.mark.postgres
def test_after_begin_missing_tenant_raises_before_sql(pg_engine):
    """Session without tenant_id raises RuntimeError before any SQL reaches the DB."""
    from core.tenant import register_tenant_session_events

    rls_factory = sessionmaker(bind=pg_engine, future=True)
    register_tenant_session_events(rls_factory)

    session = rls_factory()
    # Do NOT set session.info["tenant_id"]
    try:
        with pytest.raises(RuntimeError, match="tenant_id not set on session.info"):
            session.execute(text("SELECT 1"))
    finally:
        session.close()


@pytest.mark.postgres
def test_tenant_1_cannot_see_tenant_2_rows(pg_engine):
    """Even if tenant 2 had rows, tenant 1 session would not see them."""
    from core.tenant import register_tenant_session_events

    rls_factory = sessionmaker(bind=pg_engine, future=True)
    register_tenant_session_events(rls_factory)

    # Insert a row for tenant 2 directly (bypassing RLS via engine.begin)
    with pg_engine.begin() as conn:
        conn.execute(text("SET LOCAL app.tenant_id = '2'"))
        conn.execute(text(
            "INSERT INTO email_templates (name, subject, body, tenant_id) "
            "VALUES ('T2 Template', 'Subject', 'Body', 2) ON CONFLICT DO NOTHING"
        ))

    # Tenant 1 session must not see tenant 2's email template
    session = rls_factory()
    session.info["tenant_id"] = 1
    try:
        count = session.execute(
            text("SELECT COUNT(*) FROM email_templates WHERE tenant_id = 2")
        ).scalar()
        assert count == 0, "Tenant 1 session must not see tenant 2's email templates"
        session.rollback()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Timing probe: 404-indistinguishable response timing differential ≤ 100 ms
# ---------------------------------------------------------------------------

@pytest.mark.postgres
def test_cross_tenant_timing_differential(seeded_rows, pg_engine):
    """Own-resource vs cross-tenant lookup timing differential must be ≤ 100 ms.

    Simulates the application-layer behavior: both paths hit the DB via the
    same raw SELECT. RLS filters the cross-tenant case at the DB layer.
    The timing differential represents the cost of the RLS evaluation itself
    (should be negligible — not an application-level 404 vs 200 branch).
    """
    vid_id = seeded_rows["video_id"]
    iterations = 10

    t_own_total = 0.0
    t_cross_total = 0.0

    for _ in range(iterations):
        # Own-tenant path (GUC=1, row exists → returns 1 row)
        t0 = time.perf_counter()
        with pg_engine.begin() as conn:
            _set_guc(conn, 1)
            conn.execute(text("SELECT * FROM videos WHERE id = :id"), {"id": vid_id}).fetchone()
        t_own_total += time.perf_counter() - t0

        # Cross-tenant path (GUC=2, row filtered by RLS → returns 0 rows)
        t0 = time.perf_counter()
        with pg_engine.begin() as conn:
            _set_guc(conn, 2)
            conn.execute(text("SELECT * FROM videos WHERE id = :id"), {"id": vid_id}).fetchone()
        t_cross_total += time.perf_counter() - t0

    avg_own = t_own_total / iterations
    avg_cross = t_cross_total / iterations
    diff_ms = abs(avg_own - avg_cross) * 1000

    assert diff_ms <= 100, (
        f"Timing differential {diff_ms:.1f} ms exceeds 100 ms threshold. "
        f"avg_own={avg_own*1000:.1f}ms avg_cross={avg_cross*1000:.1f}ms"
    )
