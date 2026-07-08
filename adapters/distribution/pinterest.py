"""Pinterest video Pin publishing adapter (I/O — coverage-omitted).

SCAFFOLD: mocked — real API wiring blocked on app-review/creds.

Real implementation uses Pinterest API v5:
  1. POST /v5/media              (register upload — ``media_type=video``)
  2. PUT  <upload_url>           (multipart binary upload)
  3. POST /v5/pins               (create Pin with ``media_source.media_id``)

Requires: Trial→Standard app review. ``boards:write`` + ``pins:write`` scopes.
Video Pins: MP4/MOV, 4s–15min, ≤2 GB.

Ref: https://developers.pinterest.com/docs/api/v5/#tag/media
     https://developers.pinterest.com/docs/api/v5/#operation/pins/create
"""
from __future__ import annotations

import uuid


class PinterestAdapter:
    """Publish a video Pin to Pinterest.

    SCAFFOLD: mocked — real API wiring blocked on app-review/creds.
    """

    # ------------------------------------------------------------------
    # PlatformAdapter interface
    # ------------------------------------------------------------------

    def publish(self, video_url: str, caption: str, token: str) -> dict:
        """SCAFFOLD: mock publish to Pinterest.

        Returns a fake post id — no real API call is made.

        Args:
            video_url: Public HTTPS URL of the transcoded video.
            caption:   Pin title + description (title ≤100 chars).
            token:     OAuth 2.0 access token.

        Returns:
            ``{"post_id": str, "platform": "pinterest", "url": str}``
        """
        # SCAFFOLD: mocked — real API wiring blocked on app-review/creds
        fake_pin_id = f"pin_mock_{uuid.uuid4().hex[:12]}"
        return {
            "post_id": fake_pin_id,
            "platform": "pinterest",
            "url": f"https://www.pinterest.com/pin/{fake_pin_id}",
        }
