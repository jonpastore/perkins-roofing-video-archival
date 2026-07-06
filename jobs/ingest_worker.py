"""Cloud Run Job / cron target: run the resumable staged ingest over videos that still
need work. Transcript = on-disk captions -> cloud STT fallback (GCP Speech-to-Text). Near-silent
Shorts are VAD-skipped inside ingest_video (core.vad) — the skip is persisted so they're never
re-transcribed.

Triggering: Cloud Scheduler fires this job every minute (infra: run-ingest). Overlap is prevented
by a Postgres session advisory lock held for the whole run — if a prior execution is still
working, a new one grabs no lock and exits immediately. On sqlite (dev) there is no advisory lock.

Selection: only videos whose transcript/graph/embed stages are not all 'done' at the current
PIPELINE_VERSION are picked up, so a per-minute cron makes forward progress instead of
re-scanning the whole catalog. Fully-done videos drop out until a pipeline-version bump.
Bounded per run (INGEST_CRON_LIMIT, default 25) so an execution finishes inside the job timeout.

Run: .venv/bin/python -m jobs.ingest_worker [limit]   (limit omitted -> INGEST_CRON_LIMIT)
"""
import os
import sys
from contextlib import contextmanager

from sqlalchemy import func, text

from app import ingest
from app.config import settings
from app.models import IngestionRun, SessionLocal, Video

STAGES = ("transcript", "graph", "embed")
_LOCK_KEY = 8274123  # app-wide constant id for the ingest single-flight advisory lock


@contextmanager
def _single_flight():
    """Yield True if this process holds the ingest advisory lock (should run), False if another
    execution already holds it (skip). Session-scoped: if the process dies the connection drops
    and the lock auto-releases. No-op lock on sqlite (dev) — always yields True."""
    s = SessionLocal()
    is_pg = s.bind.dialect.name == "postgresql"
    held = True
    try:
        if is_pg:
            held = bool(s.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}).scalar())
        yield held
    finally:
        try:
            if held and is_pg:
                s.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
                s.commit()
        finally:
            s.close()


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
        .filter(~Video.id.in_(done), ~Video.id.in_(giveup))
        .order_by(Video.id)
    )
    if limit:
        q = q.limit(limit)
    return [row[0] for row in q.all()]


def run(limit=None):
    """Drain up to *limit* pending videos, single-flight. limit=None -> INGEST_CRON_LIMIT (25)."""
    if limit is None:
        limit = int(os.getenv("INGEST_CRON_LIMIT", "25"))

    with _single_flight() as ok:
        if not ok:
            return {"skipped": "ingest already running"}

        s = SessionLocal()
        try:
            vids = _pending_video_ids(s, limit)
        finally:
            s.close()

        ingested, errored = 0, 0
        for vid in vids:
            try:
                ingest.ingest_video(vid)  # resumable; VAD-skips + empty clips complete terminally
                ingested += 1
            except Exception as e:  # noqa: BLE001 — one bad video must not stop the batch
                errored += 1
                print(f"[error] {vid}: {str(e)[:160]}")
        return {"ingested": ingested, "errored": errored, "total": len(vids)}


if __name__ == "__main__":
    _limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    print(run(limit=_limit))
