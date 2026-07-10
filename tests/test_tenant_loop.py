"""Tests for core/tenant_loop.py and core/metering.py — F5-a.

All red before implementation; run with:
    pytest tests/test_tenant_loop.py -v
"""
from __future__ import annotations

import logging
import threading
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db_factory(tenant_ids: list[int], *, strict: bool = False):
    """Return a callable db_factory that returns mock Session objects.

    Each session:
    - is a context manager (supports `with db_factory() as db:`)
    - tracks session.info["tenant_id"] so the loop can stamp it
    - supports db.execute(), db.commit(), db.rollback(), db.close()
    """
    sessions: list[MagicMock] = []

    class _FakeSession:
        def __init__(self):
            self.info: dict = {}
            self._committed = False
            self._rolled_back = False
            self._closed = False
            self._executions: list = []

        def execute(self, stmt, params=None):
            self._executions.append((stmt, params))
            # Fake fetchall for the active_tenants query
            result = MagicMock()
            result.fetchall.return_value = [(tid,) for tid in tenant_ids]
            return result

        def commit(self):
            self._committed = True

        def rollback(self):
            self._rolled_back = True

        def close(self):
            self._closed = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()
            return False

    def factory():
        s = _FakeSession()
        sessions.append(s)
        return s

    factory.sessions = sessions  # type: ignore[attr-defined]
    return factory


# ---------------------------------------------------------------------------
# for_each_tenant tests
# ---------------------------------------------------------------------------

class TestForEachTenant:
    def test_iterates_active_tenants_only(self):
        """fn is called once per active tenant; inactive tenants are skipped."""
        # We control what active_tenants() returns via the mock execute
        from core.tenant_loop import for_each_tenant

        called_with: list[int] = []

        def fn(db, tenant_id: int) -> None:
            called_with.append(tenant_id)

        factory = _make_db_factory([1, 2])
        for_each_tenant(factory, fn)

        assert called_with == [1, 2]

    def test_exception_does_not_abort_loop(self):
        """fn raising for tenant 2 does not prevent tenant 3 from running."""
        from core.tenant_loop import for_each_tenant

        called_with: list[int] = []

        def fn(db, tenant_id: int) -> None:
            if tenant_id == 2:
                raise RuntimeError("tenant 2 exploded")
            called_with.append(tenant_id)

        factory = _make_db_factory([1, 2, 3])
        for_each_tenant(factory, fn)

        assert 1 in called_with
        assert 3 in called_with
        assert 2 not in called_with

    def test_exception_is_logged_with_tenant_id(self, caplog):
        """Exceptions are logged with the tenant_id in the message."""
        from core.tenant_loop import for_each_tenant

        def fn(db, tenant_id: int) -> None:
            if tenant_id == 2:
                raise RuntimeError("boom")

        factory = _make_db_factory([1, 2])
        with caplog.at_level(logging.ERROR, logger="core.tenant_loop"):
            for_each_tenant(factory, fn)

        assert any("2" in r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)

    def test_sets_tenant_context_on_session(self):
        """session.info['tenant_id'] is stamped before fn is called."""
        from core.tenant_loop import for_each_tenant

        stamped: list[int] = []

        def fn(db, tenant_id: int) -> None:
            stamped.append(db.info.get("tenant_id"))

        factory = _make_db_factory([1, 2])
        for_each_tenant(factory, fn)

        assert stamped == [1, 2]

    def test_single_tenant_called_once(self):
        """With exactly one active tenant, fn is called exactly once."""
        from core.tenant_loop import for_each_tenant

        count = 0

        def fn(db, tenant_id: int) -> None:
            nonlocal count
            count += 1

        factory = _make_db_factory([1])
        for_each_tenant(factory, fn)

        assert count == 1

    def test_no_active_tenants_fn_never_called(self):
        """With no active tenants, fn is never called."""
        from core.tenant_loop import for_each_tenant

        called = False

        def fn(db, tenant_id: int) -> None:
            nonlocal called
            called = True

        factory = _make_db_factory([])
        for_each_tenant(factory, fn)

        assert not called

    def test_db_closed_after_each_tenant(self):
        """Each tenant's session is closed even if fn raises."""
        from core.tenant_loop import for_each_tenant

        def fn(db, tenant_id: int) -> None:
            if tenant_id == 2:
                raise RuntimeError("fail")

        factory = _make_db_factory([1, 2])
        for_each_tenant(factory, fn)

        # Platform session + two per-tenant sessions = 3 sessions
        # All per-tenant sessions must be closed
        per_tenant = [s for s in factory.sessions if hasattr(s, "_closed")]
        # At minimum the two tenant sessions must have been closed
        closed_sessions = [s for s in factory.sessions if s._closed]
        assert len(closed_sessions) >= 2


# ---------------------------------------------------------------------------
# Metering / cost tracker tests
# ---------------------------------------------------------------------------

