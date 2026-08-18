"""Mocked-HTTP tests for adapters/distribution/facebook.py — no live network."""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from adapters.distribution.facebook import FacebookPublisher

TOKEN = "page_token_secret"
PAGE_ID = "111222333"
VIDEO_URL = "https://storage.example.com/reel.mp4"
CAPTION = "Roof repair in 60s #PerkinsRoofing"


class _Resp:
    """urlopen context-manager returning a fixed JSON body / status."""

    def __init__(self, body: dict | bytes, status: int = 200):
        self._body = json.dumps(body).encode() if isinstance(body, dict) else body
        self.status = status
        self.code = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code: int, url: str = "https://graph.facebook.com/x") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "err", {}, io.BytesIO(b"{}"))


def _header(req: urllib.request.Request, name: str) -> str | None:
    want = name.lower()
    for key, val in req.header_items():
        if key.lower() == want:
            return val
    return None


def _json_body(req: urllib.request.Request) -> dict:
    if not req.data:
        return {}
    return json.loads(req.data.decode())


def _publisher(urlopen) -> FacebookPublisher:
    return FacebookPublisher(access_token=TOKEN, page_id=PAGE_ID, urlopen=urlopen)


def _queue_urlopen(responses):
    calls: list[tuple[urllib.request.Request, object]] = []
    queue = list(responses)

    def fake_urlopen(req, timeout=None):
        calls.append((req, timeout))
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    return fake_urlopen, calls


def _happy_responses():
    return [
        _Resp({"video_id": "vid_abc", "upload_url": "https://rupload.facebook.com/video-upload/vid_abc"}),
        _Resp({"success": True}),
        _Resp({"success": True}),
    ]


def test_construct_from_creds_dict():
    creds = {"access_token": TOKEN, "page_id": PAGE_ID}
    urlopen, _ = _queue_urlopen(_happy_responses())
    pub = FacebookPublisher(
        access_token=creds["access_token"],
        page_id=creds["page_id"],
        urlopen=urlopen,
    )
    assert pub.publish(video_url=VIDEO_URL, caption=CAPTION, idempotency_key="k") == "vid_abc"


def test_publish_start_file_url_finish_returns_video_id():
    urlopen, calls = _queue_urlopen(_happy_responses())
    result = _publisher(urlopen).publish(
        video_url=VIDEO_URL,
        caption=CAPTION,
        idempotency_key="series-1-part-0",
    )
    assert result == "vid_abc"
    assert len(calls) == 3

    start_req, start_timeout = calls[0]
    assert start_req.full_url == f"https://graph.facebook.com/v25.0/{PAGE_ID}/video_reels"
    assert start_req.get_method() == "POST"
    assert _header(start_req, "Authorization") == f"Bearer {TOKEN}"
    assert _header(start_req, "Content-Type") == "application/json"
    assert _json_body(start_req) == {"upload_phase": "start"}
    assert start_timeout is not None

    upload_req, upload_timeout = calls[1]
    assert upload_req.full_url == "https://rupload.facebook.com/video-upload/v25.0/vid_abc"
    assert upload_req.get_method() == "POST"
    assert _header(upload_req, "Authorization") == f"OAuth {TOKEN}"
    assert _header(upload_req, "file_url") == VIDEO_URL
    assert upload_timeout is not None

    finish_req, finish_timeout = calls[2]
    assert finish_req.full_url == f"https://graph.facebook.com/v25.0/{PAGE_ID}/video_reels"
    assert finish_req.get_method() == "POST"
    assert _header(finish_req, "Authorization") == f"Bearer {TOKEN}"
    assert _json_body(finish_req) == {
        "upload_phase": "finish",
        "video_id": "vid_abc",
        "video_state": "PUBLISHED",
        "description": CAPTION,
    }
    assert finish_timeout is not None


def test_token_never_in_url_or_json_body():
    urlopen, calls = _queue_urlopen(_happy_responses())
    _publisher(urlopen).publish(video_url=VIDEO_URL, caption=CAPTION, idempotency_key="k")
    for req, _timeout in calls:
        assert TOKEN not in req.full_url
        body = _json_body(req)
        assert "access_token" not in body
        dumped = json.dumps(body)
        assert TOKEN not in dumped


def test_start_http_error_raises_status_only():
    urlopen, _ = _queue_urlopen([_http_error(400)])
    with pytest.raises(RuntimeError, match=r"Facebook API error 400$") as excinfo:
        _publisher(urlopen).publish(video_url=VIDEO_URL, caption=CAPTION, idempotency_key="k")
    assert TOKEN not in str(excinfo.value)


def test_upload_http_error_raises_status_only():
    urlopen, _ = _queue_urlopen([
        _Resp({"video_id": "vid_err"}),
        _http_error(500),
    ])
    with pytest.raises(RuntimeError, match=r"Facebook API error 500$"):
        _publisher(urlopen).publish(video_url=VIDEO_URL, caption=CAPTION, idempotency_key="k")


def test_finish_http_error_raises_status_only():
    urlopen, _ = _queue_urlopen([
        _Resp({"video_id": "vid_fin"}),
        _Resp({"success": True}),
        _http_error(403),
    ])
    with pytest.raises(RuntimeError, match=r"Facebook API error 403$"):
        _publisher(urlopen).publish(video_url=VIDEO_URL, caption=CAPTION, idempotency_key="k")


def test_non_2xx_status_without_httperror():
    urlopen, _ = _queue_urlopen([_Resp({"error": "nope"}, status=429)])
    with pytest.raises(RuntimeError, match=r"Facebook API error 429$"):
        _publisher(urlopen).publish(video_url=VIDEO_URL, caption=CAPTION, idempotency_key="k")


def test_start_missing_video_id_raises():
    urlopen, _ = _queue_urlopen([_Resp({"upload_url": "https://rupload.facebook.com/x"})])
    with pytest.raises(RuntimeError, match="missing video_id"):
        _publisher(urlopen).publish(video_url=VIDEO_URL, caption=CAPTION, idempotency_key="k")


def test_every_request_sets_a_timeout():
    urlopen, calls = _queue_urlopen(_happy_responses())
    _publisher(urlopen).publish(video_url=VIDEO_URL, caption=CAPTION, idempotency_key="k")
    assert calls
    for _req, timeout in calls:
        assert timeout is not None
