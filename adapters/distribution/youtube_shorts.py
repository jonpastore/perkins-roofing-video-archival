"""YouTube Shorts publishing adapter (I/O — coverage-omitted).

videos.insert resumable upload. Quota 1,600 units each; default 10k/day (~6 uploads).
Needs an OAuth access token that can write (youtube.force-ssl / youtube.upload).
"""
from __future__ import annotations

import urllib.request

from core.youtube_upload import upload_short


class YouTubeShortsAdapter:
    """Publish a short-form video to YouTube Shorts."""

    def publish(self, video_url: str, caption: str, token: str) -> dict:
        req = urllib.request.Request(video_url)
        with urllib.request.urlopen(req, timeout=120) as resp:
            video_bytes = resp.read()
        return upload_short(
            video_bytes=video_bytes, caption=caption, access_token=token,
        )
