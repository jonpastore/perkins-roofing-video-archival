"""Migration 0032 (Knowify data mirror) — schema + RLS assertions.

Two layers, matching the tenancy-suite convention (conftest.py):

  * SQLite structural (always runs): Base.metadata.create_all builds the ORM
    schema — the SQLite-portable mirror of the migration. Asserts the crosswalk
    columns land on invoices/payments/jobs and the two new mirror tables exist
    with their tombstone columns. RLS + partial-UNIQUE indexes + the source CHECK
    are Postgres-only DDL (SERIAL/TIMESTAMPTZ/DO$$/partial-index) and are NOT
    asserted here — they get their own @pytest.mark.postgres cases below.

  * Postgres (@pytest.mark.postgres): applies infra/migrations/0032 on top of the
    create_all schema (idempotent), then asserts the partial-UNIQUE indexes, the
    source CHECK constraint, pg_policies tenant_isolation on both new tables, and
    that a second apply is a no-op.

The Postgres cases use the conftest pg_admin_engine (superuser: it builds schema +
applies RLS DDL). Skipped cleanly when no Postgres is available.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect, text

from scripts.apply_migrations_connector import _statements

_MIGRATION = os.path.join(
    os.path.dirname(__file__), "..", "..", "infra", "migrations", "0032_knowify_mirror.sql"
)


def _apply_0032(engine) -> None:
    """Apply the 0032 migration file to a Postgres engine, statement by statement
    (dollar-quote-aware, reusing the production runner's splitter)."""
    with open(os.path.abspath(_MIGRATION)) as fh:
        sql = fh.read()
    with engine.begin() as conn:
        for stmt in _statements(sql):
            conn.execute(text(stmt))


# ---------------------------------------------------------------------------
# SQLite structural — ORM schema is the portable mirror of the migration.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sqlite_inspector():
    from app.models import Base

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return inspect(engine)


class TestSqliteStructural:
    def test_invoices_crosswalk_columns_exist(self, sqlite_inspector):
        cols = {c["name"] for c in sqlite_inspector.get_columns("invoices")}
        assert {"knowify_invoice_id", "knowify_invoice_number", "source"} <= cols

    def test_payments_crosswalk_column_exists(self, sqlite_inspector):
        cols = {c["name"] for c in sqlite_inspector.get_columns("payments")}
        assert "knowify_payment_id" in cols

    def test_jobs_crosswalk_column_exists(self, sqlite_inspector):
        cols = {c["name"] for c in sqlite_inspector.get_columns("jobs")}
        assert "knowify_job_id" in cols

    def test_sync_state_table_exists(self, sqlite_inspector):
        assert "knowify_sync_state" in sqlite_inspector.get_table_names()
        cols = {c["name"] for c in sqlite_inspector.get_columns("knowify_sync_state")}
        # watermark + health surface
        assert {"entity", "last_high_water", "last_status", "rows_seen"} <= cols

    def test_raw_records_table_has_tombstone_columns(self, sqlite_inspector):
        assert "knowify_raw_records" in sqlite_inspector.get_table_names()
        cols = {c["name"] for c in sqlite_inspector.get_columns("knowify_raw_records")}
        assert {"entity", "knowify_id", "payload", "content_hash"} <= cols
        # tombstone-on-absence columns (TRD §1c)
        assert {"is_present", "deleted_at"} <= cols

    def test_source_column_defaults_to_v2(self):
        """A default-constructed Invoice carries source='v2' (import path overrides
        to 'knowify_import'); it never collides with a v2-issued number because
        imports also leave invoice_number NULL."""
        from app.models import Invoice

        inv = Invoice(job_id=1, customer_id=1, created_by="t")
        # SQLAlchemy applies column defaults on flush; assert the declared default.
        assert Invoice.__table__.c.source.default.arg == "v2"
        assert inv.knowify_invoice_id is None


# ---------------------------------------------------------------------------
# Postgres — migration-only DDL (partial-unique, CHECK, RLS, idempotency).
# ---------------------------------------------------------------------------

@pytest.mark.postgres
class TestPostgresMigration:
    @pytest.fixture(scope="class")
    @classmethod
    def migrated(cls, pg_admin_engine):
        """create_all already built the tables (pg_admin_engine). Apply 0032 on top
        so the migration-only DDL (partial-unique indexes, CHECK, migration RLS
        policy) exists. Idempotent, so this is safe over the ORM schema."""
        _apply_0032(pg_admin_engine)
        return pg_admin_engine

    def test_crosswalk_columns_present(self, migrated):
        insp = inspect(migrated)
        assert {"knowify_invoice_id", "knowify_invoice_number", "source"} <= {
            c["name"] for c in insp.get_columns("invoices")
        }
        assert "knowify_payment_id" in {c["name"] for c in insp.get_columns("payments")}
        assert "knowify_job_id" in {c["name"] for c in insp.get_columns("jobs")}

    def test_new_tables_present(self, migrated):
        names = set(inspect(migrated).get_table_names())
        assert {"knowify_sync_state", "knowify_raw_records"} <= names

    def test_partial_unique_indexes_exist(self, migrated):
        with migrated.connect() as conn:
            rows = conn.execute(text(
                "SELECT indexname FROM pg_indexes WHERE schemaname='public'"
            )).fetchall()
        idx = {r[0] for r in rows}
        assert {
            "uq_customers_tenant_knowify",
            "uq_invoices_tenant_knowify_id",
            "uq_payments_tenant_knowify_id",
            "uq_jobs_tenant_knowify",
            "uq_price_book_items_tenant_knowify",
        } <= idx

    def test_source_check_constraint_exists(self, migrated):
        with migrated.connect() as conn:
            row = conn.execute(text(
                "SELECT 1 FROM pg_constraint WHERE conname='chk_invoices_source'"
            )).fetchone()
        assert row is not None

    def test_rls_policy_on_new_tables(self, migrated):
        with migrated.connect() as conn:
            rows = conn.execute(text(
                "SELECT tablename FROM pg_policies "
                "WHERE policyname='tenant_isolation' "
                "AND tablename IN ('knowify_sync_state','knowify_raw_records')"
            )).fetchall()
        assert {r[0] for r in rows} == {"knowify_sync_state", "knowify_raw_records"}

    def test_rls_forced_on_new_tables(self, migrated):
        with migrated.connect() as conn:
            rows = conn.execute(text(
                "SELECT relname FROM pg_class "
                "WHERE relname IN ('knowify_sync_state','knowify_raw_records') "
                "AND relrowsecurity AND relforcerowsecurity"
            )).fetchall()
        assert {r[0] for r in rows} == {"knowify_sync_state", "knowify_raw_records"}

    def test_reapply_is_idempotent(self, migrated):
        """Re-running 0032 is a no-op: no error, and the policy/constraint set is
        unchanged (still exactly one tenant_isolation policy per new table)."""
        _apply_0032(migrated)  # must not raise
        with migrated.connect() as conn:
            n = conn.execute(text(
                "SELECT count(*) FROM pg_policies "
                "WHERE policyname='tenant_isolation' "
                "AND tablename IN ('knowify_sync_state','knowify_raw_records')"
            )).scalar()
            checks = conn.execute(text(
                "SELECT count(*) FROM pg_constraint WHERE conname='chk_invoices_source'"
            )).scalar()
        assert n == 2, f"expected exactly one tenant_isolation policy per new table, got {n}"
        assert checks == 1, "source CHECK constraint duplicated on re-apply"
