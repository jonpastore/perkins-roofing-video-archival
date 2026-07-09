"""Cloud Run Job: poll YouTube KPIs for archived videos.

For each archived video (archive_uri IS NOT NULL), fetches current view/like/comment
counts from the YouTube Data API and records the newest comment timestamp.
Idempotent — safe to re-run; only updates, never inserts.

Run: python -m jobs.poll_archive_kpis [--limit N]
"""
import sys
from datetime import datetime, timezone

import adapters.youtube_stats as yt_stats
from app.models import Video, init_db


def _run_for_tenant(db, tenant_id: int, limit: int | None = None) -> dict:
    """Per-tenant KPI poll body. Called by for_each_tenant via run()."""
    query = db.query(Video).filter(Video.archive_uri.isnot(None))
    if limit is not None:
        query = query.limit(limit)
    videos = query.all()

    if not videos:
        return {"polled": 0}

    video_ids = [v.id for v in videos]
    stats_map = yt_stats.fetch_stats(video_ids)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for v in videos:
        stats = stats_map.get(v.id)
        if stats is None:
            row = db.get(Video, v.id)
            if row:
                row.kpis_polled_at = now
                db.add(row)
            continue

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


def run(limit: int | None = None) -> dict:
    """Iterate active tenants and poll KPIs for each."""
    from app.models import SessionLocal  # noqa: PLC0415
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    init_db()
    totals: dict = {"polled": 0}

    def _fn(db, tenant_id: int) -> None:
        r = _run_for_tenant(db, tenant_id, limit=limit)
        totals["polled"] += r.get("polled", 0)

    for_each_tenant(SessionLocal, _fn)
    return totals


if __name__ == "__main__":
    _limit = None
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        _limit = int(sys.argv[idx + 1])
    result = run(limit=_limit)
    print(result)
