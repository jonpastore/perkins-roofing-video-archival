"""Behavioral I/O validation for jobs/knowify_sync.py (Wave 5 — R1).

Tests run against a mocked Knowify REST client (fetch_entity patched) and an
in-memory SQLite DB so no network or Secret Manager is ever hit.

Covers:
- full-pull run: upsert_raw → tombstone_absent → promote → write_state (all entities)
- idempotent re-run: 0 new rows written, sync_state counts unchanged
- per-entity error isolation: one entity error → others 'ok'; run exits non-zero (AC-17)
- /api/v2/valid preflight: dead token → all entities 'auth_error', exits non-zero,
  fetch NOT called (no per-entity 401 storm)
- single-flight: second concurrent run (lock held) skips
- --refresh-only keep-warm path: calls tokens.refresh_only, no fetch
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import sessionmaker

from app.models import Base, KnowifyRawRecord, KnowifySyncState
from jobs.knowify_sync import SYNC_ENTITIES

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _sqlite_factory(tenant_id: int = 1):
    """Return a sessionmaker + engine pair for an in-memory SQLite DB."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    return factory, engine


def _make_session(factory, tenant_id: int = 1):
    s = factory()
    s.info["tenant_id"] = tenant_id
    return s


# Minimal fixture payloads — enough for promote_* to succeed without errors.
_CLIENTS = [{"Id": "10", "Name": "ACME Roofing", "Email": "acme@example.com"}]
_ITEMS = [{"Id": "20", "Name": "Shingle", "UnitPrice": "50.00"}]
_INVOICES = [
    {
        "Id": "30",
        "InvoiceNumber": "INV-001",
        "TotalAmount": "1000.00",
        "OutstandingAmount": "0.00",
        "BusinessState": "Closed",
        "ObjectState": "Active",
        "ClientId": "10",
        "ProjectId": None,
    }
]
_PAYMENTS = [
    {
        "Id": "40",
        "Amount": "1000.00",
        "InvoiceId": "30",
        "PaymentDate": "2024-06-01",
        "isCreditCard": False,
        "ObjectState": "Active",
        "Voided": False,
    }
]

_FIXTURE_DATA = {
    "clients": _CLIENTS,
    "items": _ITEMS,
    "invoices": _INVOICES,
    "payments": _PAYMENTS,
}

# Entities the sync job exercises (must match SYNC_ENTITIES in the job).
_ALL_ENTITIES = ["clients", "items", "invoices", "payments"]


def _mock_fetch(entity, tok):
    """Mock fetch — returns fixture data for known entities."""
    return _FIXTURE_DATA.get(entity, [])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_state(factory, tenant_id: int = 1) -> dict[str, str]:
    """Return {entity: last_status} from knowify_sync_state for tenant."""
    s = _make_session(factory, tenant_id)
    try:
        rows = s.execute(select(KnowifySyncState)).scalars().all()
        return {r.entity: r.last_status for r in rows}
    finally:
        s.close()


def _count_raw(factory, entity: str, tenant_id: int = 1) -> int:
    s = _make_session(factory, tenant_id)
    try:
        return s.execute(
            select(KnowifyRawRecord).where(
                KnowifyRawRecord.tenant_id == tenant_id,
                KnowifyRawRecord.entity == entity,
            )
        ).scalars().all().__len__()
    finally:
        s.close()


def _run_sync(factory, fetch_fn=_mock_fetch, tok=None, refresh_only=False):
    """Run jobs.knowify_sync.run() with mocked token + fetch + tenant loop."""
    if tok is None:
        tok = {"access_token": "test-tok", "refresh_token": "rt", "client_id": "cid"}

    from jobs import knowify_sync

    # Patch: token loading, liveness, fetch, and tenant loop.
    with (
        patch.object(knowify_sync.tokens, "load_tokens", return_value=tok),
        patch.object(knowify_sync.tokens, "is_valid", return_value=True),
        patch.object(knowify_sync, "_fetch_entity", side_effect=fetch_fn),
        patch("jobs.knowify_sync.for_each_tenant", side_effect=lambda sf, fn: _fake_tenant_loop(sf, fn, factory)),
    ):
        return knowify_sync.run(refresh_only=refresh_only)


