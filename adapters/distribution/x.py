"""X (Twitter) video publishing adapter (I/O — coverage-omitted).

X has no pull-from-URL for tweets. Flow is download-then-chunked-upload:

  1. GET  video_url                         (signed/public HTTPS)
  2. POST /2/media/upload                   (command=INIT)
  3. POST /2/media/upload                   (command=APPEND, 1 MiB chunks)
  4. POST /2/media/upload                   (command=FINALIZE)
  5. GET  /2/media/upload?command=STATUS    (poll until state=succeeded)
  6. POST /2/tweets                         (text + media.media_ids)

Requires a user-context OAuth 2.0 Bearer token with tweet.write.
Never log the token. urlopen is injectable — tests must not hit the network.

Ref: https://docs.x.com/x-api/media/quickstart/media-upload-chunked
     https://docs.x.com/x-api/posts/manage-tweets/api-reference/post-tweets
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

MEDIA_UPLOAD = "https://api.x.com/2/media/upload"
TWEETS = "https://api.x.com/2/tweets"
CHUNK_SIZE = 1024 * 1024
POLL_MAX = 30
POLL_DEFAULT_WAIT = 1
HTTP_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 120
_UA = "perkins-platform/1.0 (+https://perkinsroofing.net)"


class PublishFailed(Exception):
    """Raised when X media processing reports state=failed."""


class XPublisher:
    """Publish a video tweet via X API v2 chunked media upload.

    Args:
        access_token: User-context OAuth 2.0 Bearer token (tweet.write).
        urlopen:      Optional ``urllib.request.urlopen`` stand-in for tests.
    """

    def __init__(self, *, access_token: str, urlopen=None) -> None:
        if not access_token:
            raise RuntimeError("X publish requires an OAuth access token")
        self._token = access_token
        self._urlopen = urlopen or urllib.request.urlopen

    def publish(self, *, video_url: str, caption: str, idempotency_key: str) -> str:
        """Download *video_url*, chunk-upload it, tweet it. Returns tweet id.

        ``idempotency_key`` is accepted for SocialPublisher compatibility; X
        has no tweet idempotency header, so the caller stores it externally.
        """
        video = self._download(video_url)
        media_id = self._init_upload(len(video))
        self._append_all(media_id, video)
        finalized = self._finalize(media_id)
        self._wait_ready(media_id, finalized)
        return self._create_tweet(caption, media_id)

    def _download(self, video_url: str) -> bytes:
        req = urllib.request.Request(video_url, headers={"User-Agent": _UA})
        try:
            with self._urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:
                blob = resp.read() or b""
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"X video download HTTP {exc.code}") from exc
        if not blob:
            raise RuntimeError("X publish requires video bytes")
        return blob

    def _init_upload(self, total_bytes: int) -> str:
        body, ctype = _multipart(
            {
                "command": "INIT",
                "media_type": "video/mp4",
                "total_bytes": str(total_bytes),
                "media_category": "tweet_video",
            }
        )
        parsed = self._api("POST", MEDIA_UPLOAD, data=body, content_type=ctype)
        media_id = _media_id(parsed)
        if not media_id:
            raise RuntimeError("X media INIT returned no media id")
        return media_id

    def _append_all(self, media_id: str, video: bytes) -> None:
        for index, start in enumerate(range(0, len(video), CHUNK_SIZE)):
            chunk = video[start : start + CHUNK_SIZE]
            body, ctype = _multipart(
                {
                    "command": "APPEND",
                    "media_id": media_id,
                    "segment_index": str(index),
                },
                files={"media": chunk},
            )
            self._api(
                "POST",
                MEDIA_UPLOAD,
                data=body,
                content_type=ctype,
                timeout=DOWNLOAD_TIMEOUT,
            )

    def _finalize(self, media_id: str) -> dict:
        body, ctype = _multipart({"command": "FINALIZE", "media_id": media_id})
        return self._api("POST", MEDIA_UPLOAD, data=body, content_type=ctype)

    def _wait_ready(self, media_id: str, finalize_body: dict) -> None:
        info = _processing(finalize_body)
        if _ready(info):
            return
        _raise_if_failed(info, media_id)
        status_url = f"{MEDIA_UPLOAD}?{urllib.parse.urlencode({'command': 'STATUS', 'media_id': media_id})}"
        for _ in range(POLL_MAX):
            time.sleep(int(info.get("check_after_secs") or POLL_DEFAULT_WAIT))
            parsed = self._api("GET", status_url)
            info = _processing(parsed)
            if _ready(info):
                return
            _raise_if_failed(info, media_id)
        raise RuntimeError(f"X media {media_id!r} did not reach succeeded after {POLL_MAX} polls")

    def _create_tweet(self, caption: str, media_id: str) -> str:
        payload = json.dumps(
            {
                "text": caption,
                "media": {"media_ids": [media_id]},
            }
        ).encode()
        parsed = self._api(
            "POST",
            TWEETS,
            data=payload,
            content_type="application/json; charset=UTF-8",
        )
        tweet_id = _data(parsed).get("id") or ""
        if not tweet_id:
            raise RuntimeError("X POST /2/tweets returned no tweet id")
        return str(tweet_id)

    def _api(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None = None,
        content_type: str | None = None,
        timeout: int = HTTP_TIMEOUT,
    ) -> dict:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "User-Agent": _UA,
        }
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self._urlopen(req, timeout=timeout) as resp:
                raw = resp.read() or b""
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"X API error {exc.code}: {_error_snippet(exc)}") from exc
        if not raw:
            return {}
        try:
            parsed = json.loads(raw.decode())
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


def _data(payload: dict) -> dict:
    inner = payload.get("data")
    return inner if isinstance(inner, dict) else payload


def _media_id(payload: dict) -> str:
    d = _data(payload)
    return str(d.get("id") or d.get("media_id_string") or d.get("media_id") or "")


def _processing(payload: dict) -> dict:
    info = _data(payload).get("processing_info")
    return info if isinstance(info, dict) else {}


def _ready(info: dict) -> bool:
    return (not info) or info.get("state") == "succeeded"


def _raise_if_failed(info: dict, media_id: str) -> None:
    if info.get("state") != "failed":
        return
    err = info.get("error") if isinstance(info.get("error"), dict) else {}
    reason = err.get("message") or "unknown"
    raise PublishFailed(f"X media processing failed (media_id={media_id!r}): {reason}")


def _error_snippet(exc: urllib.error.HTTPError) -> str:
    try:
        return (exc.read() or b"").decode(errors="replace")[:300]
    except Exception:  # noqa: BLE001 — error path must not raise
        return ""


def _multipart(
    fields: dict[str, str],
    files: dict[str, bytes] | None = None,
) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, blob in (files or {}).items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="video.mp4"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n".encode()
            + blob
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
