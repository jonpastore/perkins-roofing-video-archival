"""Facebook Reels publishing adapter (I/O — coverage-omitted).

SCAFFOLD: mocked — real API wiring blocked on app-review/creds.

Real implementation uses the Facebook Pages API:
  1. POST /{page_id}/video_reels  (upload phase — chunked or pull-from-URL)
  2. POST /{page_id}/video_reels  (finish phase — ``upload_phase=finish``)

Requires: Page access token with ``pages_manage_posts`` + ``pages_read_engagement``.
Page must be connected to a Facebook app with Reels publishing permission granted.

Ref: https://developers.facebook.com/docs/video-api/guides/reels-publishing
"""
from __future__ import annotations

import uuid


class FacebookAdapter:
    """Publish a short-form video to Facebook Reels.

    SCAFFOLD: mocked — real API wiring blocked on app-review/creds.
    """

    # ------------------------------------------------------------------
    # PlatformAdapter interface
    # ------------------------------------------------------------------

    def publish(self, video_url: str, caption: str, token: str) -> dict:
        """SCAFFOLD: mock publish to Facebook Reels.

        Returns a fake post id — no real API call is made.

        Args:
            video_url: Public HTTPS URL of the transcoded 9:16 video.
            caption:   Description / caption text (≤63,206 chars).
            token:     Page access token.

        Returns:
            ``{"post_id": str, "platform": "facebook", "url": str}``
        """
        # SCAFFOLD: mocked — real API wiring blocked on app-review/creds
        fake_video_id = f"fb_mock_{uuid.uuid4().hex[:12]}"
        return {
            "post_id": fake_video_id,
            "platform": "facebook",
            "url": f"https://www.facebook.com/reel/{fake_video_id}",
        }
