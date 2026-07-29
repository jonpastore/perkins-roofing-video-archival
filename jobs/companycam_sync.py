"""Cloud Run Job / cron target: CompanyCam photo + video backfill and sync.

Pulls every project and BOTH its photos and its videos per-tenant, upserting into
companycam_photos / companycam_videos (core/companycam/mirror.py). Videos are a separate
v2 resource with a different payload shape — not photos with a type flag.

The application key is live (2026-07-28). When unconfigured this job logs and exits cleanly
(exit_code=0) rather than crashing the scheduler — see adapters.companycam.configured().

⚠️ Mirrored media carries CompanyCam's ``internal`` flag. Internal media must never reach a
proposal or a public project page; every consumer filters on it.

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
from core.companycam.mirror import upsert_photo, upsert_video

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
    """Pull every project's photos AND videos and upsert them for one tenant.

    Per-project, per-resource fetch errors are isolated so one bad project — or one failing
    endpoint — doesn't abort the rest.
    """
    counts = {"projects": 0, "photos_seen": 0, "photos_written": 0,
              "videos_seen": 0, "videos_written": 0, "errors": 0}
    try:
        projects = companycam.list_projects()
    except Exception as exc:  # noqa: BLE001
        log.error("companycam sync: list_projects tenant=%d error=%s", tenant_id, type(exc).__name__)
        counts["errors"] += 1
        return counts

    # Photos and videos are SEPARATE v2 resources — a project with photos may still have video
    # (measured 2026-07-29: 234 videos across 20 of 25 sampled projects). They are fetched in
    # independent try blocks so a video-endpoint failure still mirrors that project's photos.
    for project in projects:
        project_id = str(project["id"])
        counts["projects"] += 1
        for kind, fetch, seen_key, written_key, upsert in (
            ("list_photos", companycam.list_photos, "photos_seen", "photos_written", upsert_photo),
            ("list_videos", companycam.list_videos, "videos_seen", "videos_written", upsert_video),
        ):
            try:
                items = fetch(project_id)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "companycam sync: %s project=%s tenant=%d error=%s",
                    kind, project_id, tenant_id, type(exc).__name__,
                )
                counts["errors"] += 1
                continue

            for item in items:
                counts[seen_key] += 1
                if upsert(db, item):
                    counts[written_key] += 1

    log.info(
        "companycam sync: tenant=%d projects=%d photos_seen=%d photos_written=%d "
        "videos_seen=%d videos_written=%d errors=%d",
        tenant_id, counts["projects"], counts["photos_seen"], counts["photos_written"],
        counts["videos_seen"], counts["videos_written"], counts["errors"],
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
