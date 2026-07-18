"""Cloud Run Job / cron target: CompanyCam photo backfill + sync (ahead-of-account scaffold).

Ahead of the account: COMPANYCAM_PAT is not issued yet. When unconfigured this job
logs and exits cleanly (exit_code=0) rather than crashing the scheduler — see
adapters.companycam.configured(). Once a PAT is bootstrapped, this pulls every
project and its photos per-tenant and upserts them into companycam_photos
(core/companycam/mirror.py).

Single-flight: pg_try_advisory_lock key 8274126 (distinct from Knowify's ingest
8274123 / sync 8274124 / token 8274125).

Run:
    python -m jobs.companycam_sync
"""
import logging
import sys
from contextlib import contextmanager

from sqlalchemy import text

import adapters.companycam as companycam
from app.models import SessionLocal
from core.companycam.mirror import upsert_photo

log = logging.getLogger(__name__)

_LOCK_KEY = 8274126  # distinct from knowify ingest (8274123), sync (8274124), token (8274125)
# CompanyCam is a single (Perkins) account today, matching the webhook (api/routes/companycam.py).
_COMPANYCAM_TENANT_ID = 1


@contextmanager
def _single_flight():
    """Yield True if this process holds the sync advisory lock, False to skip.

    Session-scoped: process death auto-releases. No-op on SQLite (always True).
    """
    s = SessionLocal()
    s.info["platform_scope"] = True  # platform-level; no tenant GUC needed
    is_pg = s.bind.dialect.name == "postgresql"
    held = True
    try:
        if is_pg:
            held = bool(
                s.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}).scalar()
            )
        yield held
    finally:
        try:
            if held and is_pg:
                s.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
                s.commit()
        finally:
            s.close()


def _sync_tenant(db, tenant_id: int) -> dict:
    """Pull every project's photos and upsert them for one tenant.

    Per-project fetch errors are isolated so one bad project doesn't abort the rest.
    """
    counts = {"projects": 0, "photos_seen": 0, "photos_written": 0, "errors": 0}
    try:
        projects = companycam.list_projects()
    except Exception as exc:  # noqa: BLE001
        log.error("companycam sync: list_projects tenant=%d error=%s", tenant_id, type(exc).__name__)
        counts["errors"] += 1
        return counts

    for project in projects:
        project_id = str(project["id"])
        counts["projects"] += 1
        try:
            photos = companycam.list_photos(project_id)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "companycam sync: list_photos project=%s tenant=%d error=%s",
                project_id, tenant_id, type(exc).__name__,
            )
            counts["errors"] += 1
            continue

        for photo in photos:
            counts["photos_seen"] += 1
            if upsert_photo(db, photo):
                counts["photos_written"] += 1

    log.info(
        "companycam sync: tenant=%d projects=%d photos_seen=%d photos_written=%d errors=%d",
        tenant_id, counts["projects"], counts["photos_seen"], counts["photos_written"], counts["errors"],
    )
    return counts


def run() -> dict:
    """Run the CompanyCam backfill/sync job.

    Returns dict with exit_code (0=clean, 1=any error). Unconfigured (no PAT yet)
    logs and returns cleanly with exit_code=0 — this must never crash the scheduler.
    """
    logging.basicConfig(level=logging.INFO)

    if not companycam.configured():
        log.info("companycam unconfigured — skipping")
        return {"skipped": "companycam unconfigured", "exit_code": 0}

    with _single_flight() as ok:
        if not ok:
            log.info("companycam sync: already running (advisory lock held) — skip")
            return {"skipped": "companycam sync already running", "exit_code": 0}

        # Scope to tenant 1 (Perkins). A single global PAT fanned out over every tenant would
        # mirror Perkins' photos under other tenants — the webhook hardcodes tenant 1 too. When a
        # 2nd CompanyCam account exists, add a per-tenant PAT lookup and iterate configured tenants.
        db = SessionLocal()
        db.info["tenant_id"] = _COMPANYCAM_TENANT_ID  # RLS GUC stamped on after_begin
        try:
            counts = _sync_tenant(db, _COMPANYCAM_TENANT_ID)
            db.commit()
        finally:
            db.close()

        return {"exit_code": 1 if counts["errors"] else 0, "counts": {_COMPANYCAM_TENANT_ID: counts}}


if __name__ == "__main__":
    result = run()
    sys.exit(result.get("exit_code", 0))