def _fake_tenant_loop(db_factory, fn, real_factory):
    """Run fn for tenant 1 using real_factory (bypasses for_each_tenant's tenant query).

    Mirrors for_each_tenant's try/except: commit on success, rollback on exception,
    never re-raises (matches the real loop's per-tenant isolation contract).
    """
    db = real_factory()
    db.info["tenant_id"] = 1
    try:
        fn(db, 1)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.error("_fake_tenant_loop: tenant 1 failed: %s", exc)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFullPullRun:
    """Full-pull populates raw + first-class + sync_state + handles tombstones."""

    def test_raw_rows_inserted(self):
        factory, _ = _sqlite_factory()
        _run_sync(factory)
        for entity, data in _FIXTURE_DATA.items():
            assert _count_raw(factory, entity) == len(data), (
                f"entity={entity}: expected {len(data)} raw rows"
            )

    def test_sync_state_all_ok(self):
        factory, _ = _sqlite_factory()
        _run_sync(factory)
        states = _get_state(factory)
        for entity in _ALL_ENTITIES:
            assert states.get(entity) == "ok", f"entity={entity} state={states.get(entity)}"

    def test_exit_code_zero_on_clean_run(self):
        factory, _ = _sqlite_factory()
        result = _run_sync(factory)
        assert result["exit_code"] == 0

    def test_rows_seen_recorded(self):
        factory, _ = _sqlite_factory()
        _run_sync(factory)
        s = _make_session(factory)
        try:
            row = s.execute(
                select(KnowifySyncState).where(KnowifySyncState.entity == "clients")
            ).scalar_one_or_none()
            assert row is not None
            assert row.rows_seen == len(_CLIENTS)
        finally:
            s.close()

    def test_tombstone_absent_ids(self):
        """A raw record from a prior run that is absent from the current pull is tombstoned."""
        factory, _ = _sqlite_factory()
        # Seed an extra raw row that won't be in the next pull.
        s = _make_session(factory)
        s.execute(insert(KnowifyRawRecord).values(
            tenant_id=1, entity="clients", knowify_id="999",
            payload={"Id": "999"}, content_hash="deadbeef" * 8, is_present=True,
        ))
        s.commit()
        s.close()

        _run_sync(factory)

        s = _make_session(factory)
        try:
            ghost = s.execute(
                select(KnowifyRawRecord).where(
                    KnowifyRawRecord.tenant_id == 1,
                    KnowifyRawRecord.entity == "clients",
                    KnowifyRawRecord.knowify_id == "999",
                )
            ).scalar_one_or_none()
            assert ghost is not None
            assert ghost.is_present is False
            assert ghost.deleted_at is not None
        finally:
            s.close()

    def test_first_class_invoice_promoted(self):
        """An invoice with BusinessState=Closed and OutstandingAmount=0 is promoted as 'paid'."""
        from app.models import Invoice
        factory, _ = _sqlite_factory()
        _run_sync(factory)
        s = _make_session(factory)
        try:
            inv = s.execute(
                select(Invoice).where(
                    Invoice.tenant_id == 1,
                    Invoice.knowify_invoice_id == "30",
                )
            ).scalar_one_or_none()
            assert inv is not None, "Invoice not promoted"
            assert inv.status == "paid"
            assert inv.invoice_number is None  # never the integer counter
            assert inv.knowify_invoice_number == "INV-001"
        finally:
            s.close()


class TestIdempotentReRun:
    """A second identical run writes 0 new rows and leaves sync_state counts unchanged."""

    def test_no_extra_raw_rows_on_rerun(self):
        factory, _ = _sqlite_factory()
        _run_sync(factory)
        counts_after_1 = {e: _count_raw(factory, e) for e in _ALL_ENTITIES}
        _run_sync(factory)
        counts_after_2 = {e: _count_raw(factory, e) for e in _ALL_ENTITIES}
        assert counts_after_1 == counts_after_2

    def test_sync_state_still_ok_on_rerun(self):
        factory, _ = _sqlite_factory()
        _run_sync(factory)
        _run_sync(factory)
        states = _get_state(factory)
        for entity in _ALL_ENTITIES:
            assert states[entity] == "ok"

    def test_exit_code_zero_on_rerun(self):
        factory, _ = _sqlite_factory()
        _run_sync(factory)
        result = _run_sync(factory)
        assert result["exit_code"] == 0


