"""Mocked-urlopen tests for adapters.distribution.pinterest (no live network)."""
from __future__ import annotations

import json
import urllib.error
from io import BytesIO

import pytest

from adapters.distribution.pinterest import PinterestPublisher, PublishFailed

_VIDEO_URL = "https://example.com/reels/1/0.mp4"
_UPLOAD_URL = "https://pinterest-media-upload.s3-accelerate.amazonaws.com/"
_VIDEO_BYTES = b"fake-mp4-bytes"
_MEDIA_ID = "555"
_PIN_ID = "987654321"
_BOARD_ID = "111222333"
_TOKEN = "pina_test_token"


class _Resp:
    def __init__(self, body=b"", status=200):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _register_payload():
    return {
        "media_id": _MEDIA_ID,
        "media_type": "video",
        "upload_url": _UPLOAD_URL,
        "upload_parameters": {
            "Content-Type": "multipart/form-data",
            "key": "uploads/abc",
            "policy": "eyJ",
            "x-amz-algorithm": "AWS4-HMAC-SHA256",
            "x-amz-credential": "cred",
            "x-amz-date": "20220127T185143Z",
            "x-amz-security-token": "tok",
            "x-amz-signature": "sig",
        },
    }


def _happy_queue(**overrides):
    queue = [
        _Resp(_VIDEO_BYTES),
        _Resp(_register_payload()),
        _Resp(b"", status=204),
        _Resp({"media_id": _MEDIA_ID, "media_type": "video", "status": "succeeded"}),
        _Resp({"id": _PIN_ID}, status=201),
    ]
    for idx, resp in overrides.items():
        queue[int(idx)] = resp
    return queue


def _make_urlopen(queue):
    calls = []
    pending = list(queue)

    def urlopen(req, timeout=None):
        calls.append((req.get_method(), req.full_url, req, timeout))
        item = pending.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    return urlopen, calls


def _publisher(urlopen, **kw):
    kwargs = {"access_token": _TOKEN, "board_id": _BOARD_ID, "urlopen": urlopen}
    kwargs.update(kw)
    return PinterestPublisher(**kwargs)


def _pin_body(calls):
    for method, url, req, _timeout in calls:
        if method == "POST" and url.endswith("/v5/pins"):
            return json.loads(req.data.decode())
    raise AssertionError("no POST /v5/pins call captured")


def test_publish_happy_path():
    urlopen, calls = _make_urlopen(_happy_queue())
    result = _publisher(urlopen, cover_image_url="https://example.com/cover.jpg").publish(
        video_url=_VIDEO_URL,
        caption="Roof repair tips\n\n#roofing",
        idempotency_key="series-1-part-0",
    )

    assert result == _PIN_ID
    assert not result.startswith("pin_mock_")
    assert len(calls) == 5

    assert calls[0][0] == "GET" and calls[0][1] == _VIDEO_URL
    assert calls[1][0] == "POST" and calls[1][1].endswith("/v5/media")
    register = json.loads(calls[1][2].data.decode())
    assert register == {"media_type": "video"}
    assert calls[2][0] == "POST" and calls[2][1] == _UPLOAD_URL
    assert _VIDEO_BYTES in calls[2][2].data
    assert b'name="key"' in calls[2][2].data
    assert calls[3][0] == "GET" and calls[3][1].endswith(f"/v5/media/{_MEDIA_ID}")
    assert calls[4][0] == "POST" and calls[4][1].endswith("/v5/pins")

    body = _pin_body(calls)
    assert body["board_id"] == _BOARD_ID
    assert body["title"] == "Roof repair tips"
    assert "#roofing" in body["description"]
    assert body["media_source"]["source_type"] == "video_id"
    assert body["media_source"]["media_id"] == _MEDIA_ID
    assert body["media_source"]["cover_image_url"] == "https://example.com/cover.jpg"
    assert body["media_source"].get("url") is None


def test_publish_uses_keyframe_cover_when_no_image_url(monkeypatch):
    monkeypatch.delenv("PINTEREST_COVER_IMAGE_URL", raising=False)
    urlopen, calls = _make_urlopen(_happy_queue())
    _publisher(urlopen).publish(video_url=_VIDEO_URL, caption="cap", idempotency_key="k")
    source = _pin_body(calls)["media_source"]
    assert source["source_type"] == "video_id"
    assert "cover_image_url" not in source
    assert source["cover_image_key_frame_time"] == 1