class TestCostTracker:
    def test_reset_clears_counters(self):
        """reset(tenant_id) initialises all counters to zero."""
        import core.metering as metering

        metering.reset(tenant_id=1)
        c = metering._counters.get()
        assert c["llm_tokens"] == 0
        assert c["stt_minutes"] == 0.0
        assert c["render_minutes"] == 0.0
        assert c["tenant_id"] == 1

    def test_add_accumulates(self):
        """add() increments the named metric."""
        import core.metering as metering

        metering.reset(tenant_id=1)
        metering.add("llm_tokens", 100)
        metering.add("llm_tokens", 250)
        metering.add("stt_minutes", 1.5)

        c = metering._counters.get()
        assert c["llm_tokens"] == 350
        assert c["stt_minutes"] == 1.5

    def test_flush_returns_and_resets(self):
        """flush() returns accumulated totals and clears the counter."""
        import core.metering as metering

        metering.reset(tenant_id=42)
        metering.add("llm_tokens", 500)
        metering.add("render_minutes", 2.0)

        result = metering.flush()

        assert result["tenant_id"] == 42
        assert result["llm_tokens"] == 500
        assert result["render_minutes"] == 2.0

        # After flush, counters are cleared
        after = metering._counters.get()
        assert after == {}

    def test_add_outside_context_is_noop(self):
        """add() called before reset() (no active context) silently no-ops."""
        import core.metering as metering

        # Clear any prior state
        metering._counters.set({})
        metering.add("llm_tokens", 999)  # should not raise

        # Counter still empty
        assert metering._counters.get() == {}

    def test_counters_isolated_between_threads(self):
        """ContextVar isolation: two threads get independent counters."""
        import core.metering as metering

        results: dict[int, dict] = {}

        def worker(tid: int) -> None:
            metering.reset(tenant_id=tid)
            metering.add("llm_tokens", tid * 100)
            results[tid] = metering.flush()

        t1 = threading.Thread(target=worker, args=(1,))
        t2 = threading.Thread(target=worker, args=(2,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Each thread's counters must reflect only its own additions
        assert results[1]["llm_tokens"] == 100
        assert results[2]["llm_tokens"] == 200

    def test_for_each_tenant_resets_counter_between_tenants(self):
        """for_each_tenant calls reset() before each tenant so counters don't bleed."""
        import core.metering as metering
        from core.tenant_loop import for_each_tenant

        snapshots: list[dict] = []

        def fn(db, tenant_id: int) -> None:
            # Accumulate some tokens
            metering.add("llm_tokens", tenant_id * 10)
            snapshots.append(dict(metering._counters.get()))

        factory = _make_db_factory([1, 2])
        for_each_tenant(factory, fn)

        # Tenant 1 should have only its own tokens (10), not bleed into tenant 2
        assert snapshots[0]["llm_tokens"] == 10
        # Tenant 2 starts fresh so gets only 20, not 10+20=30
        assert snapshots[1]["llm_tokens"] == 20

    def test_for_each_tenant_flushes_counter_after_each_tenant(self):
        """for_each_tenant calls flush() after each tenant — structured log is emitted."""
        from core.tenant_loop import for_each_tenant

        factory = _make_db_factory([1])

        with patch("core.metering.flush") as mock_flush:
            mock_flush.return_value = {"tenant_id": 1, "llm_tokens": 0}
            # We need reset to still work so we patch only flush
            from core import metering as _m
            _m._counters.set({})  # Clear state

            def fn(db, tenant_id: int) -> None:
                pass

            for_each_tenant(factory, fn)

        mock_flush.assert_called()

    def test_soft_cap_exceeded_skips_tenant(self, caplog):
        """When a tenant's MTD usage exceeds the soft cap, fn is skipped and WARNING logged."""
        from core.tenant_loop import for_each_tenant

        called_with: list[int] = []

        def fn(db, tenant_id: int) -> None:
            called_with.append(tenant_id)

        # Patch load_caps to return a cap that's already exceeded for tenant 2
        with patch("core.tenant_loop._check_soft_caps") as mock_check:
            # Return True (cap exceeded) for tenant 2, False for tenant 1
            def _check(tenant_id):
                return tenant_id == 2  # True = exceeded
            mock_check.side_effect = _check

            factory = _make_db_factory([1, 2])
            with caplog.at_level(logging.WARNING, logger="core.tenant_loop"):
                for_each_tenant(factory, fn)

        # Tenant 1 ran, tenant 2 was skipped
        assert 1 in called_with
        assert 2 not in called_with
        assert any("cap" in r.getMessage().lower() or "metering" in r.getMessage().lower()
                   for r in caplog.records if r.levelno >= logging.WARNING)


# ---------------------------------------------------------------------------
# Metering flush emits structured log
# ---------------------------------------------------------------------------

class TestMeteringFlushLog:
    def test_flush_with_structured_log(self, caplog):
        """flush(emit=True) emits a structured log event."""
        import core.metering as metering

        metering.reset(tenant_id=5)
        metering.add("llm_tokens", 300)

        with caplog.at_level(logging.INFO, logger="core.metering"):
            metering.flush(emit=True)

        # Should emit a log record
        assert any("llm_tokens" in r.getMessage() or "metering" in r.getMessage().lower()
                   for r in caplog.records)

    def test_flush_no_emit_by_default(self, caplog):
        """flush() without emit=True does not log — for tests that just want the dict."""
        import core.metering as metering

        metering.reset(tenant_id=5)
        metering.add("llm_tokens", 100)

        with caplog.at_level(logging.DEBUG, logger="core.metering"):
            result = metering.flush()

        assert result["llm_tokens"] == 100
        # No structured metering log
        metering_logs = [r for r in caplog.records if "metering" in r.getMessage().lower()]
        assert metering_logs == []


def test_metering_flush_empty_returns_empty_dict():
    """flush() with no counters in context returns {} (early return, no log emit)."""
    from core import metering
    metering._counters.set({})
    assert metering.flush(emit=True) == {}


class TestEnumerationPlatformScope:
    def test_enumeration_session_is_platform_scoped(self):
        """C1 Part 2 step 2: the tenants-enumeration session must carry
        platform_scope=True so the strict after_begin event neither raises nor
        stamps a tenant GUC. Per-tenant sessions stay tenant-stamped."""
        from core.tenant_loop import for_each_tenant

        factory = _make_db_factory([1])
        for_each_tenant(factory, lambda db, tid: None)

        enum_session = factory.sessions[0]
        assert enum_session.info.get("platform_scope") is True
        tenant_session = factory.sessions[1]
        assert tenant_session.info.get("tenant_id") == 1
        assert "platform_scope" not in tenant_session.info
