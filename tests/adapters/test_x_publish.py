"""Mocked-urlopen tests for adapters/distribution/x.py. No live network."""

from __future__ import annotations

import io
import json
import pathlib
import urllib.error

import pytest

from adapters.distribution import x as X
from adapters.distribution.x import PublishFailed, XPublisher

VIDEO_URL = "https://storage.googleapis.com/bucket/reel.mp4"
TOKEN = "secret-token-xyz"
TWEET_ID = "1940000000000000000"
MEDIA_ID = "1880028106020515840"
VIDEO = b"mp4-bytes-here"


class _Resp:
    def __init__(self, *, body=b"", status=200):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _json(payload: dict) -> _Resp:
    return _Resp(body=json.dumps(payload).encode())


def _form_field(data: bytes | None, name: str) -> str | None:
    if not data:
        return None
    marker = f'name="{name}"'.encode()
    i = data.find(marker)
    if i < 0:
        return None
    rest = data[i + len(marker) :]
    sep = rest.find(b"\r\n\r\n")
    if sep < 0:
        return None
    val = rest[sep + 4 :]
    end = val.find(b"\r\n")
    return val[:end].decode() if end >= 0 else val.decode()


def _command(req) -> str | None:
    if req.get_method() == "GET" and "command=STATUS" in req.full_url:
        return "STATUS"
    return _form_field(req.data, "command")


class _Scripted:
    """urlopen stand-in: records calls and returns scripted responses by command."""

    def __init__(self, script: dict[str, list[_Resp | Exception]]):
        self.script = script
        self.calls: list[tuple] = []

    def __call__(self, req, timeout=None):
        self.calls.append((req, timeout))
        if req.full_url == VIDEO_URL or req.full_url.startswith(VIDEO_URL):
            key = "DOWNLOAD"
        elif req.full_url.startswith(X.TWEETS):
            key = "TWEET"
        else:
            key = _command(req) or "UNKNOWN"
        queue = self.script[key]
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _happy_script(**overrides) -> dict[str, list]:
    script = {
        "DOWNLOAD": [_Resp(body=VIDEO)],
        "INIT": [_json({"data": {"id": MEDIA_ID}})],
        "APPEND": [_Resp(body=b"")],
        "FINALIZE": [_json({"data": {"id": MEDIA_ID}})],
        "TWEET": [_json({"data": {"id": TWEET_ID, "text": "cap"}})],
    }
    script.update(overrides)
    return script


def _publish(script, **kwargs):
    opener = _Scripted(script)
    pub = XPublisher(access_token=kwargs.pop("access_token", TOKEN), urlopen=opener)
    result = pub.publish(
        video_url=VIDEO_URL,
        caption=kwargs.pop("caption", "Roof tip"),
        idempotency_key=kwargs.pop("idempotency_key", "series-1-part-0"),
    )
    return result, opener


def test_publish_happy_path():
    result, opener = _publish(_happy_script())
    assert result == TWEET_ID
    commands = [_command(req) for req, _ in opener.calls if req.full_url != VIDEO_URL]
    assert commands == ["INIT", "APPEND", "FINALIZE", None]  # tweet has no command
    init_req = next(r for r, _ in opener.calls if _command(r) == "INIT")
    assert _form_field(init_req.data, "media_type") == "video/mp4"
    assert _form_field(init_req.data, "media_category") == "tweet_video"
    assert _form_field(init_req.data, "total_bytes") == str(len(VIDEO))
    tweet_req = next(r for r, _ in opener.calls if r.full_url.startswith(X.TWEETS))
    body = json.loads(tweet_req.data.decode())
    assert body["text"] == "Roof tip"
    assert body["media"]["media_ids"] == [MEDIA_ID]


def test_publish_polls_pending_then_succeeded(monkeypatch):
    monkeypatch.setattr(X.time, "sleep", lambda _: None)
    script = _happy_script(
        FINALIZE=[
            _json(
                {
                    "data": {
                        "id": MEDIA_ID,
                        "processing_info": {"state": "pending", "check_after_secs": 1},
                    }
                }
            )
        ],
        STATUS=[
            _json({"data": {"processing_info": {"state": "in_progress", "check_after_secs": 1}}}),
            _json({"data": {"processing_info": {"state": "succeeded"}}}),
        ],
    )
    result, opener = _publish(script)
    assert result == TWEET_ID
    assert sum(1 for r, _ in opener.calls if _command(r) == "STATUS") == 2