def test_publish_polls_processing_then_succeeded():
    queue = [
        _Resp(_VIDEO_BYTES),
        _Resp(_register_payload()),
        _Resp(b"", status=204),
        _Resp({"status": "processing"}),
        _Resp({"status": "succeeded"}),
        _Resp({"id": _PIN_ID}, status=201),
    ]
    urlopen, calls = _make_urlopen(queue)

    import adapters.distribution.pinterest as _mod

    original_sleep = _mod.time.sleep
    _mod.time.sleep = lambda _: None
    try:
        result = _publisher(urlopen).publish(
            video_url=_VIDEO_URL, caption="cap", idempotency_key="k"
        )
    finally:
        _mod.time.sleep = original_sleep

    assert result == _PIN_ID
    assert len(calls) == 6


def test_media_failed_raises_publish_failed():
    urlopen, _ = _make_urlopen(_happy_queue(**{"3": _Resp({"status": "failed"})}))
    with pytest.raises(PublishFailed, match="failed"):
        _publisher(urlopen).publish(video_url=_VIDEO_URL, caption="c", idempotency_key="k")


def test_register_api_error_raises_runtime_error():
    err = urllib.error.HTTPError(
        "https://api.pinterest.com/v5/media",
        400,
        "bad",
        hdrs=None,
        fp=BytesIO(b'{"code":1,"message":"bad"}'),
    )
    urlopen, _ = _make_urlopen([_Resp(_VIDEO_BYTES), err])
    with pytest.raises(RuntimeError, match="400"):
        _publisher(urlopen).publish(video_url=_VIDEO_URL, caption="c", idempotency_key="k")


def test_non_raising_4xx_still_errors():
    urlopen, _ = _make_urlopen(_happy_queue(**{"1": _Resp({"error": "nope"}, status=403)}))
    with pytest.raises(RuntimeError, match="403"):
        _publisher(urlopen).publish(video_url=_VIDEO_URL, caption="c", idempotency_key="k")


def test_bearer_token_on_api_not_on_upload_or_download():
    urlopen, calls = _make_urlopen(_happy_queue())
    _publisher(urlopen).publish(video_url=_VIDEO_URL, caption="c", idempotency_key="k")

    download, register, upload, poll, pin = calls
    assert download[2].get_header("Authorization") is None
    assert upload[2].get_header("Authorization") is None
    for method, url, req, _timeout in (register, poll, pin):
        assert req.get_header("Authorization") == f"Bearer {_TOKEN}", f"{method} {url}"


def test_every_request_sets_a_timeout():
    urlopen, calls = _make_urlopen(_happy_queue())
    _publisher(urlopen).publish(video_url=_VIDEO_URL, caption="c", idempotency_key="k")
    assert calls, "no HTTP calls captured"
    for method, url, _req, timeout in calls:
        assert timeout is not None, f"{method} {url} has no timeout"


def test_http_video_url_rejected():
    urlopen, calls = _make_urlopen([])
    with pytest.raises(RuntimeError, match="https"):
        _publisher(urlopen).publish(
            video_url="http://example.com/v.mp4", caption="c", idempotency_key="k"
        )
    assert calls == []


def test_empty_download_raises():
    urlopen, _ = _make_urlopen([_Resp(b"")])
    with pytest.raises(RuntimeError, match="empty"):
        _publisher(urlopen).publish(video_url=_VIDEO_URL, caption="c", idempotency_key="k")


def test_register_missing_upload_url_raises():
    urlopen, _ = _make_urlopen([
        _Resp(_VIDEO_BYTES),
        _Resp({"media_id": _MEDIA_ID, "media_type": "video"}),
    ])
    with pytest.raises(RuntimeError, match="upload_url"):
        _publisher(urlopen).publish(video_url=_VIDEO_URL, caption="c", idempotency_key="k")


def test_pin_create_missing_id_raises():
    urlopen, _ = _make_urlopen(_happy_queue(**{"4": _Resp({"board_id": _BOARD_ID}, status=201)}))
    with pytest.raises(RuntimeError, match="no id"):
        _publisher(urlopen).publish(video_url=_VIDEO_URL, caption="c", idempotency_key="k")


def test_constructor_is_keyword_only():
    with pytest.raises(TypeError):
        PinterestPublisher(_TOKEN, _BOARD_ID)  # type: ignore[misc]


def test_cover_image_url_from_env(monkeypatch):
    monkeypatch.setenv("PINTEREST_COVER_IMAGE_URL", "https://cdn.example.com/still.jpg")
    urlopen, calls = _make_urlopen(_happy_queue())
    _publisher(urlopen).publish(video_url=_VIDEO_URL, caption="c", idempotency_key="k")
    assert _pin_body(calls)["media_source"]["cover_image_url"] == "https://cdn.example.com/still.jpg"
