"""YouTube Data API v3 — fetch top-level comment threads for a video (I/O adapter).

Coverage-omitted (adapter). Requires YOUTUBE_API_KEY in env.
Returns a list of dicts:
  [{comment_id, author, author_channel_id, text, published_at,
    reply_count, has_owner_reply}]

has_owner_reply is True only when a reply authored by owner_channel_id exists
in the thread's embedded replies (requires part=snippet,replies).  When
owner_channel_id is None the field is always False (conservative: do not
suppress flagging for unknown owner).
"""
import os
import urllib.parse
import urllib.request
import json
from datetime import datetime


_API_BASE = "https://www.googleapis.com/youtube/v3/commentThreads"


def fetch_comments(
    video_id: str,
    max_results: int = 100,
    owner_channel_id: str | None = None,
) -> list[dict]:
    """Return top-level comment threads for ``video_id``.

    Paginates until ``max_results`` is reached or the API has no more pages.

    Each item: {comment_id, author, author_channel_id, text,
                published_at (datetime|None), reply_count, has_owner_reply}.

    ``has_owner_reply`` is True only when a reply from *owner_channel_id*
    appears in the embedded replies list (part=snippet,replies).  It is always
    False when owner_channel_id is None.

    Raises RuntimeError when YOUTUBE_API_KEY is absent.
    """
    api_key = os.environ.get("YOUTUBE_API_KEY") or os.environ.get("YT_API_KEY")
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY is not set — cannot fetch comments")

    results: list[dict] = []
    page_token: str | None = None

    while len(results) < max_results:
        params: dict[str, str] = {
            "part": "snippet,replies",
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

            author_channel_id: str = (
                top.get("authorChannelId", {}).get("value", "")
                if isinstance(top.get("authorChannelId"), dict)
                else top.get("authorChannelId") or ""
            )

            # Detect a real owner reply in the embedded replies list.
            has_owner_reply = False
            if owner_channel_id:
                for reply in item.get("replies", {}).get("comments", []):
                    reply_author_id = (
                        reply.get("snippet", {})
                        .get("authorChannelId", {})
                        .get("value", "")
                    )
                    if reply_author_id == owner_channel_id:
                        has_owner_reply = True
                        break

            results.append({
                "comment_id": item["id"],
                "author": top.get("authorDisplayName", ""),
                "author_channel_id": author_channel_id,
                "text": top.get("textDisplay", ""),
                "published_at": published_at,
                "reply_count": item.get("snippet", {}).get("totalReplyCount", 0),
                "has_owner_reply": has_owner_reply,
            })

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return results
