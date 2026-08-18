"""Pinterest video Pin publishing adapter (I/O — coverage-omitted).

Implements Pinterest API v5 video Pin creation:

  1. GET  {video_url}                         (download the transcoded file)
  2. POST /v5/media                           (register upload — media_type=video)
  3. POST {upload_url}                        (multipart S3 upload, no Bearer)
  4. GET  /v5/media/{media_id}                (poll until status=succeeded)
  5. POST /v5/pins                            (create Pin, source_type=video_id)

Image/link pins are not used — this is video distribution.

Credentials (constructor kwargs, not env):
  access_token  — OAuth 2.0 Bearer token (scopes: pins:write, boards:read)
  board_id      — destination board id

Optional: cover_image_url (or $PINTEREST_COVER_IMAGE_URL). When omitted the Pin
uses cover_image_key_frame_time so Pinterest picks a frame from the uploaded video.

Ref: https://developers.pinterest.com/docs/work-with-organic-content-and-users/create-boards-and-pins/
     https://developers.pinterest.com/docs/api/v5/media-create/
     https://developers.pinterest.com/docs/api/v5/pins-create/
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import unquote, urlparse

_BASE = "https://api.pinterest.com/v5"
_POLL_INTERVAL = 5
_POLL_MAX = 24  # 2 min at 5s
_HTTP_TIMEOUT = 30
_DOWNLOAD_TIMEOUT = 60
_UPLOAD_TIMEOUT = 120
_TITLE_MAX = 100
_DESC_MAX = 800
_COVER_KEYFRAME_SECONDS = 1


class PublishFailed(Exception):
    """Raised when Pinterest reports media processing status=failed."""


class PinterestPublisher:
    """Publish a short-form video Pin via Pinterest API v5.

    Args:
        access_token:    OAuth Bearer token (pins:write).
        board_id:        Destination board id.
        urlopen:         Optional ``urllib.request.urlopen`` substitute (tests).
        cover_image_url: Optional public HTTPS cover image. Falls back to
                         ``$PINTEREST_COVER_IMAGE_URL``, then a video keyframe.
    """

    def __init__(
        self,
        *,
        access_token: str,
        board_id: str,
        urlopen=None,
        cover_image_url: str | None = None,
    ) -> None:
        self._token = access_token
        self._board_id = board_id
        self._urlopen = urlopen or urllib.request.urlopen
        self._cover_image_url = (
            cover_image_url or os.environ.get("PINTEREST_COVER_IMAGE_URL") or ""
        ).strip()

    def publish(self, *, video_url: str, caption: str, idempotency_key: str) -> str:
        """Download → register → upload → poll → create Pin.

        Args:
            video_url:       Public HTTPS URL of the transcoded video.
            caption:         Pin title (first line, ≤100) + description (≤800).
            idempotency_key: Ignored by Pinterest; stored externally.

        Returns:
            Pinterest Pin ``id`` string.

        Raises:
            PublishFailed: Media processing status is ``failed``.
            RuntimeError:  Non-2xx, missing fields, empty download, or poll timeout.
        """
        _ = idempotency_key
        video_bytes = self._download_video(video_url)
        media_id, upload_url, params = self._register_media()
        self._upload_video(upload_url, params, video_bytes, _filename_from_url(video_url))
        self._poll_media(media_id)
        return self._create_pin(media_id, caption)

    def _download_video(self, video_url: str) -> bytes:
        _require_https(video_url, "video_url")
        req = urllib.request.Request(video_url, method="GET")
        _, body = self._call(req, timeout=_DOWNLOAD_TIMEOUT)
        if not body:
            raise RuntimeError("Pinterest video download returned empty body")
        return body

    def _register_media(self) -> tuple[str, str, dict]:
        data = self._json_request("POST", f"{_BASE}/media", body={"media_type": "video"})
        media_id = data.get("media_id")
        upload_url = data.get("upload_url")
        params = data.get("upload_parameters") or {}
        if not media_id or not upload_url:
            raise RuntimeError("Pinterest media register missing media_id or upload_url")
        if not isinstance(params, dict):
            raise RuntimeError("Pinterest media register upload_parameters is not an object")
        return str(media_id), str(upload_url), params

    def _upload_video(
        self, upload_url: str, params: dict, video_bytes: bytes, filename: str
    ) -> None:
        _require_https(upload_url, "upload_url")
        fields = {str(k): str(v) for k, v in params.items()}
        body, content_type = _encode_multipart(fields, filename, video_bytes)
        req = urllib.request.Request(
            upload_url,
            data=body,
            method="POST",
            headers={"Content-Type": content_type},
        )
        self._call(req, timeout=_UPLOAD_TIMEOUT)

    def _poll_media(self, media_id: str) -> None:
        url = f"{_BASE}/media/{media_id}"
        for attempt in range(_POLL_MAX):
            if attempt > 0:
                time.sleep(_POLL_INTERVAL)
            status = str(self._json_request("GET", url).get("status") or "").lower()
            if status == "succeeded":
                return
            if status == "failed":
                raise PublishFailed(f"Pinterest media {media_id!r} processing failed")
        raise RuntimeError(
            f"Pinterest media {media_id!r} did not reach succeeded after "
            f"{_POLL_MAX} polls ({_POLL_MAX * _POLL_INTERVAL}s)."
        )

    def _create_pin(self, media_id: str, caption: str) -> str:
        title, description = _title_description(caption)
        media_source: dict = {"source_type": "video_id", "media_id": media_id}
        if self._cover_image_url:
            media_source["cover_image_url"] = self._cover_image_url
        else:
            media_source["cover_image_key_frame_time"] = _COVER_KEYFRAME_SECONDS
        data = self._json_request(
            "POST",
            f"{_BASE}/pins",
            body={
                "board_id": self._board_id,
                "title": title,
                "description": description,
                "media_source": media_source,
            },
        )
        pin_id = data.get("id")
        if not pin_id:
            raise RuntimeError("Pinterest pin create returned no id")
        return str(pin_id)

    def _json_request(self, method: str, url: str, *, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        _, raw = self._call(req, timeout=_HTTP_TIMEOUT)
        return _parse_json(raw)

    def _call(self, req: urllib.request.Request, *, timeout: int) -> tuple[int, bytes]:
        try:
            with self._urlopen(req, timeout=timeout) as resp:
                status = int(getattr(resp, "status", None) or resp.getcode())
                body = resp.read() if hasattr(resp, "read") else b""
        except urllib.error.HTTPError as exc:
            err = _read_http_error(exc)
            raise RuntimeError(
                f"Pinterest API error {exc.code}: {err.decode('utf-8', 'replace')[:300]}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"Pinterest API request failed: {exc}") from exc
        if status >= 400:
            raise RuntimeError(
                f"Pinterest API error {status}: {body.decode('utf-8', 'replace')[:300]}"
            )
        return status, body


def _read_http_error(exc: urllib.error.HTTPError) -> bytes:
    try:
        return exc.read() or b""
    except OSError:
        return b""


def _parse_json(body: bytes) -> dict:
    if not body:
        return {}
    try:
        data = json.loads(body.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"Pinterest API returned invalid JSON: {body[:200]!r}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Pinterest API returned non-object JSON: {type(data).__name__}")
    return data


def _require_https(url: str, what: str) -> None:
    if not url.startswith("https://"):
        raise RuntimeError(f"{what} must be https, got {url!r}")


def _filename_from_url(video_url: str) -> str:
    name = unquote(urlparse(video_url).path.rsplit("/", 1)[-1])
    if not name or "." not in name:
        return "video.mp4"
    return name


def _title_description(caption: str) -> tuple[str, str]:
    text = caption or ""
    title = text.split("\n", 1)[0].strip()[:_TITLE_MAX]
    return title, text[:_DESC_MAX]


def _encode_multipart(fields: dict[str, str], filename: str, file_bytes: bytes) -> tuple[bytes, str]:
    boundary = "----PerkinsPinterestBoundary" + uuid.uuid4().hex
    crlf = b"\r\n"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(value.encode())
        parts.append(crlf)
    safe_name = filename.replace('"', "").replace("\r", "").replace("\n", "")
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
        f"Content-Type: video/mp4\r\n\r\n".encode()
    )
    parts.append(file_bytes)
    parts.append(crlf)
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
