"""Test isolation: bind app.models to a fresh temp SQLite DB before any test imports it.

Without this, the first test to import app.models (e.g. via api.app) binds the module-global
engine to the real app/dev.db (an old POC DB missing newer columns like archive_uri), which
then leaks into every other test. Setting DB_URL here — before collection imports anything —
guarantees a clean, current-schema database for the whole suite.
"""
import os
import tempfile

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_URL"] = f"sqlite:///{_tmp.name}"

# Hermetic google.auth: strip any ambient GOOGLE_APPLICATION_CREDENTIALS (e.g. the
# perkins-deploy-sa key exported in ~/.bashrc) so tests never pick up a real credential.
# With a live SA key present, google.auth succeeds where knowify/grpc tests expect no
# creds (or a mock), and they fail non-deterministically depending on the dev's shell.
os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)


import pytest  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "postgres: requires a real PostgreSQL instance (TENANCY_PG_URL or Docker)",
    )
    # Audit writes open a SECOND connection on purpose, so the row survives the request's
    # rollback. Postgres (prod) handles that; SQLite is single-writer and every request
    # instead waits out a "database is locked" timeout — it turned a ~6min suite into a
    # >30min one. The audit machinery has its own tests (tests/core/test_audit*.py,
    # tests/api/test_audit_mw.py), which opt back in explicitly.
    os.environ.setdefault("AUDIT_ENABLED", "0")


# ---------------------------------------------------------------------------
# Postgres fixtures (shared) — needed by tests outside tests/tenancy/ such as
# test_knowify_promote.py. Defined here (root conftest, always loaded) so
# pytest_plugins is NOT needed, avoiding double-registration when
# tests/tenancy/ is also in the collection path (pytest auto-discovers
# tests/tenancy/conftest.py and re-registering via pytest_plugins crashes).
# ---------------------------------------------------------------------------

def _force_pg8000(url: str) -> str:
    from sqlalchemy.engine import make_url
    u = make_url(url)
    if u.get_backend_name() == "postgresql" and u.get_driver_name() != "pg8000":
        u = u.set(drivername="postgresql+pg8000")
    return u.render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def _root_pg_url():
    import importlib.util
    url = os.environ.get("TENANCY_PG_URL")
    if url:
        return url
    if importlib.util.find_spec("testcontainers") is None:
        pytest.skip("TENANCY_PG_URL not set and testcontainers not installed")
    return None


@pytest.fixture(scope="session")
def _root_pg_container(_root_pg_url):
    if _root_pg_url is not None:
        yield _force_pg8000(_root_pg_url)
        return
    from testcontainers.postgres import PostgresContainer
    pg = PostgresContainer(
        "pgvector/pgvector:pg15",
        username="tc_admin",
        password="tc_admin_pw",
        dbname="tc_test",
    )
    with pg as pg:
        yield _force_pg8000(pg.get_connection_url())


@pytest.fixture(scope="session")
def _root_pg_admin_engine(_root_pg_container):
    from sqlalchemy import create_engine, text

    from app.models import Base
    from scripts.apply_migrations_connector import _statements

    engine = create_engine(_root_pg_container, future=True, echo=False)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)

    here = os.path.dirname(__file__)
    for fname in (
        "0018_rls_gcip.sql",
        "0022_proposals_accept_token_policy.sql",
        "0032_knowify_mirror.sql",
    ):
        path = os.path.join(here, "..", "infra", "migrations", fname)
        with open(os.path.abspath(path)) as fh:
            sql = fh.read()
        with engine.begin() as conn:
            for stmt in _statements(sql):
                conn.execute(text(stmt))

    _APP_ROLE = "app_rls_test"
    _APP_PASSWORD = "app_rls_test_pw"
    with engine.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": _APP_ROLE}
        ).fetchone()
        if not exists:
            conn.execute(text(
                f"CREATE ROLE {_APP_ROLE} LOGIN PASSWORD '{_APP_PASSWORD}' "
                "NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"
            ))
        conn.execute(text(f"ALTER ROLE {_APP_ROLE} NOSUPERUSER NOBYPASSRLS"))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {_APP_ROLE}"))
        conn.execute(text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {_APP_ROLE}"
        ))
        conn.execute(text(
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {_APP_ROLE}"
        ))

    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO tenants (id, name, slug, status, settings, created_at) "
            "VALUES (1, 'Perkins Roofing', 'perkins', 'active', '{}', NOW()) "
            "ON CONFLICT (id) DO NOTHING"
        ))
        conn.execute(text(
            "INSERT INTO tenants (id, name, slug, status, settings, created_at) "
            "VALUES (2, 'Acme Corp', 'acme', 'active', '{}', NOW()) "
            "ON CONFLICT (id) DO NOTHING"
        ))

    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def _root_pg_engine(_root_pg_admin_engine, _root_pg_container):
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    _APP_ROLE = "app_rls_test"
    _APP_PASSWORD = "app_rls_test_pw"
    url = make_url(_root_pg_container)
    app_url = url.set(username=_APP_ROLE, password=_APP_PASSWORD).render_as_string(hide_password=False)
    engine = create_engine(app_url, future=True, echo=False)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def rls_engine(_root_pg_engine):
    """rls_engine for tests outside tests/tenancy/ (e.g. test_knowify_promote)."""
    from sqlalchemy.orm import sessionmaker

    from core.tenant import register_tenant_session_events
    factory = sessionmaker(bind=_root_pg_engine, future=True)
    register_tenant_session_events(factory)
    return factory


@pytest.fixture(autouse=True)
def _reset_auth_verifier():
    """Reset the injected auth verifier after every test so a file that sets it can't leak
    into another (a hidden ordering dependency the audit flagged)."""
    yield
    try:
        from api.auth import set_verifier
        set_verifier(None)
    except Exception:
        pass
