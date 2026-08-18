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

import adapters.companycam as companycam
from app.models import SessionLocal
from core.companycam.mirror import (
    mark_media_synced,
    set_publish_tags,
    upsert_photo,
    upsert_project,
    upsert_video,
)
from core.single_flight import single_flight

log = logging.getLogger(__name__)

_LOCK_KEY = 8274126  # distinct from knowify ingest (8274123), sync (8274124), token (8274125)
# CompanyCam is a single (Perkins) account today, matching the webhook (api/routes/companycam.py).
_COMPANYCAM_TENANT_ID = 1


def _single_flight():
    """Advisory-lock guard — see core.single_flight for why it commits on acquire."""
    return single_flight(SessionLocal, _LOCK_KEY)


def _sync_publish_tags(db, counts: dict) -> None:
    """Account-wide publish-tag pass. Runs EVERY time, gated by nothing.

    Deliberately separate from the per-project crawl above. That crawl is incremental — it
    skips any project whose CompanyCam `updated_at` has not moved — and a finished roof's
    timestamp never moves again. A tag pass gated by it could therefore never reach the
    completed jobs the portfolio is built from (they were all synced in July), and a photo
    tagged today would never appear in a gallery. Both failures would be silent: green job,
    empty gallery.

    Cost is two paginated account-wide fetches. Measured 2026-08-12: 42 tagged photos and 10
    tagged videos across the whole account, so ~4 requests — versus ~7,400 for a per-project
    fan-out that still could not do the job.

    Fails CLOSED: an unrecognised tag id makes CompanyCam return the UNFILTERED list (verified
    — `tag_ids[]=1`, `=999999999` and `=abc` each return everything), which would mark every
    photo on the account publishable, tear-off frames and burned-in GPS included. So the ids
    are validated against the account first and nothing is written unless both are real.
    """
    photo_tag = companycam.projects_tag_id()
    video_tag = companycam.projects_video_tag_id()
    try:
        known = companycam.known_tag_ids()
    except Exception as exc:  # noqa: BLE001
        log.error("companycam tags: cannot list account tags, skipping the tag pass "
                  "error=%s: %s", type(exc).__name__, str(exc)[:300])
        counts["errors"] += 1
        return

    missing = [t for t in (photo_tag, video_tag) if t not in known]
    if missing:
        log.error(
            "companycam tags: configured tag id(s) %s are not on the account — refusing to "
            "write tags, because an unknown id returns UNFILTERED media and would publish "
            "every photo. Set COMPANYCAM_PROJECTS_TAG_ID / COMPANYCAM_PROJECTS_VIDEO_TAG_ID "
            "in Admin Config -> Platform Settings to a current tag id.", missing)
        counts["errors"] += 1
        return

    for kind, fetch, tag_id, id_key, key, upsert in (
        ("photo", companycam.list_tagged_photos, photo_tag, "companycam_photo_id",
         "photos", upsert_photo),
        ("video", companycam.list_tagged_videos, video_tag, "companycam_video_id",
         "videos", upsert_video),
    ):
        try:
            items = fetch([tag_id])
        except Exception as exc:  # noqa: BLE001
            log.error("companycam tags: %s fetch failed error=%s: %s",
                      kind, type(exc).__name__, str(exc)[:300])
            counts["errors"] += 1
            continue
        # Upsert first. The incremental project crawl never sees a photo tagged on a
        # finished roof (project updated_at does not move), so a stamp-only pass left
        # 7 of 42 live Projects photos unmirrored on 2026-08-18 and stamped 0 tags.
        tagged_ids: set[str] = set()
        for item in items:
            tagged_ids.add(str(item[id_key]))
            try:
                upsert(db, item)
            except Exception as exc:  # noqa: BLE001
                log.error("companycam tags: %s upsert id=%s error=%s: %s",
                          kind, item.get(id_key), type(exc).__name__, str(exc)[:200])
                counts["errors"] += 1
        db.commit()
        result = set_publish_tags(db, kind, tagged_ids, tag_id)
        counts[f"{key}_tagged"] = result["tagged"]
        counts[f"{key}_untagged"] = result["cleared"]
        db.commit()
        log.info("companycam tags: kind=%s fetched=%d tagged=%d cleared=%d",
                 kind, len(tagged_ids), result["tagged"], result["cleared"])