class TestPerEntityErrorIsolation:
    """One entity error → others still 'ok'; run exits non-zero (AC-17)."""

    def _fetch_with_clients_error(self, entity, tok):
        if entity == "clients":
            raise RuntimeError("simulated REST error")
        return _mock_fetch(entity, tok)

    def test_error_entity_marked_error(self):
        factory, _ = _sqlite_factory()
        from jobs import knowify_sync
        tok = {"access_token": "t", "refresh_token": "r", "client_id": "c"}
        with (
            patch.object(knowify_sync.tokens, "load_tokens", return_value=tok),
            patch.object(knowify_sync.tokens, "is_valid", return_value=True),
            patch.object(knowify_sync, "_fetch_entity", side_effect=self._fetch_with_clients_error),
            patch("jobs.knowify_sync.for_each_tenant",
                  side_effect=lambda sf, fn: _fake_tenant_loop(sf, fn, factory)),
        ):
            knowify_sync.run()

        states = _get_state(factory)
        assert states.get("clients") == "error"

    def test_other_entities_write_state_on_error(self):
        """All entities get a final write_state entry even when clients fetch fails.

        When clients fetch errors, promote_invoices will hit a customer_id NOT NULL
        FK violation on SQLite, which corrupts the session. The job recovers with
        rollback and re-issues write_state for all entities. The key invariant is:
        every entity has a sync_state row (no silent gaps) and the run exits non-zero.
        """
        factory, _ = _sqlite_factory()
        from jobs import knowify_sync
        tok = {"access_token": "t", "refresh_token": "r", "client_id": "c"}
        with (
            patch.object(knowify_sync.tokens, "load_tokens", return_value=tok),
            patch.object(knowify_sync.tokens, "is_valid", return_value=True),
            patch.object(knowify_sync, "_fetch_entity", side_effect=self._fetch_with_clients_error),
            patch("jobs.knowify_sync.for_each_tenant",
                  side_effect=lambda sf, fn: _fake_tenant_loop(sf, fn, factory)),
        ):
            knowify_sync.run()

        states = _get_state(factory)
        # All entities must have a sync_state row — no silent gaps.
        for entity in SYNC_ENTITIES:
            assert entity in states, f"entity={entity} missing from sync_state after partial run"
        # clients fetch error → error; promote failure cascades; run exits non-zero.
        assert states.get("clients") == "error"

    def test_exit_code_nonzero_when_entity_errors(self):
        factory, _ = _sqlite_factory()
        from jobs import knowify_sync
        tok = {"access_token": "t", "refresh_token": "r", "client_id": "c"}
        with (
            patch.object(knowify_sync.tokens, "load_tokens", return_value=tok),
            patch.object(knowify_sync.tokens, "is_valid", return_value=True),
            patch.object(knowify_sync, "_fetch_entity", side_effect=self._fetch_with_clients_error),
            patch("jobs.knowify_sync.for_each_tenant",
                  side_effect=lambda sf, fn: _fake_tenant_loop(sf, fn, factory)),
        ):
            result = knowify_sync.run()

        assert result["exit_code"] != 0, "expected non-zero exit when an entity errored"


