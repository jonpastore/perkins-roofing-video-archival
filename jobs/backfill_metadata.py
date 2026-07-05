"""Backfill video metadata (upload_date, duration, views/likes/comments) from the YouTube
Data API. The channel enumerator uses yt-dlp flat-playlist which omits these, so ~all rows
were missing upload_date and most were missing duration. Idempotent: re-run any time; only
fills what the API returns. Requires YOUTUBE_API_KEY.

Run: python -m jobs.backfill_metadata
"""
import os
import re
import json
import logging
import urllib.request

from app.models import SessionLocal, Video

logger = logging.getLogger(__name__)

_DUR = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def _iso8601_to_seconds(iso: str) -> float | None:
    m = _DUR.fullmatch(iso or "")
    if not m:
        return None
    h, mn, s = (int(x) if x else 0 for x in m.groups())
    return float(h * 3600 + mn * 60 + s)


def _fetch_batch(ids: list[str], key: str) -> dict:
    url = (
        "https://www.googleapis.com/youtube/v3/videos"
        f"?part=snippet,contentDetails,statistics&id={','.join(ids)}&key={key}"
    )
    data = json.load(urllib.request.urlopen(url, timeout=30))
    out = {}
    for it in data.get("items", []):
        sn, cd, st = it.get("snippet", {}), it.get("contentDetails", {}), it.get("statistics", {})
        out[it["id"]] = {
            "upload_date": (sn.get("publishedAt") or "")[:10] or None,  # YYYY-MM-DD
            "duration": _iso8601_to_seconds(cd.get("duration", "")),
            "views": int(st["viewCount"]) if st.get("viewCount") else None,
            "likes": int(st["likeCount"]) if st.get("likeCount") else None,
            "comments": int(st["commentCount"]) if st.get("commentCount") else None,
        }
    return out


def run() -> dict:
    key = os.getenv("YOUTUBE_API_KEY", "")
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY not set")
    db = SessionLocal()
    try:
        ids = [v.id for v in db.query(Video.id).all()]
        updated = 0
        for i in range(0, len(ids), 50):
            batch = ids[i : i + 50]
            meta = _fetch_batch(batch, key)
            for vid, m in meta.items():
                v = db.get(Video, vid)
                if not v:
                    continue
                # only fill missing / refresh stats
                if m["upload_date"]:
                    v.upload_date = m["upload_date"]
                if m["duration"] is not None:
                    v.duration = m["duration"]
                if m["views"] is not None:
                    v.views = m["views"]
                    v.likes = m["likes"]
                    v.comments = m["comments"]
                updated += 1
            db.commit()
            logger.info("backfilled %d/%d", min(i + 50, len(ids)), len(ids))
        return {"total": len(ids), "updated": updated}
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(run(), indent=2))
