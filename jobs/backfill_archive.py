"""Cloud Run Job: backfill missing Video rows from the YouTube channel.

Enumerates the Perkins channel, finds video IDs absent from the DB,
inserts minimal Video rows (id/title/duration/upload_date/url), and stamps
last_pulled_at on every row touched.

Also provides check_new() which returns the count of channel videos newer
than the latest last_pulled_at without writing to the DB.

Run: python -m jobs.backfill_archive
"""
import sys
from datetime import datetime, timezone

from adapters.yt_dlp import list_channel
from app.models import SessionLocal, Video, init_db
from core.enumerate import to_video_rows
from jobs.enumerate_channel import CHANNEL_ID


def run(channel_id: str = CHANNEL_ID) -> dict:
    """Enumerate channel, insert missing Video rows, stamp last_pulled_at.

    Returns:
        {"added": int, "checked": int, "failed_tabs": list[str]}
    """
    init_db()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    entries, failed = list_channel(channel_id)
    rows = to_video_rows(entries)

    with SessionLocal() as db:
        existing_ids: set[str] = {vid for (vid,) in db.query(Video.id).all()}

        added = 0
        for r in rows:
            vid_id = r["id"]
            if vid_id not in existing_ids:
                v = Video(
                    id=vid_id,
                    title=r["title"],
                    duration=r["duration"],
                    url=r["url"],
                    last_pulled_at=now,
                )
                db.add(v)
                added += 1
            else:
                # Stamp last_pulled_at on existing rows too so check_new() works
                row = db.get(Video, vid_id)
                if row:
                    row.last_pulled_at = now
                    db.add(row)

        db.commit()

    incomplete = any(t in ("videos", "shorts") for t in failed)
    if failed:
        print(f"[warn] tabs failed: {failed} (incomplete={incomplete})")

    return {"added": added, "checked": len(rows), "failed_tabs": failed}


def check_new(channel_id: str = CHANNEL_ID) -> dict:
    """Enumerate channel and return count of videos not yet in the DB.

    Does NOT insert anything. Uses the latest last_pulled_at as the
    reference point: a video is "new" if its ID is absent from the DB.

    Returns:
        {"new_count": int, "last_pulled_at": str | None}
    """
    entries, failed = list_channel(channel_id)
    rows = to_video_rows(entries)
    channel_ids = {r["id"] for r in rows}

    with SessionLocal() as db:
        existing_ids: set[str] = {vid for (vid,) in db.query(Video.id).all()}

        # Latest last_pulled_at across all rows
        from sqlalchemy import func  # noqa: PLC0415
        latest_pull = db.query(func.max(Video.last_pulled_at)).scalar()

    new_count = len(channel_ids - existing_ids)
    last_pulled_str: str | None = None
    if latest_pull is not None:
        if isinstance(latest_pull, datetime):
            last_pulled_str = latest_pull.isoformat()
        else:
            last_pulled_str = str(latest_pull)

    incomplete = any(t in ("videos", "shorts") for t in failed)
    if failed:
        print(f"[warn] tabs failed during check_new: {failed} (incomplete={incomplete})")

    return {"new_count": new_count, "last_pulled_at": last_pulled_str}


if __name__ == "__main__":
    result = run()
    print(result)
    sys.exit(0)
