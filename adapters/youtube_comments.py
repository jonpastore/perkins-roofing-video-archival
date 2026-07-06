"""YouTube Data API v3 — fetch top-level comment threads for a video (I/O adapter).

Coverage-omitted (adapter). Requires YOUTUBE_API_KEY in env.
Returns a list of dicts: [{comment_id, author, text, published_at, reply_count}].
"""
import os
import urllib.parse
import urllib.request
import json
from datetime import datetime


_API_BASE = "https://www.googleapis.com/youtube/v3/commentThreads"


def fetch_comments(video_id: str, max_results: int = 100) -> list[dict]:
    """Return top-level comment threads for ``video_id``.

    Paginates until ``max_results`` is reached or the API has no more pages.
    Each item: {comment_id, author, text, published_at (datetime|None), reply_count}.
    Raises RuntimeError when YOUTUBE_API_KEY is absent.
    """
    api_key = os.environ.get("YOUTUBE_API_KEY") or os.environ.get("YT_API_KEY")
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY is not set — cannot fetch comments")

    results: list[dict] = []
    page_token: str | None = None

    while len(results) < max_results:
        params: dict[str, str] = {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": str(min(100, max_results - len(results))),
            "textFormat": "plainText",
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        url = _API_BASE + "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode())

        for item in data.get("items", []):
            top = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            published_raw = top.get("publishedAt")
            try:
                published_at: datetime | None = datetime.fromisoformat(
                    published_raw.replace("Z", "+00:00")
                ) if published_raw else None
            except ValueError:
                published_at = None

            results.append({
                "comment_id": item["id"],
                "author": top.get("authorDisplayName", ""),
                "text": top.get("textDisplay", ""),
                "published_at": published_at,
                "reply_count": item.get("snippet", {}).get("totalReplyCount", 0),
            })

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return results
