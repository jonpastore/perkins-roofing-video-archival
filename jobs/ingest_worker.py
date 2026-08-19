"""Cloud Run Job / cron target: run the resumable staged ingest over videos that still
need work. Transcript = on-disk captions -> cloud STT fallback (GCP Speech-to-Text). Near-silent
Shorts are VAD-skipped inside ingest_video (core.vad) — the skip is persisted so they're never
re-transcribed.

Triggering: Cloud Scheduler `run-ingest` fires hourly 9:00–18:00 ET (`0 9-18 * * *`
America/New_York). Overlap is prevented by a Postgres session advisory lock held for the
whole run — if a prior execution is still working, a new one grabs no lock and exits
immediately. On sqlite (dev) there is no advisory lock. A run typically takes ~50 minutes.

Selection: only videos whose transcript/graph/embed stages are not all 'done' at the current
PIPELINE_VERSION are picked up, so a per-minute cron makes forward progress instead of
re-scanning the whole catalog. Fully-done videos drop out until a pipeline-version bump.
Bounded per run (INGEST_CRON_LIMIT, default 25) so an execution finishes inside the job timeout.

Run: .venv/bin/python -m jobs.ingest_worker [limit]   (limit omitted -> INGEST_CRON_LIMIT)
"""
import os
import sys

from sqlalchemy import func

from app import ingest
from app.config import settings
from app.models import IngestionRun, SessionLocal, Video
from core.single_flight import single_flight

STAGES = ("transcript", "graph", "embed")
_LOCK_KEY = 8274123  # app-wide constant id for the ingest single-flight advisory lock


def _single_flight():
    """Advisory-lock guard — see core.single_flight for why it commits on acquire."""
    return single_flight(SessionLocal, _LOCK_KEY)


def _pending_video_ids(s, limit=None):
    """Video ids that are NOT fully done at the current pipeline version (missing a stage,
    errored, or stamped with an older pipeline_version). Oldest-id-first for stable rotation.

    Videos whose transcript stage has errored MAX_TRANSCRIPT_ATTEMPTS times are given up on and
    excluded — otherwise a permanently-failing video (e.g. a defective archive with no audio
    track) would be re-downloaded and re-attempted on every cron run forever. A manual
    /status/retry (which sets status back to 'pending') clears the give-up state."""
    done = (
        s.query(IngestionRun.video_id)
        .filter(
            IngestionRun.status == "done",
            IngestionRun.stage.in_(STAGES),
            IngestionRun.pipeline_version == settings.PIPELINE_VERSION,
        )
        .group_by(IngestionRun.video_id)
        .having(func.count(func.distinct(IngestionRun.stage)) == len(STAGES))
    )
    max_attempts = int(os.getenv("MAX_TRANSCRIPT_ATTEMPTS", "5"))
    giveup = (
        s.query(IngestionRun.video_id)
        .filter(
            IngestionRun.stage == "transcript",
            IngestionRun.status == "error",
            IngestionRun.attempts >= max_attempts,
        )
    )
    q = (
        s.query(Video.id)
        .filter(
            ~Video.id.in_(done),
            ~Video.id.in_(giveup),
            Video.parent_video_id.is_(None),
        )
        .order_by(Video.id)
    )
    if limit:
        q = q.limit(limit)
    return [row[0] for row in q.all()]


def _ingest_enabled(db, tenant_id: int) -> bool:
    """Honour kb.ingest_enabled from tenants.settings.

    The setting has existed since provisioning (core/provision.py) and the KB config screen
    promises the operator "No new videos will be fetched until re-enabled" — but NOTHING read it,
    so unticking the box did nothing and the cron kept ingesting. A UI assertion over an empty
    gap is this repo's signature defect; here the writer existed and the reader did not.

    Fails OPEN on any error, and defaults True: ingest is the pipeline everything downstream
    depends on, so a malformed settings blob must not silently halt the catalogue. The operator's
    explicit False is the only thing that stops it.
    """
    from sqlalchemy import text  # noqa: PLC0415

    from core.tenant_settings import TenantSettings  # noqa: PLC0415

    try:
        row = db.execute(
            text("SELECT settings FROM tenants WHERE id = :tid"), {"tid": tenant_id}
        ).fetchone()
        if row is None:
            return True
        raw = row.settings if hasattr(row, "settings") else row[0]
        if not isinstance(raw, dict):
            return True
        ts = TenantSettings.load(raw)
        if ts.kb is None:
            return True
        return bool(ts.kb.ingest_enabled)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] ingest_enabled lookup failed for tenant {tenant_id}, assuming enabled: {exc}")
        return True


def _run_for_tenant(db, tenant_id: int, limit=None) -> dict:
    """Per-tenant ingest body. Called by for_each_tenant via run()."""
    if not _ingest_enabled(db, tenant_id):
        print(f"[skip] tenant {tenant_id}: kb.ingest_enabled is false")
        return {"ingested": 0, "errored": 0, "total": 0, "skipped": "ingest_enabled=false"}
    vids = _pending_video_ids(db, limit)
    ingested, errored = 0, 0
    for vid in vids:
        try:
            ingest.ingest_video(vid, tenant_id=tenant_id)
            ingested += 1
        except Exception as e:  # noqa: BLE001 — one bad video must not stop the batch
            errored += 1
            print(f"[error] {vid}: {str(e)[:160]}")
    return {"ingested": ingested, "errored": errored, "total": len(vids)}


def run(limit=None):
    """Iterate active tenants and drain pending ingest for each, single-flight."""
    if limit is None:
        limit = int(os.getenv("INGEST_CRON_LIMIT", "25"))

    with _single_flight() as ok:
        if not ok:
            return {"skipped": "ingest already running"}

        from core.tenant_loop import for_each_tenant  # noqa: PLC0415

        totals: dict = {"ingested": 0, "errored": 0, "total": 0}

        def _fn(db, tenant_id: int) -> None:
            r = _run_for_tenant(db, tenant_id, limit=limit)
            totals["ingested"] += r.get("ingested", 0)
            totals["errored"] += r.get("errored", 0)
            totals["total"] += r.get("total", 0)

        for_each_tenant(SessionLocal, _fn)
        return totals


if __name__ == "__main__":
    _limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    print(run(limit=_limit))
