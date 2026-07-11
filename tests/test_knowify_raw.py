"""TDD tests for core/knowify/mirror.py — raw-mirror layer (Wave 2).

Covers:
- content_hash: stable, key-order-independent, distinct for distinct payloads
- upsert_raw: insert N rows; re-run identical = 0 writes; changed payload = 1 update
- tombstone_absent: absent id → is_present=FALSE + deleted_at set; re-run no-ops;
  a returning id un-tombstones via upsert_raw
- write_state: records last_run_at / last_status / rows_seen; upsert on re-call

PG fixture (rls_engine / pg_admin_engine from tests/tenancy/conftest.py):
  - Uses real Postgres so JSONB, RLS, and ON CONFLICT are exercised.
  - Marked @pytest.mark.postgres; skipped when no PG available.

Pure-logic tests (content_hash, count assertions on SQLite) run without PG.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from core.knowify.mirror import content_hash, tombstone_absent, upsert_raw, write_state

# Pull in the tenancy conftest fixtures (pg_url, pg_container, pg_admin_engine,
# pg_engine, rls_engine, etc.) so @pytest.mark.postgres tests here can use them.
# Must be after imports to avoid E402; pytest_plugins is processed by the framework,
# not as a module-level side effect, so placement after imports is fine.
pytest_plugins = ["tests.tenancy.conftest"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sqlite_session(tenant_id: int = 1):
    """Return a plain SQLite session stamped with tenant_id (no RLS event needed)."""
    from app.models import Base

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    sess = factory()
    sess.info["tenant_id"] = tenant_id
    return sess


# ---------------------------------------------------------------------------
# content_hash — pure, no DB
# ---------------------------------------------------------------------------

class TestContentHash:
    def test_identical_dicts_same_hash(self):
        a = {"Id": 1, "Name": "Foo", "Amount": "100.00"}
        b = {"Id": 1, "Name": "Foo", "Amount": "100.00"}
        assert content_hash(a) == content_hash(b)

    def test_key_order_independent(self):
        a = {"b": 2, "a": 1}
        b = {"a": 1, "b": 2}
        assert content_hash(a) == content_hash(b)

    def test_different_values_different_hash(self):
        a = {"Id": 1, "Amount": "100.00"}
        b = {"Id": 1, "Amount": "200.00"}
        assert content_hash(a) != content_hash(b)

    def test_returns_64_char_hex(self):
        h = content_hash({"x": 1})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_nested_dict_stable(self):
        a = {"outer": {"inner": [1, 2, 3]}}
        b = {"outer": {"inner": [1, 2, 3]}}
        assert content_hash(a) == content_hash(b)


# ---------------------------------------------------------------------------
# upsert_raw + tombstone_absent + write_state — SQLite (logic/counts)
# ---------------------------------------------------------------------------

class TestUpsertRawSQLite:
    def test_insert_n_rows(self):
        sess = _sqlite_session()
        records = [{"Id": str(i), "Name": f"rec{i}"} for i in range(5)]
        counts = upsert_raw(sess, "invoices", records)
        assert counts["inserted"] == 5
        assert counts["updated"] == 0
        assert counts["unchanged"] == 0

    def test_rerun_identical_writes_zero(self):
        sess = _sqlite_session()
        records = [{"Id": "1", "Name": "Foo"}]
        upsert_raw(sess, "invoices", records)
        counts = upsert_raw(sess, "invoices", records)
        assert counts["inserted"] == 0
        assert counts["updated"] == 0
        assert counts["unchanged"] == 1

    def test_changed_payload_updates_one(self):
        sess = _sqlite_session()
        upsert_raw(sess, "invoices", [{"Id": "1", "Name": "Foo"}])
        counts = upsert_raw(sess, "invoices", [{"Id": "1", "Name": "Bar"}])
        assert counts["updated"] == 1
        assert counts["unchanged"] == 0
        assert counts["inserted"] == 0

    def test_content_hash_stable_after_upsert(self):
        from app.models import KnowifyRawRecord

        sess = _sqlite_session()
        rec = {"Id": "42", "Name": "Stable"}
        upsert_raw(sess, "invoices", [rec])
        row = sess.execute(
            select(KnowifyRawRecord).where(KnowifyRawRecord.knowify_id == "42")
        ).scalar_one()
        expected = content_hash(rec)
        assert row.content_hash == expected

    def test_rerun_hash_unchanged(self):
        from app.models import KnowifyRawRecord

        sess = _sqlite_session()
        rec = {"Id": "7", "Val": 99}
        upsert_raw(sess, "clients", [rec])
        h1 = sess.execute(
            select(KnowifyRawRecord.content_hash).where(KnowifyRawRecord.knowify_id == "7")
        ).scalar_one()
        upsert_raw(sess, "clients", [rec])
        h2 = sess.execute(
            select(KnowifyRawRecord.content_hash).where(KnowifyRawRecord.knowify_id == "7")
        ).scalar_one()
        assert h1 == h2

    def test_custom_id_key(self):
        sess = _sqlite_session()
        records = [{"CustomId": "abc", "Data": 1}]
        counts = upsert_raw(sess, "items", records, id_key="CustomId")
        assert counts["inserted"] == 1

    def test_changed_payload_updates_hash(self):
        from app.models import KnowifyRawRecord

        sess = _sqlite_session()
        upsert_raw(sess, "invoices", [{"Id": "X", "v": 1}])
        upsert_raw(sess, "invoices", [{"Id": "X", "v": 2}])
        row = sess.execute(
            select(KnowifyRawRecord).where(KnowifyRawRecord.knowify_id == "X")
        ).scalar_one()
        assert row.content_hash == content_hash({"Id": "X", "v": 2})


class TestTombstoneAbsentSQLite:
    def test_absent_id_tombstoned(self):
        from app.models import KnowifyRawRecord

        sess = _sqlite_session()
        upsert_raw(sess, "invoices", [{"Id": "1"}, {"Id": "2"}])
        # Only id=1 present in the latest pull
        n = tombstone_absent(sess, "invoices", {"1"})
        assert n == 1
        row = sess.execute(
            select(KnowifyRawRecord).where(KnowifyRawRecord.knowify_id == "2")
        ).scalar_one()
        assert row.is_present is False
        assert row.deleted_at is not None

    def test_present_id_not_tombstoned(self):
        from app.models import KnowifyRawRecord

        sess = _sqlite_session()
        upsert_raw(sess, "invoices", [{"Id": "1"}])
        tombstone_absent(sess, "invoices", {"1"})
        row = sess.execute(
            select(KnowifyRawRecord).where(KnowifyRawRecord.knowify_id == "1")
        ).scalar_one()
        assert row.is_present is True
        assert row.deleted_at is None

    def test_rerun_noop(self):
        from app.models import KnowifyRawRecord

        sess = _sqlite_session()
        upsert_raw(sess, "invoices", [{"Id": "1"}, {"Id": "2"}])
        tombstone_absent(sess, "invoices", {"1"})
        # Record the deleted_at timestamp
        ts1 = sess.execute(
            select(KnowifyRawRecord.deleted_at).where(KnowifyRawRecord.knowify_id == "2")
        ).scalar_one()
        # Re-run same absent set — should be a no-op (count=0)
        n2 = tombstone_absent(sess, "invoices", {"1"})
        assert n2 == 0
        ts2 = sess.execute(
            select(KnowifyRawRecord.deleted_at).where(KnowifyRawRecord.knowify_id == "2")
        ).scalar_one()
        assert ts1 == ts2

    def test_returning_id_untombstones(self):
        from app.models import KnowifyRawRecord

        sess = _sqlite_session()
        upsert_raw(sess, "invoices", [{"Id": "1"}, {"Id": "2"}])
        tombstone_absent(sess, "invoices", {"1"})
        # Verify id=2 is tombstoned
        row = sess.execute(
            select(KnowifyRawRecord).where(KnowifyRawRecord.knowify_id == "2")
        ).scalar_one()
        assert row.is_present is False
        # Next pull: id=2 reappears
        upsert_raw(sess, "invoices", [{"Id": "2"}])
        sess.expire(row)
        row2 = sess.execute(
            select(KnowifyRawRecord).where(KnowifyRawRecord.knowify_id == "2")
        ).scalar_one()
        assert row2.is_present is True
        assert row2.deleted_at is None

    def test_entity_scoped(self):
        """Tombstone on entity A does not affect entity B rows."""
        from app.models import KnowifyRawRecord

        sess = _sqlite_session()
        upsert_raw(sess, "invoices", [{"Id": "1"}])
        upsert_raw(sess, "payments", [{"Id": "1"}])
        tombstone_absent(sess, "invoices", set())  # tombstone ALL invoice rows
        pay_row = sess.execute(
            select(KnowifyRawRecord).where(
                KnowifyRawRecord.entity == "payments",
                KnowifyRawRecord.knowify_id == "1",
            )
        ).scalar_one()
        assert pay_row.is_present is True

    def test_empty_present_ids_tombstones_all(self):
        from app.models import KnowifyRawRecord

        sess = _sqlite_session()
        upsert_raw(sess, "invoices", [{"Id": "1"}, {"Id": "2"}, {"Id": "3"}])
        n = tombstone_absent(sess, "invoices", set())
        assert n == 3
        rows = sess.execute(
            select(KnowifyRawRecord).where(KnowifyRawRecord.entity == "invoices")
        ).scalars().all()
        assert all(not r.is_present for r in rows)
        assert all(r.deleted_at is not None for r in rows)


class TestWriteStateSQLite:
    def test_records_last_run_at(self):
        from app.models import KnowifySyncState

        sess = _sqlite_session()
        before = _utcnow()
        write_state(sess, "invoices", rows_seen=10, status="ok")
        row = sess.execute(
            select(KnowifySyncState).where(KnowifySyncState.entity == "invoices")
        ).scalar_one()
        assert row.last_run_at >= before
        assert row.last_status == "ok"
        assert row.rows_seen == 10

    def test_records_status_error(self):
        from app.models import KnowifySyncState

        sess = _sqlite_session()
        write_state(sess, "clients", rows_seen=0, status="error")
        row = sess.execute(
            select(KnowifySyncState).where(KnowifySyncState.entity == "clients")
        ).scalar_one()
        assert row.last_status == "error"

    def test_high_water_optional(self):
        from app.models import KnowifySyncState

        sess = _sqlite_session()
        write_state(sess, "invoices", rows_seen=5, status="ok")
        row = sess.execute(
            select(KnowifySyncState).where(KnowifySyncState.entity == "invoices")
        ).scalar_one()
        assert row.last_high_water is None

    def test_high_water_recorded(self):
        from app.models import KnowifySyncState

        sess = _sqlite_session()
        hw = _utcnow()
        write_state(sess, "invoices", rows_seen=3, status="ok", high_water=hw)
        row = sess.execute(
            select(KnowifySyncState).where(KnowifySyncState.entity == "invoices")
        ).scalar_one()
        assert row.last_high_water == hw

    def test_rerun_updates_in_place(self):
        from app.models import KnowifySyncState

        sess = _sqlite_session()
        write_state(sess, "invoices", rows_seen=1, status="ok")
        write_state(sess, "invoices", rows_seen=5, status="partial")
        rows = sess.execute(
            select(KnowifySyncState).where(KnowifySyncState.entity == "invoices")
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].rows_seen == 5
        assert rows[0].last_status == "partial"

    def test_different_entities_separate_rows(self):
        from app.models import KnowifySyncState

        sess = _sqlite_session()
        write_state(sess, "invoices", rows_seen=10, status="ok")
        write_state(sess, "payments", rows_seen=20, status="ok")
        rows = sess.execute(select(KnowifySyncState)).scalars().all()
        assert len(rows) == 2

    def test_high_water_on_update(self):
        """high_water branch on SQLite update path (line 277)."""
        from app.models import KnowifySyncState

        sess = _sqlite_session()
        write_state(sess, "invoices", rows_seen=1, status="ok")
        hw = _utcnow()
        write_state(sess, "invoices", rows_seen=2, status="ok", high_water=hw)
        row = sess.execute(
            select(KnowifySyncState).where(KnowifySyncState.entity == "invoices")
        ).scalar_one()
        assert row.last_high_water == hw


# ---------------------------------------------------------------------------
# Postgres tests — real JSONB + RLS (skipped when no PG available)
# ---------------------------------------------------------------------------

@pytest.mark.postgres
class TestUpsertRawPostgres:
    """Uses the rls_engine session factory from tests/tenancy/conftest.py.

    rls_engine is a sessionmaker wired to the pg_engine (NON-superuser, NOBYPASSRLS)
    with the after_begin RLS event registered, so tenant GUC fires on each txn.
    """

    def _session(self, rls_engine, tenant_id: int = 1):
        sess = rls_engine()
        sess.info["tenant_id"] = tenant_id
        return sess

    def test_insert_rows(self, rls_engine):
        sess = self._session(rls_engine)
        try:
            records = [{"Id": "pg-1", "Name": "Alpha"}, {"Id": "pg-2", "Name": "Beta"}]
            counts = upsert_raw(sess, "pg_test_inv", records)
            sess.commit()
            assert counts["inserted"] == 2
        finally:
            sess.rollback()
            sess.close()

    def test_rerun_identical_unchanged(self, rls_engine):
        sess = self._session(rls_engine)
        try:
            rec = [{"Id": "pg-idem-1", "v": 1}]
            upsert_raw(sess, "pg_test_idem", rec)
            sess.commit()
            counts = upsert_raw(sess, "pg_test_idem", rec)
            sess.commit()
            assert counts["unchanged"] == 1
            assert counts["inserted"] == 0
            assert counts["updated"] == 0
        finally:
            sess.rollback()
            sess.close()

    def test_changed_payload_updates(self, rls_engine):
        sess = self._session(rls_engine)
        try:
            upsert_raw(sess, "pg_test_upd", [{"Id": "pg-upd-1", "v": 1}])
            sess.commit()
            counts = upsert_raw(sess, "pg_test_upd", [{"Id": "pg-upd-1", "v": 2}])
            sess.commit()
            assert counts["updated"] == 1
        finally:
            sess.rollback()
            sess.close()

    def test_hash_stable_after_upsert(self, rls_engine):
        from app.models import KnowifyRawRecord

        sess = self._session(rls_engine)
        try:
            rec = {"Id": "pg-hash-1", "X": "Y"}
            upsert_raw(sess, "pg_test_hash", [rec])
            sess.commit()
            row = sess.execute(
                select(KnowifyRawRecord).where(
                    KnowifyRawRecord.entity == "pg_test_hash",
                    KnowifyRawRecord.knowify_id == "pg-hash-1",
                )
            ).scalar_one()
            assert row.content_hash == content_hash(rec)
        finally:
            sess.rollback()
            sess.close()

    def test_rls_tenant_isolation(self, rls_engine):
        """Rows inserted as tenant 1 are invisible when queried as tenant 2."""
        from app.models import KnowifyRawRecord

        sess1 = self._session(rls_engine, tenant_id=1)
        try:
            upsert_raw(sess1, "pg_rls_entity", [{"Id": "rls-only-t1", "v": 1}])
            sess1.commit()
        finally:
            sess1.close()

        sess2 = self._session(rls_engine, tenant_id=2)
        try:
            rows = sess2.execute(
                select(KnowifyRawRecord).where(
                    KnowifyRawRecord.entity == "pg_rls_entity",
                    KnowifyRawRecord.knowify_id == "rls-only-t1",
                )
            ).scalars().all()
            assert rows == [], "RLS breach: tenant 2 can see tenant 1 rows"
        finally:
            sess2.rollback()
            sess2.close()


@pytest.mark.postgres
class TestTombstoneAbsentPostgres:
    def _session(self, rls_engine, tenant_id: int = 1):
        sess = rls_engine()
        sess.info["tenant_id"] = tenant_id
        return sess

    def test_tombstone_absent_pg(self, rls_engine):
        from app.models import KnowifyRawRecord

        sess = self._session(rls_engine)
        try:
            upsert_raw(sess, "pg_tomb", [{"Id": "t1"}, {"Id": "t2"}])
            sess.commit()
            n = tombstone_absent(sess, "pg_tomb", {"t1"})
            sess.commit()
            assert n == 1
            row = sess.execute(
                select(KnowifyRawRecord).where(
                    KnowifyRawRecord.entity == "pg_tomb",
                    KnowifyRawRecord.knowify_id == "t2",
                )
            ).scalar_one()
            assert row.is_present is False
            assert row.deleted_at is not None
        finally:
            sess.rollback()
            sess.close()

    def test_rerun_noop_pg(self, rls_engine):
        sess = self._session(rls_engine)
        try:
            upsert_raw(sess, "pg_noop", [{"Id": "n1"}, {"Id": "n2"}])
            sess.commit()
            tombstone_absent(sess, "pg_noop", {"n1"})
            sess.commit()
            n2 = tombstone_absent(sess, "pg_noop", {"n1"})
            sess.commit()
            assert n2 == 0
        finally:
            sess.rollback()
            sess.close()


@pytest.mark.postgres
class TestWriteStatePostgres:
    def _session(self, rls_engine, tenant_id: int = 1):
        sess = rls_engine()
        sess.info["tenant_id"] = tenant_id
        return sess

    def test_write_state_pg(self, rls_engine):
        from app.models import KnowifySyncState

        sess = self._session(rls_engine)
        try:
            before = _utcnow()
            write_state(sess, "pg_ws_inv", rows_seen=42, status="ok")
            sess.commit()
            row = sess.execute(
                select(KnowifySyncState).where(KnowifySyncState.entity == "pg_ws_inv")
            ).scalar_one()
            assert row.last_run_at >= before
            assert row.rows_seen == 42
            assert row.last_status == "ok"
        finally:
            sess.rollback()
            sess.close()

    def test_write_state_upsert_pg(self, rls_engine):
        from app.models import KnowifySyncState

        sess = self._session(rls_engine)
        try:
            write_state(sess, "pg_ws_idem", rows_seen=1, status="ok")
            sess.commit()
            write_state(sess, "pg_ws_idem", rows_seen=99, status="partial")
            sess.commit()
            rows = sess.execute(
                select(KnowifySyncState).where(KnowifySyncState.entity == "pg_ws_idem")
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].rows_seen == 99
            assert rows[0].last_status == "partial"
        finally:
            sess.rollback()
            sess.close()

    def test_write_state_high_water_pg(self, rls_engine):
        """high_water branch on PG ON CONFLICT update path (line 249)."""
        from app.models import KnowifySyncState

        sess = self._session(rls_engine)
        try:
            # First call: insert (no high_water)
            write_state(sess, "pg_ws_hw", rows_seen=3, status="ok")
            sess.commit()
            # Second call: ON CONFLICT update WITH high_water — exercises line 249
            hw = _utcnow()
            write_state(sess, "pg_ws_hw", rows_seen=7, status="ok", high_water=hw)
            sess.commit()
            row = sess.execute(
                select(KnowifySyncState).where(KnowifySyncState.entity == "pg_ws_hw")
            ).scalar_one()
            assert row.last_high_water is not None
            assert row.rows_seen == 7
        finally:
            sess.rollback()
            sess.close()