def test_publish_processing_failed_raises(monkeypatch):
    monkeypatch.setattr(X.time, "sleep", lambda _: None)
    script = _happy_script(
        FINALIZE=[
            _json(
                {
                    "data": {
                        "id": MEDIA_ID,
                        "processing_info": {"state": "pending", "check_after_secs": 1},
                    }
                }
            )
        ],
        STATUS=[
            _json(
                {
                    "data": {
                        "processing_info": {
                            "state": "failed",
                            "error": {"message": "InvalidMedia"},
                        }
                    }
                }
            )
        ],
    )
    with pytest.raises(PublishFailed, match="InvalidMedia"):
        _publish(script)


def test_finalize_failed_raises_without_status():
    script = _happy_script(
        FINALIZE=[
            _json(
                {
                    "data": {
                        "id": MEDIA_ID,
                        "processing_info": {"state": "failed", "error": {"message": "bad encode"}},
                    }
                }
            )
        ],
    )
    with pytest.raises(PublishFailed, match="bad encode"):
        _publish(script)


def test_chunked_append_sends_each_segment(monkeypatch):
    monkeypatch.setattr(X, "CHUNK_SIZE", 4)
    video = b"abcdefghij"  # 10 bytes → 3 chunks
    script = _happy_script(
        DOWNLOAD=[_Resp(body=video)],
        APPEND=[_Resp(body=b""), _Resp(body=b""), _Resp(body=b"")],
    )
    _, opener = _publish(script)
    appends = [r for r, _ in opener.calls if _command(r) == "APPEND"]
    assert [_form_field(r.data, "segment_index") for r in appends] == ["0", "1", "2"]
    assert all(_form_field(r.data, "media_id") == MEDIA_ID for r in appends)
    assert all(b'name="media"' in (r.data or b"") for r in appends)


def test_init_http_error_raises_runtime_error():
    err = urllib.error.HTTPError(
        X.MEDIA_UPLOAD,
        400,
        "bad",
        hdrs=None,
        fp=io.BytesIO(b'{"error":"nope"}'),
    )
    script = _happy_script(INIT=[err])
    with pytest.raises(RuntimeError, match="400"):
        _publish(script)


def test_download_http_error_raises():
    err = urllib.error.HTTPError(VIDEO_URL, 403, "no", hdrs=None, fp=io.BytesIO(b""))
    script = _happy_script(DOWNLOAD=[err])
    with pytest.raises(RuntimeError, match="403"):
        _publish(script)


def test_empty_video_raises():
    script = _happy_script(DOWNLOAD=[_Resp(body=b"")])
    with pytest.raises(RuntimeError, match="video bytes"):
        _publish(script)


def test_empty_access_token_raises():
    with pytest.raises(RuntimeError, match="access token"):
        XPublisher(access_token="")


def test_missing_media_id_raises():
    script = _happy_script(INIT=[_json({"data": {}})])
    with pytest.raises(RuntimeError, match="no media id"):
        _publish(script)


def test_missing_tweet_id_raises():
    script = _happy_script(TWEET=[_json({"data": {}})])
    with pytest.raises(RuntimeError, match="no tweet id"):
        _publish(script)


def test_poll_timeout_raises(monkeypatch):
    monkeypatch.setattr(X.time, "sleep", lambda _: None)
    monkeypatch.setattr(X, "POLL_MAX", 2)
    pending = _json({"data": {"processing_info": {"state": "pending", "check_after_secs": 1}}})
    script = _happy_script(
        FINALIZE=[pending],
        STATUS=[pending, pending],
    )
    with pytest.raises(RuntimeError, match="did not reach succeeded"):
        _publish(script)


def test_bearer_on_api_not_on_download():
    _, opener = _publish(_happy_script())
    download = next(r for r, _ in opener.calls if r.full_url == VIDEO_URL)
    assert download.get_header("Authorization") is None
    api_reqs = [r for r, _ in opener.calls if r.full_url != VIDEO_URL]
    assert api_reqs
    for req in api_reqs:
        assert req.get_header("Authorization") == f"Bearer {TOKEN}"


def test_token_not_in_http_error_message():
    err = urllib.error.HTTPError(
        X.MEDIA_UPLOAD,
        401,
        "no",
        hdrs=None,
        fp=io.BytesIO(b'{"title":"Unauthorized"}'),
    )
    script = _happy_script(INIT=[err])
    with pytest.raises(RuntimeError) as excinfo:
        _publish(script)
    assert TOKEN not in str(excinfo.value)
    assert TOKEN not in repr(excinfo.value)


def test_every_request_sets_a_timeout():
    _, opener = _publish(_happy_script())
    assert opener.calls
    for req, timeout in opener.calls:
        assert timeout is not None, f"{req.get_method()} {req.full_url} has no timeout"


def test_no_scaffold_or_mock_ids_in_module():
    src = pathlib.Path(X.__file__).read_text()
    assert "SCAFFOLD" not in src
    assert "x_mock_" not in src
