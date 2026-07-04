"""Cloud Run Job: enumerate the full Perkins channel (videos + shorts + streams) and
upsert Video rows. Idempotent — re-running refreshes titles/urls, adds new videos.

Run: .venv/bin/python -m jobs.enumerate_channel [limit_per_tab]
"""
import sys

from adapters.yt_dlp import list_channel
from app.models import SessionLocal, Video, init_db
from core.enumerate import to_video_rows

CHANNEL_ID = "UChJZpBYXOuR0j1EHJugv5hg"  # Perkins Roofing Corp


def run(channel_id=CHANNEL_ID, limit=None):
    init_db()
    entries, failed = list_channel(channel_id, limit=limit)
    rows = to_video_rows(entries)
    s = SessionLocal()
    for r in rows:
        v = s.get(Video, r["id"]) or Video(id=r["id"])
        v.title = r["title"] or v.title
        if r["duration"] is not None:
            v.duration = r["duration"]
        v.url = r["url"]
        s.add(v)
    s.commit()
    total = s.query(Video).count()
    s.close()
    # A dropped videos/shorts tab means the enumeration is incomplete — surface it, don't hide it.
    incomplete = any(t in ("videos", "shorts") for t in failed)
    if failed:
        print(f"[warn] tabs failed during enumeration: {failed} (incomplete={incomplete})")
    return {"enumerated": len(rows),
            "shorts": sum(1 for r in rows if r["is_short"]),
            "videos_in_db": total,
            "failed_tabs": failed,
            "incomplete": incomplete}


if __name__ == "__main__":
    _limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    result = run(limit=_limit)
    print(result)
    sys.exit(1 if result["incomplete"] else 0)  # non-zero exit on partial enumeration
