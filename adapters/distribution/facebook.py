"""Facebook Reels publishing adapter (I/O — coverage-omitted).

Page Reels via Graph API v25.0, hosted-file (file_url) flow:

  1. POST https://graph.facebook.com/v25.0/{page_id}/video_reels
        JSON: {"upload_phase": "start"}
        Auth: Authorization: Bearer {page access token}
        -> {"video_id": "...", "upload_url": "..."}

  2. POST https://rupload.facebook.com/video-upload/v25.0/{video_id}
        Headers: Authorization: OAuth {token}, file_url: {video_url}
        -> {"success": true}

  3. POST https://graph.facebook.com/v25.0/{page_id}/video_reels
        JSON: {"upload_phase": "finish", "video_id": "...",
               "video_state": "PUBLISHED", "description": caption}
        Auth: Authorization: Bearer {token}
        -> {"success": true}

The access token is never placed in a URL, JSON body, or log line.
Non-2xx responses raise RuntimeError with the HTTP status only.

Requires a Page access token with pages_manage_posts + pages_read_engagement.

Ref: https://developers.facebook.com/docs/video-api/guides/reels-publishing
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

_GRAPH_VERSION = "v25.0"
_GRAPH_REELS = f"https://graph.facebook.com/{_GRAPH_VERSION}/{{page_id}}/video_reels"
_RUPLOAD = f"https://rupload.facebook.com/video-upload/{_GRAPH_VERSION}/{{video_id}}"
_HTTP_TIMEOUT = 30


class FacebookPublisher:
    """Publish a short-form video to a Facebook Page as a Reel.

    Construct from a creds dict ``{"access_token": ..., "page_id": ...}``:

        FacebookPublisher(access_token=creds["access_token"], page_id=creds["page_id"])
    """

    def __init__(self, *, access_token: str, page_id: str, urlopen=None) -> None:
        self._access_token = access_token
        self._page_id = page_id
        self._urlopen = urlopen or urllib.request.urlopen

    def publish(self, *, video_url: str, caption: str, idempotency_key: str) -> str:
        """Start upload (file_url) then finish. Returns the Graph video_id.

        ``idempotency_key`` is unused here — social_job stores it externally.
        """
        del idempotency_key
        video_id = self._start()
        self._upload_file_url(video_id, video_url)
        self._finish(video_id, caption)
        return video_id

    def _reels_url(self) -> str:
        return _GRAPH_REELS.format(page_id=self._page_id)

    def _start(self) -> str:
        data = self._json_post(self._reels_url(), {"upload_phase": "start"})
        video_id = data.get("video_id")
        if not video_id:
            raise RuntimeError("Facebook API error: missing video_id")
        return str(video_id)

    def _upload_file_url(self, video_id: str, video_url: str) -> None:
        req = urllib.request.Request(
            _RUPLOAD.format(video_id=video_id),
            data=b"",
            method="POST",
            headers={
                "Authorization": f"OAuth {self._access_token}",
                "file_url": video_url,
            },
        )
        self._open(req)

    def _finish(self, video_id: str, caption: str) -> None:
        self._json_post(
            self._reels_url(),
            {
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "description": caption,
            },
        )

    def _json_post(self, url: str, body: dict) -> dict:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            },
        )
        raw = self._open(req)
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode())
        except json.JSONDecodeError as exc:
            raise RuntimeError("Facebook API error: invalid JSON") from exc
        return parsed if isinstance(parsed, dict) else {}

    def _open(self, req: urllib.request.Request) -> bytes:
        try:
            with self._urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                status = getattr(resp, "status", None) or getattr(resp, "code", 200)
                body = resp.read() or b""
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Facebook API error {exc.code}") from exc
        if not (200 <= int(status) < 300):
            raise RuntimeError(f"Facebook API error {status}")
        return body
