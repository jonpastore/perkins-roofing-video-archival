"""YouTube Data API ingestion — metrics + comments. NEEDS YOUTUBE_API_KEY.
ToS/quota notes: default 10k units/day; commentThreads.list = 1 unit/call (100/page);
store derived analysis, refresh periodically, honor deletions (don't cache raw indefinitely)."""
import json
import os
import urllib.parse
import urllib.request

API = "https://www.googleapis.com/youtube/v3"

def _get(path, **params):
    key = os.getenv("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("set YOUTUBE_API_KEY to use the YouTube Data API")
    params["key"] = key
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())

def video_metrics(video_id):
    d = _get("/videos", part="statistics,snippet", id=video_id)
    it = d["items"][0]; st = it["statistics"]
    return {"video_id": video_id, "title": it["snippet"]["title"],
            "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
            "comments": int(st.get("commentCount", 0))}

def comments(video_id, max_pages=5):
    out, tok = [], None
    for _ in range(max_pages):
        extra = {"pageToken": tok} if tok else {}
        d = _get("/commentThreads", part="snippet", videoId=video_id, maxResults=100, order="time", **extra)
        for it in d.get("items", []):
            sn = it["snippet"]["topLevelComment"]["snippet"]
            out.append({"author": sn.get("authorDisplayName"), "text": sn.get("textOriginal"),
                        "likes": sn.get("likeCount"), "published": sn.get("publishedAt"),
                        "updated": sn.get("updatedAt")})
        tok = d.get("nextPageToken")
        if not tok:
            break
    return out  # caller derives first/last comment timestamps + persists to MetricSnapshot/comments
