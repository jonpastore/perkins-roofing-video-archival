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
import json
import os
import urllib.parse
import urllib.request
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


# ---------------------------------------------------------------------------
# Posting replies — OAuth (scope youtube.force-ssl), as the channel owner.
#
# API keys are read-only; inserting a comment requires an OAuth access token for the
# Perkins YouTube channel owner with scope https://www.googleapis.com/auth/youtube.force-ssl.
# We store a long-lived REFRESH token (obtained once via consent; see
# scripts/youtube_oauth_setup.py + docs/YOUTUBE_REPLY_OAUTH.md) and exchange it for a
# short-lived access token per post. Reuses the existing OAUTH_CLIENT_ID/SECRET.
# ---------------------------------------------------------------------------

YOUTUBE_REPLY_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_COMMENTS_INSERT = "https://www.googleapis.com/youtube/v3/comments"
_CHANNELS_MINE = "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true"


def posting_channel() -> dict | None:
    """Return the YouTube channel the stored reply token can post AS, or None.

    Exchanges the refresh token and calls channels?mine=true — the definitive
    "can this token actually post a comment?" check. A token can be valid and
    correctly scoped yet still 403 on comments.insert if the authorizing Google
    account has NO YouTube channel (or is the wrong account): comments are posted
    AS a channel. Returns {"id", "title"} of the authorized channel, or None when
    unconfigured, the exchange fails, or the account has no channel. Never raises.
    """
    try:
        access = _owner_access_token()
    except Exception:  # noqa: BLE001 — unconfigured / exchange failure → not postable
        return None
    try:
        req = urllib.request.Request(
            _CHANNELS_MINE, headers={"Authorization": f"Bearer {access}"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 — fixed Google API URL
            data = json.loads(resp.read().decode())
    except Exception:  # noqa: BLE001
        return None
    items = data.get("items") or []
    if not items:
        return None
    ch = items[0]
    return {"id": ch.get("id"), "title": (ch.get("snippet") or {}).get("title", "")}


def reply_oauth_configured() -> bool:
    """True when the owner refresh token + OAuth client creds are all present."""
    return bool(
        os.environ.get("YOUTUBE_OAUTH_REFRESH_TOKEN")
        and os.environ.get("OAUTH_CLIENT_ID")
        and os.environ.get("OAUTH_CLIENT_SECRET")
    )


def _owner_access_token() -> str:
    """Exchange the stored owner refresh token for a fresh access token."""
    refresh = os.environ.get("YOUTUBE_OAUTH_REFRESH_TOKEN", "")
    client_id = os.environ.get("OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("OAUTH_CLIENT_SECRET", "")
    if not (refresh and client_id and client_secret):
        raise RuntimeError(
            "YouTube reply OAuth not configured — set YOUTUBE_OAUTH_REFRESH_TOKEN "
            "(scope youtube.force-ssl) plus OAUTH_CLIENT_ID/OAUTH_CLIENT_SECRET"
        )
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(_TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — fixed Google token URL
        tok = json.loads(resp.read().decode())
    access = tok.get("access_token")
    if not access:
        raise RuntimeError("YouTube OAuth token exchange returned no access_token")
    return access


def post_reply(parent_comment_id: str, text: str) -> dict:
    """Post *text* as a reply to the top-level comment *parent_comment_id* on YouTube.

    Uses an OAuth access token for the channel owner (scope youtube.force-ssl). The
    CommentDraft.comment_id (a commentThread id) equals the top-level comment id, which is
    the required parentId. Returns the created comment resource.

    Raises RuntimeError('YouTube reply OAuth not configured…') when no refresh token is set,
    so callers can surface a clear "connect YouTube" message instead of a 500.
    """
    access = _owner_access_token()
    body = json.dumps({
        "snippet": {"parentId": parent_comment_id, "textOriginal": text},
    }).encode()
    url = _COMMENTS_INSERT + "?" + urllib.parse.urlencode({"part": "snippet"})
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — fixed Google API URL
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        # Surface YouTube's actual reason instead of a bare 403. The most common one
        # (reason=forbidden on a valid, force-ssl token) is "the authorizing account
        # has no channel / is the wrong channel" — a reconnect problem, not a code bug.
        detail = ""
        try:
            err = json.loads(exc.read().decode()).get("error", {})
            errs = err.get("errors") or [{}]
            detail = f"{errs[0].get('reason', '')}: {err.get('message', '')}"
        except Exception:  # noqa: BLE001 — best-effort error detail
            pass
        raise RuntimeError(f"YouTube comments.insert HTTP {exc.code} — {detail}".strip()) from exc
