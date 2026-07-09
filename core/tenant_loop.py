"""Tenant-loop primitives — F5-a.

for_each_tenant(db_factory, fn) iterates every active tenant and calls
fn(db, tenant_id) with:
  - a fresh DB session whose session.info["tenant_id"] is stamped (the F4
    after_begin event fires immediately after BEGIN and issues SET LOCAL)
  - per-tenant cost counters reset before fn() and flushed after
  - per-tenant exception isolation (one tenant failing never aborts the loop)

Platform-level session (no tenant_id) is used only for the initial
active_tenants() query; each tenant's fn() receives its own session.
"""
from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from core import metering

log = logging.getLogger(__name__)


def active_tenants(db: Session) -> list[int]:
    """Return tenant IDs for all tenants with status='active'.

    Platform-level query; runs without tenant context (no RLS on tenants table).
    The calling session must NOT have tenant_id stamped (use a raw SessionLocal()
    without session.info["tenant_id"] — the F4 after_begin event no-ops on SQLite
    and defaults to tenant 1 on Postgres, which is fine for the tenants table since
    it has no RLS policy).
    """
    rows = db.execute(
        text("SELECT id FROM tenants WHERE status = 'active' ORDER BY id")
    ).fetchall()
    return [r[0] for r in rows]


def _check_soft_caps(tenant_id: int) -> bool:  # noqa: ARG001
    """Return True if the tenant has exceeded any metering soft cap this month.

    Full implementation deferred to the post-F5 metering-caps wave (requires
    BigQuery or a DB counter table for MTD aggregation). This stub always returns
    False (no cap exceeded) so the loop runs all tenants.

    The counters themselves (reset/add/flush) ARE implemented in core/metering.py
    and are emitted per-run — the prerequisite for future cap enforcement is met.

    To enable cap checks: replace this function with a real MTD query against the
    structured logs or a `tenant_usage_monthly` summary table, then compare against
    `core.tenant_settings.load(tenant_id).get("metering_caps", {})`.
    """
    return False


def for_each_tenant(
    db_factory: Callable[[], Session],
    fn: Callable[[Session, int], None],
) -> None:
    """Iterate active tenants; call fn(db, tenant_id) for each.

    Guarantees:
    - fn receives a fresh DB session with session.info["tenant_id"] stamped.
      The F4 after_begin event fires on the first query and issues
      SET LOCAL app.tenant_id (no-op on SQLite in tests).
    - Soft-cap check: if _check_soft_caps(tid) returns True for a tenant,
      that tenant's fn() is skipped and a WARNING is logged.
    - Per-tenant cost counters are reset via core.metering.reset() before fn()
      and flushed via core.metering.flush(emit=True) after fn() (even on error).
    - Exceptions in fn are caught, logged with tenant_id, and do not abort
      the loop for remaining tenants.
    - The tenant's DB session is closed in a finally block regardless of outcome.

    Args:
        db_factory: Callable that returns a new SQLAlchemy Session each call.
                    SessionLocal from app.models is the production value.
        fn:         Per-tenant work function. Must accept (db: Session, tenant_id: int).
                    May commit/rollback internally; for_each_tenant commits after a
                    successful fn() call and rolls back on exception.
    """
    # Use a platform-level session for the tenants query only.
    # We do NOT stamp tenant_id here — the tenants table is RLS-exempt.
    with db_factory() as platform_db:
        tenant_ids = active_tenants(platform_db)

    for tid in tenant_ids:
        # Soft-cap check before opening the tenant session
        if _check_soft_caps(tid):
            log.warning(
                "for_each_tenant: tenant %d skipped — metering cap exceeded for this cycle",
                tid,
                extra={"tenant_id": tid},
            )
            continue

        db = db_factory()
        # Stamp tenant_id so the F4 after_begin event issues SET LOCAL on Postgres.
        # On SQLite (dev/test) the event is a no-op and tests run without stamping.
        db.info["tenant_id"] = tid
        try:
            metering.reset(tenant_id=tid)
            fn(db, tid)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            log.error(
                "for_each_tenant: tenant %d failed: %s",
                tid,
                exc,
                extra={"tenant_id": tid},
            )
        finally:
            metering.flush(emit=True)
            db.close()
