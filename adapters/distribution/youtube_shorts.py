"""YouTube Shorts publishing adapter (I/O — coverage-omitted).

videos.insert resumable upload. Quota 1,600 units each; default 10k/day (~6 uploads).
Needs an OAuth access token that can write (youtube.force-ssl / youtube.upload).
"""
from __future__ import annotations

import urllib.request

from core.youtube_upload import upload_short


class YouTubeShortsPublisher:
    """Publish a short-form video to YouTube Shorts."""

    def __init__(self, *, access_token: str, urlopen=None):
        if not access_token:
            raise RuntimeError("YouTube Shorts publish requires an access token")
        self._token = access_token
        self._urlopen = urlopen or urllib.request.urlopen

    def publish(self, *, video_url: str, caption: str, idempotency_key: str) -> str:
        del idempotency_key
        req = urllib.request.Request(video_url)
        with self._urlopen(req, timeout=120) as resp:
            video_bytes = resp.read()
        out = upload_short(
            video_bytes=video_bytes, caption=caption, access_token=self._token,
            urlopen=self._urlopen,
        )
        return out["post_id"]


# leftover name for any import that still uses the scaffold class
YouTubeShortsAdapter = YouTubeShortsPublisher
