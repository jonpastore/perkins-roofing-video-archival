"""Instagram Reels publishing adapter (I/O — coverage-omitted).

Implements the 3-call Instagram Content Publishing flow on
graph.instagram.com/v21.0:

  1. POST /{ig_user_id}/media  (create container, media_type=REELS)
  2. GET  /{container_id}?fields=status_code  (poll until FINISHED)
  3. POST /{ig_user_id}/media_publish          (publish container)

Credentials are read from the environment:
  IG_USER_ID              — Instagram Business / Creator account id
  META_SYSTEM_USER_TOKEN  — permanent System User token with
                            instagram_content_publish + instagram_basic +
                            pages_read_engagement (Advanced Access required)

Reference: https://developers.facebook.com/docs/instagram-api/reference/ig-user/media
           https://developers.facebook.com/docs/instagram-api/reference/ig-media
           https://developers.facebook.com/docs/instagram-api/reference/ig-user/media_publish
"""
from __future__ import annotations

import os
import time

import requests

_BASE = "https://graph.instagram.com/v21.0"
_POLL_INTERVAL = 60   # seconds between status polls
_POLL_MAX = 5         # maximum polls before giving up (~5 min)


class RateLimited(Exception):
    """Raised when the IG 50-publishes/24h limit is reached."""


class ContainerError(Exception):
    """Raised when a media container enters ERROR or EXPIRED state."""


class IgPublisher:
    """Publish a short-form video to Instagram Reels.

    Args:
        ig_user_id:   Instagram user id.  Defaults to ``$IG_USER_ID``.
        access_token: System User token.  Defaults to ``$META_SYSTEM_USER_TOKEN``.
        session:      Optional ``requests.Session`` (injected for testing).
    """

    def __init__(
        self,
        ig_user_id: str | None = None,
        access_token: str | None = None,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self._user_id = ig_user_id or os.environ["IG_USER_ID"]
        self._token = access_token or os.environ["META_SYSTEM_USER_TOKEN"]
        self._session = session or requests.Session()

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    # ------------------------------------------------------------------
    # SocialPublisher interface
    # ------------------------------------------------------------------

    def publish(self, *, video_url: str, caption: str, idempotency_key: str) -> str:
        """Full 3-call IG Reels publish flow.

        Args:
            video_url:       Public HTTPS URL of the video (no redirects).
            caption:         Caption text (≤2 200 chars recommended).
            idempotency_key: Ignored by IG (stored externally); included for
                             interface compatibility.

        Returns:
            IG media id string.

        Raises:
            RateLimited:    50-publishes/24h moving window exceeded.
            ContainerError: Container reached ERROR or EXPIRED state.
            RuntimeError:   Any other non-2xx API response.
        """
        self._check_rate_limit()
        container_id = self._create_container(video_url, caption)
        self._poll_container(container_id)
        return self._publish_container(container_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_rate_limit(self) -> None:
        """Query the content_publishing_limit endpoint; raise RateLimited if quota hit."""
        url = f"{_BASE}/{self._user_id}/content_publishing_limit"
        resp = self._session.get(
            url,
            params={"fields": "quota_usage"},
            headers=self._auth_headers(),
        )
        _raise_for_status(resp)
        data = resp.json()
        # data = {"data": [{"quota_usage": N}]}
        entries = data.get("data", [])
        if entries:
            usage = entries[0].get("quota_usage", 0)
            if usage >= 50:
                raise RateLimited(
                    f"Instagram content publishing quota exhausted (quota_usage={usage}/50 per 24h)"
                )

    def _create_container(self, video_url: str, caption: str) -> str:
        """Step 1: create the REELS media container."""
        url = f"{_BASE}/{self._user_id}/media"
        resp = self._session.post(
            url,
            params={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
            },
            headers=self._auth_headers(),
        )
        _raise_for_status(resp)
        return resp.json()["id"]

    def _poll_container(self, container_id: str) -> None:
        """Step 2: poll status_code until FINISHED; raise on ERROR/EXPIRED."""
        url = f"{_BASE}/{container_id}"
        for attempt in range(_POLL_MAX):
            if attempt > 0:
                time.sleep(_POLL_INTERVAL)
            resp = self._session.get(
                url,
                params={"fields": "status_code"},
                headers=self._auth_headers(),
            )
            _raise_for_status(resp)
            status_code = resp.json().get("status_code", "")
            if status_code == "FINISHED":
                return
            if status_code in ("ERROR", "EXPIRED"):
                raise ContainerError(
                    f"IG media container {container_id!r} reached terminal state {status_code!r}. "
                    "Create a new container — do not retry the same id."
                )
            # IN_PROGRESS or anything else → keep polling
        raise ContainerError(
            f"IG media container {container_id!r} did not reach FINISHED after "
            f"{_POLL_MAX} polls ({_POLL_MAX * _POLL_INTERVAL}s)."
        )

    def _publish_container(self, container_id: str) -> str:
        """Step 3: publish the finished container; return IG media id."""
        url = f"{_BASE}/{self._user_id}/media_publish"
        resp = self._session.post(
            url,
            params={"creation_id": container_id},
            headers=self._auth_headers(),
        )
        _raise_for_status(resp)
        return resp.json()["id"]


def _raise_for_status(resp: requests.Response) -> None:
    """Raise RuntimeError with a readable message for non-2xx responses."""
    if not resp.ok:
        raise RuntimeError(
            f"IG API error {resp.status_code}: {resp.text[:300]}"
        )
