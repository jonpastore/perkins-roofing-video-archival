"""Cloud Run Job: poll YouTube KPIs for archived videos.

For each archived video (archive_uri IS NOT NULL), fetches current view/like/comment
counts from the YouTube Data API and records the newest comment timestamp.
Idempotent — safe to re-run; only updates, never inserts.

Run: python -m jobs.poll_archive_kpis [--limit N]
"""
import sys
from datetime import datetime, timezone

import adapters.youtube_stats as yt_stats
from app.models import SessionLocal, Video, init_db


def run(limit: int | None = None) -> dict:
    """Fetch KPIs for archived videos and update DB rows.

    Args:
        limit: cap on how many videos to process (None = all).

    Returns:
        {"polled": int}
    """
    init_db()

    with SessionLocal() as db:
        query = db.query(Video).filter(Video.archive_uri.isnot(None))
        if limit is not None:
            query = query.limit(limit)
        videos = query.all()

    if not videos:
        return {"polled": 0}

    video_ids = [v.id for v in videos]

    # Batch-fetch statistics (handles chunking internally)
    stats_map = yt_stats.fetch_stats(video_ids)

    now = datetime.now(timezone.utc).replace(tzinfo=None)  # store as naive UTC

    with SessionLocal() as db:
        for v in videos:
            stats = stats_map.get(v.id)
            if stats is None:
                # Video deleted or private — skip KPI update but still stamp polled_at
                row = db.get(Video, v.id)
                if row:
                    row.kpis_polled_at = now
                    db.add(row)
                continue

            # Fetch latest comment timestamp (may be None if comments disabled)
            latest = yt_stats.latest_comment_at(v.id)
            last_comment_dt: datetime | None = None
            if latest:
                try:
                    last_comment_dt = datetime.fromisoformat(
                        latest.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except ValueError:
                    last_comment_dt = None

            row = db.get(Video, v.id)
            if row:
                row.views = stats["views"]
                row.likes = stats["likes"]
                row.comment_count = stats["comments"]
                if last_comment_dt is not None:
                    row.last_comment_at = last_comment_dt
                row.kpis_polled_at = now
                db.add(row)

        db.commit()

    return {"polled": len(videos)}


if __name__ == "__main__":
    _limit = None
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        _limit = int(sys.argv[idx + 1])
    result = run(limit=_limit)
    print(result)