def _sync_tenant(db, tenant_id: int) -> dict:
    """Pull every project's photos AND videos and upsert them for one tenant.

    Per-project, per-resource fetch errors are isolated so one bad project — or one failing
    endpoint — doesn't abort the rest.
    """
    counts = {"projects": 0, "projects_skipped": 0, "photos_seen": 0, "photos_written": 0,
              "videos_seen": 0, "videos_written": 0, "photos_tagged": 0, "videos_tagged": 0,
              "photos_untagged": 0, "videos_untagged": 0, "errors": 0}
    try:
        projects = companycam.list_projects()
    except Exception as exc:  # noqa: BLE001
        log.error("companycam sync: list_projects tenant=%d error=%s", tenant_id, type(exc).__name__)
        counts["errors"] += 1
        return counts

    # Photos and videos are SEPARATE v2 resources — a project with photos may still have video
    # (measured 2026-07-29: 420 videos across 38 projects). They are fetched in independent try
    # blocks so a video-endpoint failure still mirrors that project's photos.
    #
    # INCREMENTAL: the account holds 3,684 projects, so pulling both endpoints for all of them
    # is ~7,400 paginated requests. upsert_project compares CompanyCam's updated_at against
    # what we stored and only returns needs_media when it moved (or we have never pulled it),
    # which makes a quiet night one project listing instead of a full crawl.
    for project in projects:
        project_id = str(project["id"])
        counts["projects"] += 1
        row, needs_media = upsert_project(db, project)
        # Commit BEFORE any network call. Otherwise the transaction opened by upsert_project
        # stays open — and idle — for the whole media fetch, which is what pins locks and the
        # vacuum horizon behind slow HTTP. (Prod runs with
        # idle_in_transaction_session_timeout=5min for exactly this class of bug, so holding one
        # across a large project's pagination would also get this session killed.)
        db.commit()
        if not needs_media:
            counts["projects_skipped"] += 1
            continue

        ok = True
        for kind, fetch, seen_key, written_key, upsert in (
            ("list_photos", companycam.list_photos, "photos_seen", "photos_written", upsert_photo),
            ("list_videos", companycam.list_videos, "videos_seen", "videos_written", upsert_video),
        ):
            try:
                items = fetch(project_id)
            except Exception as exc:  # noqa: BLE001
                # The MESSAGE, not just the class: "error=RuntimeError" cost a diagnosis
                # round on 2026-07-29 when the real cause was a 404 on the sub-resource.
                log.error(
                    "companycam sync: %s project=%s tenant=%d error=%s: %s",
                    kind, project_id, tenant_id, type(exc).__name__, str(exc)[:300],
                )
                counts["errors"] += 1
                ok = False
                continue

            for item in items:
                counts[seen_key] += 1
                if upsert(db, item):
                    counts[written_key] += 1

        # Only stamp a project complete when BOTH endpoints succeeded, so a partial pull is
        # retried next run instead of being remembered as done.
        if ok:
            mark_media_synced(db, row)
        # Commit per project: a 3,684-project backfill must not lose everything to one late
        # failure, and the next run resumes from what landed.
        db.commit()

    # AFTER the crawl, so media mirrored in this same run gets tagged in this same run.
    _sync_publish_tags(db, counts)

    log.info(
        "companycam sync: tenant=%d projects=%d skipped_unchanged=%d photos_seen=%d "
        "photos_written=%d videos_seen=%d videos_written=%d photos_tagged=%d "
        "photos_untagged=%d videos_tagged=%d videos_untagged=%d errors=%d",
        tenant_id, counts["projects"], counts["projects_skipped"], counts["photos_seen"],
        counts["photos_written"], counts["videos_seen"], counts["videos_written"],
        counts["photos_tagged"], counts["photos_untagged"], counts["videos_tagged"],
        counts["videos_untagged"], counts["errors"],
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
