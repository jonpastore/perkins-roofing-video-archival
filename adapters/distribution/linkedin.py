"""LinkedIn video publishing adapter (I/O — coverage-omitted).

SCAFFOLD: mocked — real API wiring blocked on app-review/creds.

Real implementation uses the LinkedIn Posts API:
  1. POST /v2/assets?action=registerUpload  (initialize upload)
  2. PUT  <uploadUrl>                       (binary upload)
  3. POST /v2/ugcPosts                      (create post with ``media.status=READY``)

Requires: ``w_member_social`` scope (personal) or ``w_organization_social`` (org page).
Org posting requires LinkedIn Partner Program access.

Ref: https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/video-shares
"""
from __future__ import annotations

import uuid


class LinkedInAdapter:
    """Publish a video post to LinkedIn.

    SCAFFOLD: mocked — real API wiring blocked on app-review/creds.
    """

    # ------------------------------------------------------------------
    # PlatformAdapter interface
    # ------------------------------------------------------------------

    def publish(self, video_url: str, caption: str, token: str) -> dict:
        """SCAFFOLD: mock publish to LinkedIn.

        Returns a fake post id — no real API call is made.

        Args:
            video_url: Public HTTPS URL of the transcoded video.
            caption:   Post commentary text (≤3,000 chars recommended).
            token:     OAuth 2.0 access token.

        Returns:
            ``{"post_id": str, "platform": "linkedin", "url": str}``
        """
        # SCAFFOLD: mocked — real API wiring blocked on app-review/creds
        fake_post_id = f"li_mock_{uuid.uuid4().hex[:12]}"
        return {
            "post_id": fake_post_id,
            "platform": "linkedin",
            "url": f"https://www.linkedin.com/feed/update/{fake_post_id}",
        }
