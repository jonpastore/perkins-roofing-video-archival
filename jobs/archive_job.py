"""Archive job (I/O orchestration — coverage-omitted).

Downloads every source video that lacks an ``archive_uri`` and stores it in the
private media GCS bucket (``{GOOGLE_CLOUD_PROJECT}-media``).

Idempotent + resumable:
- Videos that already have ``archive_uri`` set are skipped.
- If the GCS object already exists but ``archive_uri`` is NULL, the URI is written
  back to the DB row without re-downloading.
- Per-video try/except: one failure never stops the batch.

Usage:
    PYTHONPATH=. .venv/bin/python jobs/archive_job.py [LIMIT]
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile

logger = logging.getLogger(__name__)

_GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")


def _media_bucket() -> str:
    project = _GOOGLE_CLOUD_PROJECT or os.getenv("GOOGLE_CLOUD_PROJECT", "")
    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT env var is required for GCS upload")
    return f"{project}-media"


def _run_for_tenant(db, tenant_id: int, limit: int | None = None) -> dict:
    """Per-tenant archive body. Called by for_each_tenant via run()."""
    from adapters.storage import object_size, upload_file  # noqa: PLC0415
    from adapters.yt_dlp import pull_video  # noqa: PLC0415
    from app.models import Video  # noqa: PLC0415

    bucket = _media_bucket()

    # SHORTEST FIRST. Downloads go through a WireGuard tunnel (~465 KiB/s measured), and the
    # backlog is wildly skewed: of the 15 unarchived on 2026-07-29, twelve were Shorts of
    # 13-80s and three were 20/49/117 minutes — the last ~1.36 GB, roughly 50 minutes on its
    # own. Unordered, one long video at the head of the batch can eat the whole 2h job timeout
    # and leave twelve trivial ones undone.
    #
    # Ordering by duration means a timeout truncates the TAIL, and since the job is idempotent
    # (it only selects archive_uri IS NULL) the next run resumes with the big ones. NULLS LAST
    # so an un-backfilled row never jumps the queue.
    query = (
        db.query(Video)
        .filter(Video.archive_uri.is_(None))
        .order_by(Video.duration.asc().nullslast())
    )
    if limit is not None:
        query = query.limit(limit)
    videos = query.all()

    archived = skipped = errored = 0
    total = len(videos)

    for video in videos:
        video_id = video.id
        key = f"videos/{video_id}.mp4"
        gs_uri = f"gs://{bucket}/{key}"

        try:
            # Idempotency/resume: only trust an existing object if it's non-empty. A crash
            # mid-upload can leave a 0-byte object; treat that as not-archived and re-download.
            if object_size(bucket, key) > 0:
                logger.info("archive_job: object exists, patching row: %s", video_id)
                _set_archive_uri(video_id, gs_uri, tenant_id=tenant_id)
                skipped += 1
                continue

            with tempfile.TemporaryDirectory() as tmp:
                logger.info("archive_job: downloading %s -> %s", video_id, tmp)
                local_path = pull_video(video_id, tmp)
                local_size = os.path.getsize(local_path)

                logger.info("archive_job: uploading %s -> gs://%s/%s", local_path, bucket, key)
                upload_file(local_path, bucket, key, content_type="video/mp4")

                # Integrity: verify the uploaded object matches the local size before we stamp
                # the row — otherwise a truncated upload gets marked archived forever.
                remote_size = object_size(bucket, key)
                if remote_size != local_size:
                    raise RuntimeError(
                        f"upload size mismatch for {video_id}: local={local_size} remote={remote_size}"
                    )

            _set_archive_uri(video_id, gs_uri, tenant_id=tenant_id)
            logger.info("archive_job: archived %s (%d bytes)", video_id, local_size)
            archived += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("archive_job: error on %s: %s", video_id, exc)
            errored += 1

    result = {"archived": archived, "skipped": skipped, "errored": errored, "total": total}
    _record_scan(db, tenant_id, result)
    return result


def _record_scan(db, tenant_id: int, payload: dict) -> None:
    try:
        from core.scan_report import record  # noqa: PLC0415
        record(db, scan_type="youtube_archive", payload=payload, tenant_id=tenant_id)
        db.commit()
    except Exception:
        db.rollback()


def run(limit: int | None = None) -> dict:
    """Iterate active tenants and archive source videos for each."""
    from app.models import SessionLocal  # noqa: PLC0415
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    totals: dict = {"archived": 0, "skipped": 0, "errored": 0, "total": 0}

    def _fn(db, tenant_id: int) -> None:
        r = _run_for_tenant(db, tenant_id, limit=limit)
        for k in totals:
            totals[k] += r.get(k, 0)

    for_each_tenant(SessionLocal, _fn)
    return totals


def _set_archive_uri(video_id: str, gs_uri: str, tenant_id: int | None = None) -> None:
    """Write *gs_uri* into ``Video.archive_uri`` for *video_id* and commit."""
    from app.models import SessionLocal, Video  # noqa: PLC0415

    db = SessionLocal()
    if tenant_id is not None:
        db.info["tenant_id"] = tenant_id
    try:
        video = db.get(Video, video_id)
        if video is not None:
            video.archive_uri = gs_uri
            db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    result = run(limit=_limit)
    print(result)

    # Per-video try/except keeps one bad video from stopping the batch — but on its own it also
    # meant a run where EVERY video failed still exited 0. That is what execution archive-52md7
    # did on 2026-07-28: {'archived': 0, 'skipped': 0, 'errored': 15, 'total': 15} and
    # "Container called exit(0)". Cloud Run reported success, the scheduler would have reported
    # success every night, and archive_uri would have stayed NULL forever — silently blocking
    # STT, because adapters/stt_gcp.py refuses to transcribe a video without it.
    #
    # Fail the run when there was work to do and NOTHING succeeded. A partial failure still
    # exits 0 (one unavailable video must not page anyone), but a total failure is a real
    # outage and Cloud Run should show it as one.
    if result["errored"] and not result["archived"] and not result["skipped"]:
        logging.error(
            "archive_job: %d/%d videos failed and none succeeded — failing the run",
            result["errored"], result["total"],
        )
        sys.exit(1)
