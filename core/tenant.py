"""Tenant isolation primitives.

TenantMixin        — attach to every new ORM model to get tenant_id + the F4 seam.
set_tenant_context — issues SET LOCAL app.tenant_id in the current transaction.
                     Called by the after_begin event registered in app/models.py.
TenantQueryMixin   — ORM belt filter (complements RLS suspenders).
"""
from __future__ import annotations

import logging

from sqlalchemy import Column, ForeignKey, Integer, text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


class TenantMixin:
    """Mixin that adds tenant_id to a SQLAlchemy model.

    Usage (new tables, F2+):
        class MyModel(Base, TenantMixin):
            __tablename__ = "my_table"
            ...

    Existing tables are backfilled via migration 0013; their model classes
    gain the column declaration below without needing this mixin (the mixin
    is for NEW tables going forward).  Existing models will be updated to
    inherit TenantMixin in a follow-up cleanup so the column is declared in
    one place.
    """
    tenant_id = Column(
        Integer,
        ForeignKey("tenants.id"),
        nullable=False,
        default=1,
        index=False,
    )


def _unstamped_origin() -> str:
    """Best-effort 'file:line in func' of the app code that opened an unstamped
    session, skipping sqlalchemy internals and this module. Used only in the
    non-strict CRITICAL log so an operator can find the caller to migrate."""
    import traceback

    for frame in reversed(traceback.extract_stack()):
        fn = frame.filename
        if "sqlalchemy" in fn or fn.endswith("core/tenant.py"):
            continue
        return f"{fn}:{frame.lineno} in {frame.name}"
    return "unknown"


def set_tenant_context(session: Session, tenant_id: int) -> None:
    """Issue SET LOCAL app.tenant_id for the current transaction.

    Pool-safe: SET LOCAL is transaction-scoped and dies with the transaction,
    so the GUC never leaks to the next connection checkout from the pool.

    Sources ONLY from verified token claims (stamped into session.info by the
    FastAPI dependency before the first query). Never called with a value from
    request headers or body.

    Called by the after_begin event registered in app/models.py. Also callable
    directly in tests or scripts that manage their own sessions.

    Uses set_config(..., is_local => true) rather than `SET LOCAL app.tenant_id =
    :tid`: Postgres SET does not accept extended-protocol bind parameters, so the
    parameterized SET form raises `syntax error at or near "$1"`. set_config() is a
    normal function call that DOES accept a bind param, and the `true` third arg
    makes it transaction-local (identical semantics to SET LOCAL).
    """
    session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


def register_tenant_session_events(session_factory, strict: bool = True) -> None:
    """Wire the after_begin event onto a SessionLocal factory.

    Called once at app startup (from app/models.py) after SessionLocal is
    created.  The event fires immediately after BEGIN for every session that
    comes from this factory, setting the transaction-scoped GUC before the
    first SQL executes.

    Platform-scoped sessions (PlatformSessionLocal) intentionally do NOT
    call this function — they operate on RLS-exempt tables only and must NOT
    set app.tenant_id (platform_admin sessions have tenant_id=None).

    Seam for platform_scope bypass:
        If session.info.get("platform_scope") is True the raise is skipped and
        no GUC is issued.  This seam is reserved for the f4-identity agent's
        PlatformSessionLocal — regular tenant sessions must never set this flag.

    ``strict`` controls what happens for an UNSTAMPED tenant session (no
    tenant_id, no platform_scope):

      strict=True  (default) — raise RuntimeError. Used for explicit test
                    factories and any future factory that must never leak an
                    un-migrated call site.
      strict=False — default to tenant 1 with a CRITICAL log naming the caller.

    The production SessionLocal registers with strict=False (see app/models.py).
    RATIONALE (F4 → pre-tenant-2 transition contract): ~150 bare `SessionLocal()`
    call sites across api/jobs/scripts predate F4 and do not stamp
    session.info["tenant_id"] yet. Raising for them would 500 every un-migrated
    endpoint in the single-tenant world that exists today. Defaulting to tenant 1
    (the only real tenant) preserves current correctness while the CRITICAL log
    flags every site that MUST be converted to get_db_session before tenant #2 is
    provisioned. This is a documented, temporary contract — not a permanent
    fallback. Once every call site is stamped, flip strict back to True.
    """
    from sqlalchemy import event

    @event.listens_for(session_factory, "after_begin")
    def _set_tenant_id(session, transaction, connection):
        """Set transaction-scoped tenant GUC immediately after BEGIN.

        On PostgreSQL: stamps the GUC from session.info["tenant_id"]. If unstamped,
        either raises (strict) or defaults to tenant 1 with a CRITICAL log (see
        ``strict`` above).
        On SQLite: skipped — no GUC support; ORM belt filter (TenantQueryMixin)
        provides dev-time isolation. Existing SQLite-based tests run unmodified.
        """
        if connection.dialect.name != "postgresql":
            return

        if session.info.get("platform_scope"):
            return

        tenant_id = session.info.get("tenant_id")
        if tenant_id is None:
            if strict:
                raise RuntimeError(
                    "tenant_id not set on session.info; populate session.info['tenant_id'] "
                    "from verified token claims before the first query. "
                    "For platform-scoped sessions (no tenant context) set "
                    "session.info['platform_scope'] = True instead."
                )
            # Non-strict (production SessionLocal): default to tenant 1 and log
            # loudly which caller was unstamped, so it can be migrated.
            log.critical(
                "UNSTAMPED tenant session defaulted to tenant 1 (F4 transition "
                "contract). Convert this caller to get_db_session before tenant #2. "
                "Origin: %s",
                _unstamped_origin(),
            )
            tenant_id = 1
        # Issue the GUC on the CONNECTION the event was handed — NOT via
        # session.execute(). Calling session.execute() inside after_begin re-enters
        # the connection-provisioning the event is running within and raises
        # "this session is provisioning a new connection; concurrent operations are
        # not permitted" on real Postgres. connection.execute() is the safe path.
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )


