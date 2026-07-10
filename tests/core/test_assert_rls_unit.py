"""Unit coverage for assert_rls_enforceable's Postgres branch WITHOUT a real DB.

The PG branch (core/tenant.py) was previously exercised only by
@pytest.mark.postgres testcontainer tests, which CI skips (no Docker) — so the
100% core gate could never pass in CI. These mock-engine tests cover the branch
in any environment. See memory: c1 CI coverage gap.
"""
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from core.tenant import assert_rls_enforceable


def _pg_engine(rolsuper, rolbypassrls, *, row_none=False):
    """A fake SQLAlchemy engine reporting dialect 'postgresql' whose connection
    returns one pg_roles row (rolsuper, rolbypassrls)."""
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    conn = MagicMock()
    result = MagicMock()
    result.fetchone.return_value = None if row_none else (rolsuper, rolbypassrls)
    conn.execute.return_value = result

    @contextmanager
    def _connect():
        yield conn

    engine.connect.side_effect = _connect
    return engine


def test_pg_hardened_role_returns_true():
    assert assert_rls_enforceable(_pg_engine(False, False)) is True


def test_pg_superuser_logs_and_returns_false():
    assert assert_rls_enforceable(_pg_engine(True, False)) is False


def test_pg_bypassrls_returns_false():
    assert assert_rls_enforceable(_pg_engine(False, True)) is False


def test_pg_superuser_refuse_to_serve_raises():
    with pytest.raises(RuntimeError, match="can bypass RLS"):
        assert_rls_enforceable(_pg_engine(True, False), refuse_to_serve=True)
