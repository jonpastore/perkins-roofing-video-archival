"""YouTube Shorts publishing adapter (I/O — coverage-omitted).

SCAFFOLD: mocked — real API wiring blocked on app-review/creds.

Real implementation uses YouTube Data API v3 ``videos.insert`` with:
  - ``snippet.title``              — clip title (≤100 chars)
  - ``snippet.description``        — caption + hashtags
  - ``status.privacyStatus``       — "public"
  - ``#Shorts`` in title/desc      — triggers Shorts shelf
  - ``part=snippet,status``
  - Resumable upload for file > 5 MB

Quota note: each ``videos.insert`` costs 1,600 units; default quota is 10,000 units/day
(~6 uploads). Channel-level quota increase requires a Google form submission.

Ref: https://developers.google.com/youtube/v3/docs/videos/insert
"""
from __future__ import annotations

import uuid


class YouTubeShortsAdapter:
    """Publish a short-form video to YouTube Shorts.

    SCAFFOLD: mocked — real API wiring blocked on app-review/creds.
    """

    # ------------------------------------------------------------------
    # PlatformAdapter interface
    # ------------------------------------------------------------------

    def publish(self, video_url: str, caption: str, token: str) -> dict:
        """SCAFFOLD: mock publish to YouTube Shorts.

        Returns a fake post id — no real API call is made.

        Args:
            video_url: Public HTTPS URL of the transcoded 9:16 video.
            caption:   Title + description with ``#Shorts`` appended.
            token:     OAuth access token (scope: ``youtube.upload``).

        Returns:
            ``{"post_id": str, "platform": "youtube_shorts", "url": str}``
        """
        # SCAFFOLD: mocked — real API wiring blocked on app-review/creds
        fake_video_id = f"yt_mock_{uuid.uuid4().hex[:12]}"
        return {
            "post_id": fake_video_id,
            "platform": "youtube_shorts",
            "url": f"https://www.youtube.com/shorts/{fake_video_id}",
        }
