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


def run(limit: int | None = None) -> dict:
    """Archive source videos to GCS.

    Args:
        limit: If set, process at most this many un-archived videos per run.

    Returns:
        ``{"archived": n, "skipped": n, "errored": n, "total": n}``
        where *total* is the number of Video rows examined.
    """
    from adapters.storage import object_size, upload_file  # noqa: PLC0415
    from adapters.yt_dlp import pull_video  # noqa: PLC0415
    from app.models import SessionLocal, Video  # noqa: PLC0415

    bucket = _media_bucket()

    db = SessionLocal()
    try:
        query = db.query(Video).filter(Video.archive_uri.is_(None))
        if limit is not None:
            query = query.limit(limit)
        videos = query.all()
    finally:
        db.close()

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
                _set_archive_uri(video_id, gs_uri)
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
                # local_path is inside tmp; cleaned up automatically on context exit

            _set_archive_uri(video_id, gs_uri)
            logger.info("archive_job: archived %s (%d bytes)", video_id, local_size)
            archived += 1

        except Exception as exc:  # noqa: BLE001
            logger.error("archive_job: error on %s: %s", video_id, exc)
            errored += 1

    return {"archived": archived, "skipped": skipped, "errored": errored, "total": total}


def _set_archive_uri(video_id: str, gs_uri: str) -> None:
    """Write *gs_uri* into ``Video.archive_uri`` for *video_id* and commit."""
    from app.models import SessionLocal, Video  # noqa: PLC0415

    db = SessionLocal()
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
