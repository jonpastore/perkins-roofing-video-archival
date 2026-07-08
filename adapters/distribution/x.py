"""X (Twitter) video publishing adapter (I/O — coverage-omitted).

SCAFFOLD: mocked — real API wiring blocked on app-review/creds.

Real implementation uses X API v2:
  1. POST /2/media/upload  (INIT phase — ``command=INIT``)
  2. POST /2/media/upload  (APPEND phase — chunked binary)
  3. POST /2/media/upload  (FINALIZE phase — ``command=FINALIZE``)
  4. GET  /2/media/upload  (STATUS poll until ``state=succeeded``)
  5. POST /2/tweets        (create tweet with ``media.media_ids``)

Requires: paid API access — Basic tier ($200/mo) or pay-per-use.
OAuth 2.0 with PKCE or OAuth 1.0a (app-only for read, user-context for posting).

Ref: https://developer.x.com/en/docs/x-api/media/upload-media/api-reference/post-media-upload
     https://developer.x.com/en/docs/x-api/tweets/manage-tweets/api-reference/post-tweets
"""
from __future__ import annotations

import uuid


class XAdapter:
    """Publish a video tweet to X (Twitter).

    SCAFFOLD: mocked — real API wiring blocked on app-review/creds.
    """

    # ------------------------------------------------------------------
    # PlatformAdapter interface
    # ------------------------------------------------------------------

    def publish(self, video_url: str, caption: str, token: str) -> dict:
        """SCAFFOLD: mock publish to X.

        Returns a fake post id — no real API call is made.

        Args:
            video_url: Public HTTPS URL of the transcoded video.
            caption:   Tweet text (≤280 chars; URL counts as 23).
            token:     OAuth 2.0 Bearer token (user context required for posting).

        Returns:
            ``{"post_id": str, "platform": "x", "url": str}``
        """
        # SCAFFOLD: mocked — real API wiring blocked on app-review/creds
        fake_tweet_id = f"x_mock_{uuid.uuid4().hex[:12]}"
        return {
            "post_id": fake_tweet_id,
            "platform": "x",
            "url": f"https://x.com/i/web/status/{fake_tweet_id}",
        }
