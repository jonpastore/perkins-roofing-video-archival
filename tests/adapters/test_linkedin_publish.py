"""Mocked-HTTP tests for adapters.distribution.linkedin — no live network."""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO

import pytest

from adapters.distribution.linkedin import LinkedInPublisher

_TOKEN = "li_test_token_do_not_leak"
_AUTHOR = "urn:li:organization:12345"
_ASSET = "urn:li:digitalmediaAsset:C5500AQGxxx"
_UPLOAD = "https://api.linkedin.com/mediaUpload/C5500AQGxxx"
_VIDEO = "https://example.com/reel.mp4"
_POST_ID = "urn:li:share:999"


class _Resp:
    def __init__(self, *, headers=None, body=b"", status=200):
        self.headers = headers or {}
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _register_body():
    return {
        "value": {
            "uploadMechanism": {
                "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest": {
                    "uploadUrl": _UPLOAD,
                    "headers": {},
                }
            },
            "asset": _ASSET,
        }
    }


def _publisher(urlopen) -> LinkedInPublisher:
    return LinkedInPublisher(access_token=_TOKEN, author_urn=_AUTHOR, urlopen=urlopen)


def _happy_open(calls):
    def _open(req, timeout=0):
        calls.append((req, timeout))
        url = req.full_url
        method = req.get_method()
        if _VIDEO in url:
            assert method == "GET"
            return _Resp(body=b"mp4bytes")
        if "action=registerUpload" in url:
            assert method == "POST"
            return _Resp(body=json.dumps(_register_body()).encode())
        if "mediaUpload" in url:
            assert method == "PUT"
            return _Resp(body=b"")
        if "ugcPosts" in url:
            assert method == "POST"
            return _Resp(headers={"X-RestLi-Id": _POST_ID}, body=b"")
        raise AssertionError(f"unexpected {method} {url}")

    return _open


def _http_error(url, code, body=b""):
    return urllib.error.HTTPError(url, code, "err", hdrs=None, fp=BytesIO(body))


def test_publish_happy_path():
    calls = []
    pub = _publisher(_happy_open(calls))
    result = pub.publish(video_url=_VIDEO, caption="Roof repair tips", idempotency_key="series-1-part-0")

    assert result == _POST_ID
    assert len(calls) == 4

    download, register, upload, create = (req for req, _ in calls)
    assert download.full_url == _VIDEO
    assert "Authorization" not in download.headers
    assert download.get_header("Authorization") is None

    assert "action=registerUpload" in register.full_url
    assert register.get_header("Authorization") == f"Bearer {_TOKEN}"
    assert register.get_header("X-restli-protocol-version") == "2.0.0"
    reg_body = json.loads(register.data.decode())
    assert reg_body["registerUploadRequest"]["owner"] == _AUTHOR
    assert "feedshare-video" in reg_body["registerUploadRequest"]["recipes"][0]

    assert upload.full_url == _UPLOAD
    assert upload.data == b"mp4bytes"
    assert upload.get_header("Authorization") == f"Bearer {_TOKEN}"

    assert create.full_url.endswith("/ugcPosts")
    create_body = json.loads(create.data.decode())
    assert create_body["author"] == _AUTHOR
    share = create_body["specificContent"]["com.linkedin.ugc.ShareContent"]
    assert share["shareCommentary"]["text"] == "Roof repair tips"
    assert share["shareMediaCategory"] == "VIDEO"
    assert share["media"][0]["status"] == "READY"
    assert share["media"][0]["media"] == _ASSET


def test_every_request_sets_a_timeout():
    calls = []
    _publisher(_happy_open(calls)).publish(
        video_url=_VIDEO,
        caption="c",
        idempotency_key="k",
    )
    assert calls
    for _req, timeout in calls:
        assert timeout is not None


def test_missing_access_token_raises():
    with pytest.raises(RuntimeError, match="access token"):
        LinkedInPublisher(access_token="", author_urn=_AUTHOR)


def test_missing_author_urn_raises():
    pub = LinkedInPublisher(access_token=_TOKEN, author_urn="", urlopen=lambda *a, **k: _Resp())
    with pytest.raises(RuntimeError, match="author_urn"):
        pub.publish(video_url=_VIDEO, caption="c", idempotency_key="k")


def test_empty_video_bytes_raises():
    def _open(req, timeout=0):
        if _VIDEO in req.full_url:
            return _Resp(body=b"")
        raise AssertionError("should stop after download")

    pub = _publisher(_open)
    with pytest.raises(RuntimeError, match="video bytes"):
        pub.publish(video_url=_VIDEO, caption="c", idempotency_key="k")


def test_register_missing_upload_url_raises():
    def _open(req, timeout=0):
        if _VIDEO in req.full_url:
            return _Resp(body=b"mp4")
        return _Resp(body=json.dumps({"value": {"asset": _ASSET}}).encode())

    pub = _publisher(_open)
    with pytest.raises(RuntimeError, match="uploadUrl or asset"):
        pub.publish(video_url=_VIDEO, caption="c", idempotency_key="k")


def test_ugc_posts_missing_id_raises():
    def _open(req, timeout=0):
        url = req.full_url
        if _VIDEO in url:
            return _Resp(body=b"mp4")
        if "registerUpload" in url:
            return _Resp(body=json.dumps(_register_body()).encode())
        if "mediaUpload" in url:
            return _Resp()
        return _Resp(headers={}, body=b"")

    pub = _publisher(_open)
    with pytest.raises(RuntimeError, match="no post id"):
        pub.publish(video_url=_VIDEO, caption="c", idempotency_key="k")


@pytest.mark.parametrize(
    "step,code",
    [
        ("download", 404),
        ("register", 401),
        ("upload", 500),
        ("create", 403),
    ],
)
def test_http_errors_raise_runtime_error(step, code):
    def _open(req, timeout=0):
        url = req.full_url
        if step == "download" and _VIDEO in url:
            raise _http_error(url, code, b'{"error":"gone"}')
        if _VIDEO in url:
            return _Resp(body=b"mp4")
        if step == "register" and "registerUpload" in url:
            raise _http_error(url, code, b'{"message":"unauthorized"}')
        if "registerUpload" in url:
            return _Resp(body=json.dumps(_register_body()).encode())
        if step == "upload" and "mediaUpload" in url:
            raise _http_error(url, code, b"upload failed")
        if "mediaUpload" in url:
            return _Resp()
        if step == "create":
            raise _http_error(url, code, b'{"message":"forbidden"}')
        raise AssertionError(url)

    pub = _publisher(_open)
    with pytest.raises(RuntimeError, match=str(code)) as excinfo:
        pub.publish(video_url=_VIDEO, caption="c", idempotency_key="k")
    assert _TOKEN not in str(excinfo.value)


def test_http_error_body_does_not_include_token():
    def _open(req, timeout=0):
        raise _http_error(req.full_url, 400, b'{"message":"bad request"}')

    pub = _publisher(_open)
    with pytest.raises(RuntimeError, match="400") as excinfo:
        pub.publish(video_url=_VIDEO, caption="c", idempotency_key="k")
    msg = str(excinfo.value)
    assert _TOKEN not in msg
    assert "Authorization" not in msg
    assert "bad request" in msg
