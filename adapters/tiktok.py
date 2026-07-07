"""TikTok Content Posting API adapter (I/O — coverage-omitted).

Implements the PULL_FROM_URL flow on open.tiktokapis.com:

  1. POST /v2/post/publish/video/init/         (init with source=PULL_FROM_URL)
  2. POST /v2/post/publish/status/fetch/       (poll until PUBLISH_COMPLETE)

No upload step; no finalize step.  Token refresh is handled via
refresh_access_token().

Credentials are read from the environment:
  TIKTOK_ACCESS_TOKEN   — OAuth Bearer access token (scope: video.publish)
  TIKTOK_OPEN_ID        — Creator open_id (returned during OAuth)
  TIKTOK_CLIENT_KEY     — App client key (for token refresh)
  TIKTOK_CLIENT_SECRET  — App client secret (for token refresh)
  TIKTOK_REFRESH_TOKEN  — Long-lived refresh token

Reference: https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
           https://developers.tiktok.com/doc/content-posting-api-reference-query-video-status
           https://developers.tiktok.com/doc/oauth-user-access-token-management
"""
from __future__ import annotations

import os
import time

import requests

_BASE = "https://open.tiktokapis.com"
_POLL_INTERVAL = 10   # seconds between status polls
_POLL_MAX = 30        # maximum polls (5 min total at 10s interval)
_HTTP_TIMEOUT = 30    # per-request (connect+read) timeout — never hang the social cron


class PublishFailed(Exception):
    """Raised when TikTok reports FAILED status with a fail_reason."""


class TikTokPublisher:
    """Publish a short-form video to TikTok via the Content Posting API.

    Args:
        access_token:  OAuth Bearer token.  Defaults to ``$TIKTOK_ACCESS_TOKEN``.
        open_id:       Creator open_id.  Defaults to ``$TIKTOK_OPEN_ID``.
        session:       Optional ``requests.Session`` (injected for testing).
    """

    def __init__(
        self,
        access_token: str | None = None,
        open_id: str | None = None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self._token = access_token or os.environ["TIKTOK_ACCESS_TOKEN"]
        self._open_id = open_id or os.environ["TIKTOK_OPEN_ID"]
        self._session = session or requests.Session()

    # ------------------------------------------------------------------
    # SocialPublisher interface
    # ------------------------------------------------------------------

    def publish(self, *, video_url: str, caption: str, idempotency_key: str) -> str:
        """PULL_FROM_URL init + poll flow.

        Args:
            video_url:       Public HTTPS URL of the video.  The GCS bucket
                             domain must be verified via DNS TXT prefix
                             verification before TikTok allows PULL_FROM_URL.
            caption:         Title / description (≤150 chars per TikTok spec).
            idempotency_key: Ignored by TikTok; stored externally for our
                             idempotency guard.

        Returns:
            TikTok ``publish_id`` string.

        Raises:
            PublishFailed: TikTok returned FAILED status with a fail_reason.
            RuntimeError:  Non-2xx API response or poll timeout.
        """
        publish_id = self._init_upload(video_url, caption)
        self._poll_status(publish_id)
        return publish_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _init_upload(self, video_url: str, caption: str) -> str:
        """Step 1: POST /v2/post/publish/video/init/ — returns publish_id."""
        url = f"{_BASE}/v2/post/publish/video/init/"
        body = {
            "post_info": {
                "title": caption,
                "privacy_level": "SELF_ONLY",
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": video_url,
            },
        }
        resp = self._session.post(url, json=body, headers=self._auth_headers(), timeout=_HTTP_TIMEOUT)
        _raise_for_status(resp)
        data = resp.json()
        return data["data"]["publish_id"]

    def _poll_status(self, publish_id: str) -> None:
        """Step 2: poll /v2/post/publish/status/fetch/ until PUBLISH_COMPLETE."""
        url = f"{_BASE}/v2/post/publish/status/fetch/"
        for attempt in range(_POLL_MAX):
            if attempt > 0:
                time.sleep(_POLL_INTERVAL)
            resp = self._session.post(
                url,
                json={"publish_id": publish_id},
                headers=self._auth_headers(),
                timeout=_HTTP_TIMEOUT,
            )
            _raise_for_status(resp)
            data = resp.json().get("data", {})
            status = data.get("status", "")
            if status == "PUBLISH_COMPLETE":
                return
            if status == "FAILED":
                fail_reason = data.get("fail_reason", "unknown")
                raise PublishFailed(
                    f"TikTok publish failed (publish_id={publish_id!r}): {fail_reason}"
                )
            # PROCESSING_DOWNLOAD or anything else → keep polling
        raise RuntimeError(
            f"TikTok publish_id {publish_id!r} did not reach PUBLISH_COMPLETE after "
            f"{_POLL_MAX} polls ({_POLL_MAX * _POLL_INTERVAL}s)."
        )


def refresh_access_token(
    *,
    client_key: str | None = None,
    client_secret: str | None = None,
    refresh_token: str | None = None,
    session: requests.Session | None = None,
) -> dict:
    """Refresh a TikTok OAuth access token.

    Uses the /v2/oauth/token/ endpoint with grant_type=refresh_token.

    Args:
        client_key:    App client key.  Defaults to ``$TIKTOK_CLIENT_KEY``.
        client_secret: App client secret.  Defaults to ``$TIKTOK_CLIENT_SECRET``.
        refresh_token: Long-lived refresh token.  Defaults to
                       ``$TIKTOK_REFRESH_TOKEN``.
        session:       Optional requests.Session for testing.

    Returns:
        Dict with ``access_token``, ``refresh_token``, ``expires_in``, etc.

    Raises:
        RuntimeError: on non-2xx response.
    """
    key = client_key or os.environ["TIKTOK_CLIENT_KEY"]
    secret = client_secret or os.environ["TIKTOK_CLIENT_SECRET"]
    token = refresh_token or os.environ["TIKTOK_REFRESH_TOKEN"]
    sess = session or requests.Session()

    url = f"{_BASE}/v2/oauth/token/"
    resp = sess.post(
        url,
        data={
            "client_key": key,
            "client_secret": secret,
            "grant_type": "refresh_token",
            "refresh_token": token,
        },
        timeout=_HTTP_TIMEOUT,
    )
    _raise_for_status(resp)
    return resp.json()


def _raise_for_status(resp: requests.Response) -> None:
    """Raise RuntimeError with a readable message for non-2xx responses."""
    if not resp.ok:
        raise RuntimeError(
            f"TikTok API error {resp.status_code}: {resp.text[:300]}"
        )