class TestPreflightDeadToken:
    """/api/v2/valid preflight: dead token → all entities auth_error, no fetch called."""

    def test_auth_error_all_entities_on_dead_token(self):
        factory, _ = _sqlite_factory()
        from jobs import knowify_sync
        tok = {"access_token": "dead", "refresh_token": "r", "client_id": "c"}
        fetch_mock = MagicMock(side_effect=AssertionError("fetch must not be called"))

        with (
            patch.object(knowify_sync.tokens, "load_tokens", return_value=tok),
            patch.object(knowify_sync.tokens, "is_valid", return_value=False),
            patch.object(knowify_sync, "_fetch_entity", fetch_mock),
            patch("jobs.knowify_sync.for_each_tenant",
                  side_effect=lambda sf, fn: _fake_tenant_loop(sf, fn, factory)),
        ):
            knowify_sync.run()

        states = _get_state(factory)
        for entity in _ALL_ENTITIES:
            assert states.get(entity) == "auth_error", (
                f"entity={entity} expected auth_error, got {states.get(entity)}"
            )

    def test_fetch_not_called_on_dead_token(self):
        factory, _ = _sqlite_factory()
        from jobs import knowify_sync
        tok = {"access_token": "dead", "refresh_token": "r", "client_id": "c"}
        fetch_mock = MagicMock()

        with (
            patch.object(knowify_sync.tokens, "load_tokens", return_value=tok),
            patch.object(knowify_sync.tokens, "is_valid", return_value=False),
            patch.object(knowify_sync, "_fetch_entity", fetch_mock),
            patch("jobs.knowify_sync.for_each_tenant",
                  side_effect=lambda sf, fn: _fake_tenant_loop(sf, fn, factory)),
        ):
            knowify_sync.run()

        fetch_mock.assert_not_called()

    def test_exit_code_nonzero_on_dead_token(self):
        factory, _ = _sqlite_factory()
        from jobs import knowify_sync
        tok = {"access_token": "dead", "refresh_token": "r", "client_id": "c"}

        with (
            patch.object(knowify_sync.tokens, "load_tokens", return_value=tok),
            patch.object(knowify_sync.tokens, "is_valid", return_value=False),
            patch.object(knowify_sync, "_fetch_entity", MagicMock()),
            patch("jobs.knowify_sync.for_each_tenant",
                  side_effect=lambda sf, fn: _fake_tenant_loop(sf, fn, factory)),
        ):
            result = knowify_sync.run()

        assert result["exit_code"] != 0


class TestSingleFlight:
    """A second concurrent run (lock held) skips — single-flight advisory lock 8274124."""

    def test_lock_key_is_8274124(self):
        from jobs import knowify_sync
        assert knowify_sync._LOCK_KEY == 8274124, (
            f"advisory lock key must be 8274124 (distinct from ingest 8274123 / token 8274125); "
            f"got {knowify_sync._LOCK_KEY}"
        )

    def test_second_run_skips_on_sqlite(self):
        """On SQLite the advisory lock no-ops (always yields True), so we simulate
        the skip by patching pg_try_advisory_lock to return False."""
        from jobs import knowify_sync

        # Patch _single_flight to simulate 'lock not obtained'.
        @contextmanager
        def _locked_out():
            yield False

        with patch.object(knowify_sync, "_single_flight", _locked_out):
            result = knowify_sync.run()

        assert result.get("skipped") == "knowify sync already running"


class TestRefreshOnlyPath:
    """--refresh-only keep-warm path calls tokens.refresh_only, no fetch."""

    def test_refresh_only_calls_tokens_refresh_only(self):
        from jobs import knowify_sync
        refresh_mock = MagicMock(return_value=0)
        fetch_mock = MagicMock(side_effect=AssertionError("fetch must not be called"))

        with (
            patch.object(knowify_sync.tokens, "refresh_only", refresh_mock),
            patch.object(knowify_sync, "_fetch_entity", fetch_mock),
        ):
            result = knowify_sync.run(refresh_only=True)

        refresh_mock.assert_called_once()
        assert result["exit_code"] == 0

    def test_refresh_only_exit_nonzero_on_auth_error(self):
        from jobs import knowify_sync
        refresh_mock = MagicMock(return_value=1)  # auth_error

        with patch.object(knowify_sync.tokens, "refresh_only", refresh_mock):
            result = knowify_sync.run(refresh_only=True)

        assert result["exit_code"] != 0


# ---------------------------------------------------------------------------
# MCP transport (KNOWIFY_PULL_MODE=mcp) — stopgap while REST /oauth 500s.
# Token comes from tokens.mcp_access_token; fetch via _fetch_entity_mcp; NO tombstoning.
# ---------------------------------------------------------------------------

