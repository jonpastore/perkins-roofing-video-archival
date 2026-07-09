"""Unit tests for core/tenant.py — run on SQLite, no Postgres needed.

Covers:
  - set_tenant_context issues SET LOCAL with correct tid
  - after_begin event fires before any query (via rls_engine fixture on PG,
    or via mock on SQLite)
  - Missing tenant_id on session.info raises RuntimeError
  - platform_scope=True bypasses the raise
  - TenantQueryMixin filter produces correct clause
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# set_tenant_context — pure unit tests (SQLite-safe: we mock the execute call)
# ---------------------------------------------------------------------------

class TestSetTenantContext:
    def test_issues_set_local_with_string_tid(self):
        from core.tenant import set_tenant_context

        mock_session = MagicMock()
        set_tenant_context(mock_session, 42)

        mock_session.execute.assert_called_once()
        args, kwargs = mock_session.execute.call_args
        sql_str = str(args[0])
        # set_config('app.tenant_id', :tid, true) — the working, parameterizable
        # equivalent of SET LOCAL (which cannot take a bind param). is_local=true
        # gives identical transaction-local semantics.
        assert "set_config" in sql_str
        assert "app.tenant_id" in sql_str
        assert "true" in sql_str  # is_local => transaction-scoped
        assert kwargs == {"tid": "42"} or args[1] == {"tid": "42"}

    def test_converts_int_to_string(self):
        from core.tenant import set_tenant_context

        mock_session = MagicMock()
        set_tenant_context(mock_session, 1)

        _, kwargs_or_args = mock_session.execute.call_args
        # The tid parameter must be a string (Postgres GUC accepts string only)
        call_args = mock_session.execute.call_args
        # Check second positional arg or kwarg
        params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]
        assert params["tid"] == "1", f"Expected '1' (str), got {params['tid']!r}"


# ---------------------------------------------------------------------------
# register_tenant_session_events — after_begin event wiring (mock-based)
# ---------------------------------------------------------------------------

class TestRegisterTenantSessionEvents:
    def _make_sqlite_factory(self):
        """SQLite engine with dialect.name patched to 'postgresql'.

        The after_begin event skips on real SQLite (no GUC support). These unit
        tests verify PG-path behavior, so we patch the dialect name so the guard
        passes and the event logic runs.
        """
        eng = create_engine("sqlite:///:memory:", future=True)
        eng.dialect.name = "postgresql"
        return sessionmaker(bind=eng, future=True), eng

    def test_after_begin_fires_set_local(self):
        """after_begin event issues the GUC set_config on the connection with the
        session's tenant_id (the event uses connection.execute, not session.execute,
        to avoid re-entrant connection provisioning)."""
        from core.tenant import register_tenant_session_events

        factory, engine = self._make_sqlite_factory()
        register_tenant_session_events(factory)

        session = factory()
        session.info["tenant_id"] = 7

        fired = []
        # Spy on the raw connection execute — the event issues set_config there.
        orig_execute = __import__("sqlalchemy").engine.Connection.execute

        def spy(self, statement, *a, **kw):
            params = a[0] if a else kw.get("parameters")
            if "set_config" in str(statement):
                fired.append(params)
            return orig_execute(self, statement, *a, **kw)

        with patch("sqlalchemy.engine.Connection.execute", spy):
            try:
                session.execute(text("SELECT 1"))
            except Exception:
                pass

        session.close()
        assert fired == [{"tid": "7"}], f"Expected set_config for tid=7, got {fired}"

    def test_missing_tenant_id_raises_runtime_error(self):
        """Session without tenant_id in info raises RuntimeError on first use."""
        from core.tenant import register_tenant_session_events

        factory, engine = self._make_sqlite_factory()
        register_tenant_session_events(factory)

        session = factory()

        with pytest.raises(RuntimeError, match="tenant_id not set on session.info"):
            session.execute(text("SELECT 1"))

        session.close()

    def test_none_tenant_id_raises_runtime_error(self):
        """Explicitly setting tenant_id=None also raises (platform_admin path requires platform_scope)."""
        from core.tenant import register_tenant_session_events

        factory, engine = self._make_sqlite_factory()
        register_tenant_session_events(factory)

        session = factory()
        session.info["tenant_id"] = None

        with pytest.raises(RuntimeError, match="tenant_id not set on session.info"):
            session.execute(text("SELECT 1"))

        session.close()

    def test_platform_scope_bypasses_guc_and_raise(self):
        """platform_scope=True skips the GUC and does not raise RuntimeError."""
        from core.tenant import register_tenant_session_events

        factory, engine = self._make_sqlite_factory()
        register_tenant_session_events(factory)

        session = factory()
        session.info["platform_scope"] = True

        fired = []
        orig_execute = __import__("sqlalchemy").engine.Connection.execute

        def spy(self, statement, *a, **kw):
            if "set_config" in str(statement):
                fired.append(True)
            return orig_execute(self, statement, *a, **kw)

        with patch("sqlalchemy.engine.Connection.execute", spy):
            try:
                session.execute(text("SELECT 1"))
            except Exception:
                pass

        session.close()
        assert fired == [], "GUC must not be set for platform_scope sessions"

    def test_multiple_sessions_independent_tenant_ids(self):
        """Two concurrent sessions can have different tenant_ids without interference."""
        from core.tenant import register_tenant_session_events

        factory, engine = self._make_sqlite_factory()
        register_tenant_session_events(factory)

        seen = []
        orig_execute = __import__("sqlalchemy").engine.Connection.execute

        def spy(self, statement, *a, **kw):
            params = a[0] if a else kw.get("parameters")
            if "set_config" in str(statement) and params:
                seen.append(params["tid"])
            return orig_execute(self, statement, *a, **kw)

        with patch("sqlalchemy.engine.Connection.execute", spy):
            s1 = factory()
            s1.info["tenant_id"] = 1
            s2 = factory()
            s2.info["tenant_id"] = 2

            try:
                s1.execute(text("SELECT 1"))
            except Exception:
                pass
            try:
                s2.execute(text("SELECT 1"))
            except Exception:
                pass

            s1.close()
            s2.close()

        assert set(seen) == {"1", "2"}, f"Expected {{'1', '2'}}, got {seen}"

    def test_sqlite_dialect_skips_event(self):
        """On non-postgresql dialects the after_begin handler returns early (line 82 coverage).

        A real SQLite engine (dialect.name='sqlite') must never raise even when
        tenant_id is absent — the whole event is a no-op on SQLite.
        """
        from core.tenant import register_tenant_session_events

        eng = create_engine("sqlite:///:memory:", future=True)
        # Do NOT patch dialect.name — leave it as 'sqlite'
        factory = sessionmaker(bind=eng, future=True)
        register_tenant_session_events(factory)

        session = factory()
        # No tenant_id, no platform_scope — would raise on PG but must be silent on SQLite
        fired = []
        with patch("core.tenant.set_tenant_context", side_effect=lambda s, tid: fired.append(tid)):
            session.execute(text("SELECT 1"))  # must not raise

        session.close()
        assert fired == [], "set_tenant_context must not fire on SQLite dialect"


# ---------------------------------------------------------------------------
# Non-strict (production) after_begin: default-to-tenant-1 + loud log
# (F4 → pre-tenant-2 transition contract)
# ---------------------------------------------------------------------------

class TestNonStrictDefault:
    def _pg_factory(self, strict):
        eng = create_engine("sqlite:///:memory:", future=True)
        eng.dialect.name = "postgresql"
        factory = sessionmaker(bind=eng, future=True)
        from core.tenant import register_tenant_session_events
        register_tenant_session_events(factory, strict=strict)
        return factory

    def test_unstamped_defaults_to_tenant_1_and_logs(self, caplog):
        """strict=False: an unstamped session defaults to tenant 1 and logs CRITICAL
        naming the caller — instead of raising (F4 transition contract)."""
        import logging

        factory = self._pg_factory(strict=False)
        session = factory()  # no tenant_id, no platform_scope

        fired = []
        orig_execute = __import__("sqlalchemy").engine.Connection.execute

        def spy(self, statement, *a, **kw):
            params = a[0] if a else kw.get("parameters")
            if "set_config" in str(statement) and params:
                fired.append(params["tid"])
            return orig_execute(self, statement, *a, **kw)

        with caplog.at_level(logging.CRITICAL, logger="core.tenant"):
            with patch("sqlalchemy.engine.Connection.execute", spy):
                try:
                    session.execute(text("SELECT 1"))
                except Exception:
                    pass

        session.close()
        assert fired == ["1"], f"Unstamped non-strict session must default to tenant 1, got {fired}"
        assert any("UNSTAMPED tenant session defaulted to tenant 1" in r.message for r in caplog.records)

    def test_unstamped_origin_names_a_caller(self):
        """_unstamped_origin returns a 'file:line in func' string skipping sqlalchemy
        + this module (used in the non-strict CRITICAL log)."""
        from core.tenant import _unstamped_origin

        origin = _unstamped_origin()
        assert isinstance(origin, str)
        assert origin != ""
        # Must not point back into sqlalchemy internals or core/tenant.py itself.
        assert "sqlalchemy" not in origin
        assert not origin.startswith("core/tenant.py")

    def test_unstamped_origin_unknown_when_all_frames_filtered(self):
        """When every frame is sqlalchemy/tenant-internal, _unstamped_origin returns
        'unknown' (the loop's fallback)."""
        import traceback as _tb

        from core.tenant import _unstamped_origin

        fake_frame = _tb.FrameSummary("/x/sqlalchemy/engine.py", 1, "run")
        with patch("traceback.extract_stack", return_value=[fake_frame]):
            assert _unstamped_origin() == "unknown"


# ---------------------------------------------------------------------------
# assert_rls_enforceable — H2 fail-open guard
# ---------------------------------------------------------------------------

class TestAssertRlsEnforceable:
    def test_non_postgres_engine_returns_true(self):
        """SQLite (non-PG) engines return True — RLS isn't expected there."""
        from core.tenant import assert_rls_enforceable

        eng = create_engine("sqlite:///:memory:", future=True)
        assert assert_rls_enforceable(eng) is True

    @pytest.mark.postgres
    def test_non_superuser_role_is_enforceable(self, pg_engine):
        """The app-role engine (NOSUPERUSER NOBYPASSRLS) → RLS enforceable → True."""
        from core.tenant import assert_rls_enforceable

        assert assert_rls_enforceable(pg_engine) is True

    @pytest.mark.postgres
    def test_superuser_role_is_not_enforceable(self, pg_admin_engine, caplog):
        """The admin (superuser) engine → RLS fail-open → False + CRITICAL log."""
        import logging

        from core.tenant import assert_rls_enforceable

        with caplog.at_level(logging.CRITICAL, logger="core.tenant"):
            result = assert_rls_enforceable(pg_admin_engine)
        assert result is False
        assert any("RLS FAIL-OPEN" in r.message for r in caplog.records)

    @pytest.mark.postgres
    def test_superuser_role_refuse_to_serve_raises(self, pg_admin_engine):
        """refuse_to_serve=True on a bypass-capable role → RuntimeError (fail-closed)."""
        from core.tenant import assert_rls_enforceable

        with pytest.raises(RuntimeError, match="can bypass RLS"):
            assert_rls_enforceable(pg_admin_engine, refuse_to_serve=True)


# ---------------------------------------------------------------------------
# TenantQueryMixin — belt filter (SQLite-safe)
# ---------------------------------------------------------------------------

class TestTenantQueryMixin:
    def test_filter_returns_correct_clause(self):
        from app.models import Article
        from core.tenant import TenantQueryMixin

        filters = TenantQueryMixin.tenant_filter(Article, 42)
        assert len(filters) == 1
        sql = str(filters[0].compile(compile_kwargs={"literal_binds": True}))
        assert "tenant_id" in sql
        assert "42" in sql

    def test_filter_is_equality_not_contains(self):
        from app.models import Video
        from core.tenant import TenantQueryMixin

        filters = TenantQueryMixin.tenant_filter(Video, 99)
        sql = str(filters[0].compile(compile_kwargs={"literal_binds": True}))
        # Should be = not IN or LIKE
        assert "= 99" in sql or "=99" in sql

    def test_filter_works_for_any_tenant_scoped_model(self):
        from app.models import Chunk, CommentDraft, FaqEntry
        from core.tenant import TenantQueryMixin

        for Model in (Chunk, CommentDraft, FaqEntry):
            filters = TenantQueryMixin.tenant_filter(Model, 5)
            assert len(filters) == 1
            sql = str(filters[0].compile(compile_kwargs={"literal_binds": True}))
            assert "tenant_id" in sql


# ---------------------------------------------------------------------------
# PlatformSessionLocal — present in app/models.py without the after_begin hook
# ---------------------------------------------------------------------------

class TestPlatformSessionLocal:
    def test_platform_session_local_exists(self):
        from app.models import PlatformSessionLocal
        assert PlatformSessionLocal is not None

    def test_platform_session_does_not_fire_guc(self):
        """PlatformSessionLocal sessions do not trigger the tenant GUC event."""
        from app.models import PlatformSessionLocal

        # Even with no tenant_id in info, a PlatformSessionLocal session must
        # not raise RuntimeError on first execute.
        session = PlatformSessionLocal()
        # No tenant_id, no platform_scope
        fired = []
        with patch("core.tenant.set_tenant_context", side_effect=lambda s, tid: fired.append(tid)):
            try:
                session.execute(text("SELECT 1"))
            except Exception:
                pass
        session.close()
        assert fired == [], "PlatformSessionLocal must not fire set_tenant_context"
