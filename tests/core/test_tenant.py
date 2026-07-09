"""Coverage tests for core/tenant.py — TenantQueryMixin and SQLite bypass."""
from unittest.mock import MagicMock

from core.tenant import TenantQueryMixin, set_tenant_context


def test_tenant_query_mixin_returns_filter_clause():
    from app.models import Article
    filters = TenantQueryMixin.tenant_filter(Article, 42)
    assert len(filters) == 1


def test_tenant_query_mixin_filter_is_tuple():
    from app.models import Article
    result = TenantQueryMixin.tenant_filter(Article, 1)
    assert isinstance(result, tuple)


def test_set_tenant_context_calls_execute():
    mock_session = MagicMock()
    set_tenant_context(mock_session, 99)
    mock_session.execute.assert_called_once()
    # Verify the tenant_id was passed as string
    call_params = mock_session.execute.call_args[0][1]
    assert call_params["tid"] == "99"


def test_after_begin_skips_non_postgresql():
    """The after_begin listener must be a no-op on SQLite (the conftest DB)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.tenant import register_tenant_session_events

    engine = create_engine("sqlite:///:memory:")
    Factory = sessionmaker(bind=engine)
    register_tenant_session_events(Factory)

    # Opening a session and starting a transaction must NOT raise on SQLite
    # even without session.info['tenant_id'] set.
    session = Factory()
    try:
        session.execute(__import__("sqlalchemy").text("SELECT 1"))
    finally:
        session.close()


def _get_after_begin_fn():
    """Extract the registered _set_tenant_id closure from a fresh factory."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.tenant import register_tenant_session_events

    engine = create_engine("sqlite:///:memory:")
    Factory = sessionmaker(bind=engine)
    register_tenant_session_events(Factory)
    sess = Factory()
    fn = list(sess.dispatch.after_begin.parent_listeners)[0]
    sess.close()
    return fn


def _pg_conn():
    conn = MagicMock()
    conn.dialect.name = "postgresql"
    return conn


def test_after_begin_platform_scope_bypasses_check():
    """platform_scope=True must skip the RuntimeError even on PostgreSQL."""
    fn = _get_after_begin_fn()
    mock_session = MagicMock()
    mock_session.info = {"platform_scope": True}
    fn(mock_session, MagicMock(), _pg_conn())
    mock_session.execute.assert_not_called()


def test_after_begin_raises_without_tenant_id_on_postgresql():
    """RuntimeError must fire on PostgreSQL when tenant_id is missing."""
    import pytest
    fn = _get_after_begin_fn()
    mock_session = MagicMock()
    mock_session.info = {}
    with pytest.raises(RuntimeError, match="tenant_id not set"):
        fn(mock_session, MagicMock(), _pg_conn())


def test_after_begin_sets_guc_when_tenant_id_present():
    """The GUC must be issued via connection.execute (not session.execute) when
    dialect=postgresql and tenant_id is set. connection.execute is required: calling
    session.execute() inside after_begin re-enters the transaction and raises on real PG."""
    fn = _get_after_begin_fn()
    mock_session = MagicMock()
    mock_session.info = {"tenant_id": 7}
    conn = _pg_conn()
    fn(mock_session, MagicMock(), conn)
    conn.execute.assert_called_once()
    # tenant_id passed as the set_config bind param
    call_params = conn.execute.call_args[0][1]
    assert call_params["tid"] == "7"
