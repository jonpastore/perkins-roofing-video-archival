"""Postgres fixture for the tenancy test suite.

Tests marked @pytest.mark.postgres require a real PostgreSQL instance and are
skipped when TENANCY_PG_URL is not set AND Docker is unavailable for testcontainers.

Two supported modes (in priority order):
  1. TENANCY_PG_URL env var set  → use that URL directly (CI service container).
  2. Docker available             → spin up a postgres:15 container via testcontainers.
  3. Neither                      → skip with an explicit message.

Tests in this suite MUST NOT silently pass on SQLite — the RLS policies do not
exist on SQLite and false-green results are worse than skips.

CRITICAL (R2 fix H3-arch + fix 5): the schema is built with create_all AND the
RLS policies from infra/migrations/0018_rls_gcip.sql are applied on top, THEN the
denial tests connect as a dedicated NON-SUPERUSER, NON-BYPASSRLS role. Without
all three, denial tests false-green: create_all alone has no policies, and even
with policies a superuser/BYPASSRLS connection bypasses RLS entirely. An exit-gate
fixture (assert_rls_role_hardened) proves the connecting role cannot bypass RLS
before any denial result is trusted.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

# The app-like role the denial tests connect as. Deliberately NOT the container
# superuser: RLS is a no-op for SUPERUSER/BYPASSRLS roles.
_APP_ROLE = "app_rls_test"
_APP_PASSWORD = "app_rls_test_pw"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "postgres: requires a real PostgreSQL instance (TENANCY_PG_URL or Docker)",
    )


@pytest.fixture(scope="session")
def pg_url():
    """Session-scoped: resolve the (admin/superuser) Postgres URL or skip.

    Returns TENANCY_PG_URL if set, None if testcontainers is available (pg_container
    will spin one up), or skips if neither is available.
    """
    import importlib.util

    url = os.environ.get("TENANCY_PG_URL")
    if url:
        return url

    if importlib.util.find_spec("testcontainers") is None:
        pytest.skip(
            "TENANCY_PG_URL not set and testcontainers not installed — "
            "tenancy suite requires real Postgres. "
            "Install: pip install testcontainers[postgresql]"
        )

    return None  # testcontainers fixture handles connection


@pytest.fixture(scope="session")
def pg_container(pg_url):
    """Spin up a Postgres container if TENANCY_PG_URL is not set. Yields the
    ADMIN connection URL (superuser) used for schema build + role creation."""
    if pg_url is not None:
        yield _force_pg8000(pg_url)
        return

    from testcontainers.postgres import PostgresContainer

    # pgvector image: chunks.embedding maps to Vector(3072) on Postgres, which needs
    # the `vector` extension. Stock postgres:15 lacks it; pgvector/pgvector ships it.
    pg = PostgresContainer(
        "pgvector/pgvector:pg15",
        username="tc_admin",
        password="tc_admin_pw",
        dbname="tc_test",
    )
    with pg as pg:
        yield _force_pg8000(pg.get_connection_url())


def _force_pg8000(url: str) -> str:
    """Normalize any Postgres URL to the pg8000 driver — the repo does not install
    psycopg2, and testcontainers/CI URLs often default to postgresql+psycopg2://.

    Uses render_as_string(hide_password=False): plain str(URL) REDACTS the password
    to '***', which would then be re-parsed as the literal password and fail auth.
    """
    u = make_url(url)
    if u.get_backend_name() == "postgresql" and u.get_driver_name() != "pg8000":
        u = u.set(drivername="postgresql+pg8000")
    return u.render_as_string(hide_password=False)


def _app_role_url(admin_url: str) -> str:
    """Derive the connection URL for the non-superuser app role from the admin URL
    (same host/port/db, different credentials)."""
    url = make_url(admin_url)
    return url.set(username=_APP_ROLE, password=_APP_PASSWORD).render_as_string(
        hide_password=False
    )


def _apply_rls_migration(admin_engine) -> None:
    """Apply the RLS-policy DDL to the fixture DB: 0018 (base per-table policies)
    then 0022 (proposals accept-token resolver policy, which DROP/CREATEs the
    proposals policy 0018 made — order matters).

    Reuses the dollar-quote-aware statement splitter from the production migration
    runner so DO $$ ... $$ policy blocks are applied intact. Runs as the admin
    (superuser) connection because ALTER TABLE ... ENABLE RLS + CREATE POLICY are
    owner/superuser operations.
    """
    from scripts.apply_migrations_connector import _statements

    here = os.path.dirname(__file__)
    for fname in ("0018_rls_gcip.sql", "0022_proposals_accept_token_policy.sql"):
        migration_path = os.path.join(here, "..", "..", "infra", "migrations", fname)
        with open(os.path.abspath(migration_path)) as fh:
            sql = fh.read()
        with admin_engine.begin() as conn:
            for stmt in _statements(sql):
                # The identity-section INSERT/CREATE TABLE statements are already
                # created by create_all; IF NOT EXISTS / ON CONFLICT make them no-ops.
                conn.execute(text(stmt))


def _create_app_role(admin_engine) -> None:
    """Create the NON-SUPERUSER, NON-BYPASSRLS app role and grant it DML on all
    tables in public. This is the role the denial tests connect as — the whole
    point of the suite is proving RLS blocks THIS role."""
    with admin_engine.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": _APP_ROLE}
        ).fetchone()
        if not exists:
            # CREATE ROLE is DDL — it does not accept extended-protocol bind params
            # (a :pw param errors with `syntax error at or near "$1"`). The role name
            # and password are fixed test constants (no external input), so inlining
            # the quoted literal is safe here.
            conn.execute(
                text(
                    f"CREATE ROLE {_APP_ROLE} LOGIN PASSWORD '{_APP_PASSWORD}' "
                    "NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"
                )
            )
        # Belt-and-suspenders: force the flags even if the role pre-existed.
        conn.execute(text(f"ALTER ROLE {_APP_ROLE} NOSUPERUSER NOBYPASSRLS"))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {_APP_ROLE}"))
        conn.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "
                f"public TO {_APP_ROLE}"
            )
        )
        conn.execute(
            text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {_APP_ROLE}")
        )


@pytest.fixture(scope="session")
def pg_admin_engine(pg_container):
    """Admin (superuser) engine — builds schema, applies RLS, creates the app role.
    Seeds tenants 1 and 2. Not used directly by denial tests."""
    from app.models import Base

    engine = create_engine(pg_container, future=True, echo=False)
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    _apply_rls_migration(engine)
    _create_app_role(engine)

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
        conn.execute(text(
            "SELECT setval('tenants_id_seq', GREATEST((SELECT MAX(id) FROM tenants), 2), true)"
        ))

    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def pg_engine(pg_admin_engine, pg_container):
    """Session-scoped engine the denial tests use — connects as the NON-SUPERUSER
    app role so RLS is actually enforced. Depends on pg_admin_engine to guarantee
    schema + policies + role exist first."""
    app_engine = create_engine(_app_role_url(pg_container), future=True, echo=False)
    yield app_engine
    app_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def assert_rls_role_hardened(request):
    """Exit-gate (fix 5b): before ANY denial result is trusted, prove the role the
    denial tests connect as is NOT a superuser and does NOT have BYPASSRLS. If it
    does, RLS is silently a no-op and every denial 'pass' is a false green — so we
    fail the whole suite loudly instead.

    Autouse + session-scoped: runs once. Skips cleanly when the suite is skipped
    (no Postgres available) by resolving pg_engine lazily only if the marker is used.
    """
    # Only enforce when a postgres-marked test is actually being collected/run.
    if not any(
        item.get_closest_marker("postgres") for item in request.session.items
    ):
        return
    try:
        engine = request.getfixturevalue("pg_engine")
    except pytest.skip.Exception:
        return

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
        ).fetchone()
    assert row is not None, "could not read pg_roles for the test app role"
    rolsuper, rolbypassrls = bool(row[0]), bool(row[1])
    assert not rolsuper and not rolbypassrls, (
        f"RLS EXIT-GATE FAILED: denial tests connect as a role with "
        f"SUPERUSER={rolsuper} BYPASSRLS={rolbypassrls}. RLS is NOT enforced for "
        f"this role, so every denial 'pass' is a false green. The suite is "
        f"meaningless — fix the fixture role before trusting any result."
    )


@pytest.fixture(scope="session")
def seeded_rows(pg_engine):
    """Seed one row per tenant-scoped table for tenant 1; return IDs for
    cross-tenant checks. Shared across test_rls_denial.py and test_rls_probe.py
    (defined here in conftest so both files can request it). Runs as the
    non-superuser app role with RLS active → GUC set to tenant 1 before INSERTs."""
    from tests.tenancy.test_rls_denial import (
        _seed_article,
        _seed_comment_draft,
        _seed_customer,
        _seed_faq_entry,
        _seed_mini_series,
        _seed_property,
        _seed_proposal,
        _seed_social_post,
        _seed_video,
        _set_guc,
    )

    ids = {}
    with pg_engine.begin() as conn:
        _set_guc(conn, 1)
        ids["video_id"] = _seed_video(conn, 1, "vid-rls-t1")
        ids["article_slug"] = _seed_article(conn, 1, "article-rls-t1")
        ids["mini_series_id"] = _seed_mini_series(conn, 1)
        ids["social_post_id"] = _seed_social_post(conn, 1)
        ids["comment_draft_id"] = _seed_comment_draft(conn, 1)
        ids["faq_entry_id"] = _seed_faq_entry(conn, 1)
        ids["customer_id"] = _seed_customer(conn, 1)
        ids["property_id"] = _seed_property(conn, ids["customer_id"], 1)
        ids["proposal_id"] = _seed_proposal(conn, ids["customer_id"], ids["property_id"], 1)
    return ids


@pytest.fixture(scope="session")
def pg_session_factory(pg_engine):
    """Return a session factory wired to the app-role Postgres engine WITHOUT the
    after_begin RLS event (tests control the GUC explicitly for denial probes)."""
    return sessionmaker(bind=pg_engine, future=True)


@pytest.fixture()
def pg_tenant1_session(pg_session_factory):
    """A session pre-stamped for tenant 1 (used in positive-path tests)."""
    session = pg_session_factory()
    session.info["tenant_id"] = 1
    try:
        yield session
        session.rollback()
    finally:
        session.close()


@pytest.fixture()
def pg_tenant2_session(pg_session_factory):
    """A session pre-stamped for tenant 2 (cross-tenant isolation tests)."""
    session = pg_session_factory()
    session.info["tenant_id"] = 2
    try:
        yield session
        session.rollback()
    finally:
        session.close()


@pytest.fixture(scope="session")
def rls_engine(pg_engine):
    """Engine variant where the after_begin RLS hook IS active.

    Used for tests that verify the full production session path including
    the automatic GUC injection.
    """
    from sqlalchemy.orm import sessionmaker as _sm

    from core.tenant import register_tenant_session_events

    factory = _sm(bind=pg_engine, future=True)
    register_tenant_session_events(factory)
    return factory
