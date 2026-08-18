"""YouTube Shorts publisher — download then upload_short (no live network)."""
from adapters.distribution.youtube_shorts import YouTubeShortsPublisher


class _Resp:
    def __init__(self, body=b"mp4"):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_publish_returns_video_id(monkeypatch):
    monkeypatch.setattr(
        "adapters.distribution.youtube_shorts.upload_short",
        lambda **k: {"post_id": "abc123XYZ01", "platform": "youtube_shorts", "url": "u"},
    )
    pub = YouTubeShortsPublisher(access_token="tok", urlopen=lambda *a, **k: _Resp())
    assert pub.publish(video_url="https://ex/v.mp4", caption="Hi", idempotency_key="k") == "abc123XYZ01"


def test_empty_token_raises():
    try:
        YouTubeShortsPublisher(access_token="")
        assert False
    except RuntimeError:
        pass
