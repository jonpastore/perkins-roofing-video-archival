"""YouTube Data API v3 — fetch video statistics and latest comment timestamp.

Coverage-omitted (I/O adapter). Requires YOUTUBE_API_KEY in env.

Public API:
    fetch_stats(video_ids)       -> {video_id: {views, likes, comments}}
    latest_comment_at(video_id) -> ISO-8601 str | None
"""
import json
import os
import urllib.parse
import urllib.request

_VIDEOS_API = "https://www.googleapis.com/youtube/v3/videos"
_COMMENTS_API = "https://www.googleapis.com/youtube/v3/commentThreads"


def _api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY") or os.environ.get("YT_API_KEY")
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY is not set — cannot call YouTube API")
    return key


def fetch_stats(video_ids: list[str]) -> dict[str, dict]:
    """Batch-fetch statistics for up to any number of video IDs.

    Splits into pages of 50 (API max) automatically.
    Returns {video_id: {views: int, likes: int, comments: int}}.
    Missing or deleted videos are omitted from the result.
    """
    key = _api_key()
    result: dict[str, dict] = {}

    # API max per request is 50 ids
    for offset in range(0, len(video_ids), 50):
        batch = video_ids[offset : offset + 50]
        params = {
            "part": "statistics",
            "id": ",".join(batch),
            "key": key,
        }
        url = _VIDEOS_API + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode())

        for item in data.get("items", []):
            vid = item.get("id")
            stats = item.get("statistics", {})
            result[vid] = {
                "views": int(stats.get("viewCount") or 0),
                "likes": int(stats.get("likeCount") or 0),
                "comments": int(stats.get("commentCount") or 0),
            }

    return result


def fetch_titles(video_ids: list[str]) -> dict[str, str]:
    """Batch-fetch the current YouTube title (snippet.title) for up to any number of ids.

    Splits into pages of 50. Returns {video_id: title}. Missing/deleted videos are omitted.
    Used to re-parse a better name from YouTube for archived videos.
    """
    key = _api_key()
    result: dict[str, str] = {}
    for offset in range(0, len(video_ids), 50):
        batch = video_ids[offset : offset + 50]
        params = {"part": "snippet", "id": ",".join(batch), "key": key}
        url = _VIDEOS_API + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 — fixed Google API URL
            data = json.loads(resp.read().decode())
        for item in data.get("items", []):
            vid = item.get("id")
            title = (item.get("snippet", {}) or {}).get("title")
            if vid and title:
                result[vid] = title
    return result


def latest_comment_at(video_id: str) -> str | None:
    """Return the publishedAt timestamp of the newest top-level comment, or None.

    Uses commentThreads?order=time&maxResults=1. Returns the raw ISO-8601 string
    from the API (e.g. "2024-06-01T12:00:00Z"), or None if comments are disabled
    or the video has no comments.
    """
    key = _api_key()
    params = {
        "part": "snippet",
        "videoId": video_id,
        "order": "time",
        "maxResults": "1",
        "textFormat": "plainText",
        "key": key,
    }
    url = _COMMENTS_API + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception:  # noqa: BLE001 — disabled comments returns 403; treat as None
        return None

    items = data.get("items", [])
    if not items:
        return None
    top = items[0].get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
    return top.get("publishedAt") or None
