import json
import urllib.error

from core import youtube_upload as U


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


def test_short_metadata_adds_hash():
    meta = U.short_metadata("A clip")
    assert meta["snippet"]["title"] == "A clip"
    assert "#Shorts" in meta["snippet"]["description"]
    assert meta["status"]["privacyStatus"] == "public"


def test_short_metadata_keeps_existing_hash():
    meta = U.short_metadata("Hello\n#Shorts")
    assert meta["snippet"]["title"] == "Hello"
    assert meta["snippet"]["description"] == "Hello\n#Shorts"


def test_upload_requires_token_and_bytes():
    try:
        U.upload_short(video_bytes=b"x", caption="c", access_token="")
        assert False
    except RuntimeError:
        pass
    try:
        U.upload_short(video_bytes=b"", caption="c", access_token="tok")
        assert False
    except RuntimeError:
        pass


def test_upload_happy_path():
    calls = []

    def _open(req, timeout=0):
        calls.append((req.get_method(), req.full_url))
        if "uploadType=resumable" in req.full_url:
            return _Resp(headers={"Location": "https://upload.example/s"})
        return _Resp(body=json.dumps({"id": "abc123XYZ01"}).encode())

    out = U.upload_short(video_bytes=b"mp4", caption="Hi", access_token="tok", urlopen=_open)
    assert out["post_id"] == "abc123XYZ01"
    assert out["url"].endswith("/shorts/abc123XYZ01")
    assert calls[0][0] == "POST" and calls[1][0] == "PUT"


def test_upload_missing_session():
    def _open(req, timeout=0):
        return _Resp(headers={})

    try:
        U.upload_short(video_bytes=b"mp4", caption="Hi", access_token="tok", urlopen=_open)
        assert False
    except RuntimeError:
        pass


def test_upload_http_error():
    def _open(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 403, "no", hdrs=None, fp=None)

    try:
        U.upload_short(video_bytes=b"mp4", caption="Hi", access_token="tok", urlopen=_open)
        assert False
    except RuntimeError:
        pass


def test_upload_missing_id():
    def _open(req, timeout=0):
        if "uploadType=resumable" in req.full_url:
            return _Resp(headers={"Location": "https://upload.example/s"})
        return _Resp(body=b"{}")

    try:
        U.upload_short(video_bytes=b"mp4", caption="Hi", access_token="tok", urlopen=_open)
        assert False
    except RuntimeError:
        pass