# ── ORM belt (do_orm_execute) — DESCOPED (TRD-F4 §3.3) ───────────────────────
# The TRD proposed a do_orm_execute listener appending a tenant_id filter on every
# ORM SELECT as "belt" to RLS's "suspenders". After implementation review it is
# descoped for F4, deliberately:
#   1. RLS with FORCE ROW LEVEL SECURITY already filters EVERY statement at the DB
#      layer — raw SQL, ORM, and any code path — which strictly dominates an
#      ORM-only belt (the belt cannot catch anything RLS misses, since RLS sees all).
#   2. A correct do_orm_execute + with_loader_criteria implementation must match
#      entities structurally (they don't share a tenant base class); a wrong matcher
#      silently filters nothing (false security) or over-filters and breaks the many
#      existing SQLite tests that query without a stamped tenant. The failure mode of
#      a subtly-wrong belt is worse than its absence.
#   3. The genuine gap the belt was meant to cover — RLS silently off when the app
#      role is SUPERUSER/BYPASSRLS — is addressed directly by assert_rls_enforceable()
#      (startup CRITICAL/refuse-to-serve), which is a real guard, not a duplicate.
# The required tenant_id-on-every-log-line (§5) is implemented separately in
# adapters/gcp_logging.py (TenantLogFilter) and IS in scope.


def assert_rls_enforceable(engine, *, refuse_to_serve: bool = False) -> bool:
    """Verify the app DB role cannot bypass RLS (H2 fail-open guard).

    RLS is silently a no-op if the connecting role is SUPERUSER or has BYPASSRLS.
    Migration 0018 documents `ALTER ROLE <app> NOSUPERUSER NOBYPASSRLS` but leaves
    it commented (superuser-only; Jon applies). Until applied, the hardening is
    absent — this check makes that state LOUD instead of silent.

    Returns True if RLS is enforceable (role is NOSUPERUSER + NOBYPASSRLS), False
    otherwise. On PostgreSQL, a False result logs CRITICAL. If refuse_to_serve is
    True, a False result raises RuntimeError (fail-closed startup). Non-Postgres
    engines (SQLite dev/test) return True — RLS isn't expected there.
    """
    if engine.dialect.name != "postgresql":
        return True

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles "
                "WHERE rolname = current_user"
            )
        ).fetchone()

    if row is None:  # pragma: no cover — current_user is always present in pg_roles
        log.critical(
            "assert_rls_enforceable: could not read pg_roles for current_user; "
            "cannot confirm RLS is enforceable."
        )
        if refuse_to_serve:
            raise RuntimeError("cannot verify RLS enforceability for the app role")
        return False

    rolsuper, rolbypassrls = bool(row[0]), bool(row[1])
    if rolsuper or rolbypassrls:
        log.critical(
            "RLS FAIL-OPEN: app DB role is SUPERUSER=%s BYPASSRLS=%s — row-level "
            "security is NOT enforced. Apply `ALTER ROLE <app> NOSUPERUSER "
            "NOBYPASSRLS` (migration 0018 step 7, superuser-only) before serving "
            "multi-tenant traffic.",
            rolsuper,
            rolbypassrls,
        )
        if refuse_to_serve:
            raise RuntimeError(
                "app DB role can bypass RLS (SUPERUSER/BYPASSRLS); refusing to serve"
            )
        return False

    return True


class TenantQueryMixin:
    """ORM query helper — belt (complements F4's RLS suspenders).

    Usage in service layer:
        rows = session.query(Article).filter(
            *TenantQueryMixin.tenant_filter(Article, tenant_id)
        ).all()

    F4 relies on RLS as the primary guard; this filter stays as defense-in-depth.
    """
    @staticmethod
    def tenant_filter(model_cls, tenant_id: int):
        return (model_cls.tenant_id == tenant_id,)