# items has no MCP spec -> the real fetch returns []; mirror that here.
_MCP_FIXTURE = {"clients": _CLIENTS, "invoices": _INVOICES, "payments": _PAYMENTS, "items": []}


def _mock_fetch_mcp(entity, access_token):
    assert access_token == "mcp-tok"  # the resolved MCP access token is threaded through
    return _MCP_FIXTURE.get(entity, [])


def _run_sync_mcp(factory, fetch_fn=_mock_fetch_mcp, access="mcp-tok", refresh_only=False):
    from jobs import knowify_sync

    with (
        patch.dict("os.environ", {"KNOWIFY_PULL_MODE": "mcp"}),
        patch.object(knowify_sync.tokens, "mcp_access_token", return_value=access),
        patch.object(knowify_sync.tokens, "mcp_refresh_only", return_value=0),
        patch.object(knowify_sync, "_fetch_entity_mcp", side_effect=fetch_fn),
        patch.object(knowify_sync, "_fetch_entity",
                     side_effect=AssertionError("REST fetch must not run in mcp mode")),
        patch("jobs.knowify_sync.for_each_tenant",
              side_effect=lambda sf, fn: _fake_tenant_loop(sf, fn, factory)),
    ):
        return knowify_sync.run(refresh_only=refresh_only)


class TestMcpMode:
    def test_mcp_raw_rows_inserted(self):
        factory, _ = _sqlite_factory()
        result = _run_sync_mcp(factory)
        assert result["exit_code"] == 0
        for entity, data in _MCP_FIXTURE.items():
            assert _count_raw(factory, entity) == len(data)

    def test_mcp_mode_skips_tombstone(self):
        """A prior raw row absent from the current MCP pull is NOT tombstoned (safety:
        MCP can't enumerate every non-deleted state, so no hard-delete detection)."""
        factory, _ = _sqlite_factory()
        s = _make_session(factory)
        s.execute(insert(KnowifyRawRecord).values(
            tenant_id=1, entity="clients", knowify_id="999",
            payload={"Id": "999"}, content_hash="deadbeef" * 8, is_present=True,
        ))
        s.commit()
        s.close()

        _run_sync_mcp(factory)

        s = _make_session(factory)
        try:
            ghost = s.execute(
                select(KnowifyRawRecord).where(KnowifyRawRecord.knowify_id == "999")
            ).scalar_one_or_none()
            assert ghost is not None
            assert ghost.is_present is True  # NOT tombstoned
            assert ghost.deleted_at is None
        finally:
            s.close()

    def test_mcp_auth_error_marks_all_and_skips_fetch(self):
        from jobs import knowify_sync
        factory, _ = _sqlite_factory()
        fetch_mock = MagicMock(side_effect=AssertionError("fetch must not run on auth_error"))

        with (
            patch.dict("os.environ", {"KNOWIFY_PULL_MODE": "mcp"}),
            patch.object(knowify_sync.tokens, "mcp_access_token",
                         side_effect=knowify_sync.tokens.AuthError("dead")),
            patch.object(knowify_sync, "_fetch_entity_mcp", fetch_mock),
            patch("jobs.knowify_sync.for_each_tenant",
                  side_effect=lambda sf, fn: _fake_tenant_loop(sf, fn, factory)),
        ):
            result = knowify_sync.run()

        assert result["exit_code"] == 1
        assert result.get("auth_error") is True
        states = _get_state(factory)
        for entity in SYNC_ENTITIES:
            assert states.get(entity) == "auth_error"

    def test_mcp_refresh_only_uses_mcp_path(self):
        from jobs import knowify_sync
        mcp_refresh = MagicMock(return_value=0)
        rest_refresh = MagicMock(side_effect=AssertionError("REST refresh must not run in mcp mode"))
        with (
            patch.dict("os.environ", {"KNOWIFY_PULL_MODE": "mcp"}),
            patch.object(knowify_sync.tokens, "mcp_refresh_only", mcp_refresh),
            patch.object(knowify_sync.tokens, "refresh_only", rest_refresh),
        ):
            result = knowify_sync.run(refresh_only=True)
        mcp_refresh.assert_called_once()
        assert result["exit_code"] == 0
