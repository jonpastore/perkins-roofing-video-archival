"""Mocked-HTTP tests for adapters/meta_ig.py."""
import pytest

from adapters.meta_ig import ContainerError, IgPublisher, RateLimited

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MockResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = str(json_data)

    def json(self):
        return self._json


def _make_session(*responses):
    """Return a session stub that returns *responses* in order (get/post agnostic)."""
    calls = []
    _queue = list(responses)

    class _Sess:
        def get(self, url, **kwargs):
            calls.append(("GET", url, kwargs))
            return _queue.pop(0)

        def post(self, url, **kwargs):
            calls.append(("POST", url, kwargs))
            return _queue.pop(0)

    return _Sess(), calls


# ---------------------------------------------------------------------------
# Happy-path: container → FINISHED → publish returns id
# ---------------------------------------------------------------------------

def test_publish_happy_path():
    """Full 3-call success sequence."""
    rate_limit_resp = _MockResponse({"data": [{"quota_usage": 5}]})
    create_resp = _MockResponse({"id": "container_abc"})
    poll_finished = _MockResponse({"status_code": "FINISHED", "id": "container_abc"})
    publish_resp = _MockResponse({"id": "ig_media_999"})

    sess, calls = _make_session(rate_limit_resp, create_resp, poll_finished, publish_resp)
    pub = IgPublisher(ig_user_id="user1", access_token="tok", session=sess)

    result = pub.publish(
        video_url="https://example.com/reel.mp4",
        caption="Test caption",
        idempotency_key="series-1-part-0",
    )

    assert result == "ig_media_999"
    assert len(calls) == 4
    # First call: rate limit check
    assert calls[0][0] == "GET"
    assert "content_publishing_limit" in calls[0][1]
    # Second call: create container
    assert calls[1][0] == "POST"
    assert calls[1][1].endswith("/media")
    # Third call: poll status
    assert calls[2][0] == "GET"
    assert "container_abc" in calls[2][1]
    # Fourth call: publish
    assert calls[3][0] == "POST"
    assert "media_publish" in calls[3][1]


def test_publish_polls_in_progress_then_finished():
    """IN_PROGRESS on first poll, FINISHED on second — returns media id."""
    rate_limit_resp = _MockResponse({"data": [{"quota_usage": 0}]})
    create_resp = _MockResponse({"id": "cont_xyz"})
    poll_in_progress = _MockResponse({"status_code": "IN_PROGRESS"})
    poll_finished = _MockResponse({"status_code": "FINISHED"})
    publish_resp = _MockResponse({"id": "ig_media_111"})

    sess, calls = _make_session(
        rate_limit_resp, create_resp, poll_in_progress, poll_finished, publish_resp
    )

    # Patch sleep to avoid waiting in tests
    import adapters.meta_ig as _mod
    original_sleep = _mod.time.sleep
    _mod.time.sleep = lambda _: None
    try:
        pub = IgPublisher(ig_user_id="u", access_token="t", session=sess)
        result = pub.publish(
            video_url="https://x.com/v.mp4",
            caption="cap",
            idempotency_key="k",
        )
    finally:
        _mod.time.sleep = original_sleep

    assert result == "ig_media_111"
    # calls: rate_limit, create, poll×2, publish = 5
    assert len(calls) == 5


# ---------------------------------------------------------------------------
# ERROR state aborts — ContainerError raised
# ---------------------------------------------------------------------------

def test_publish_container_error_state_raises():
    rate_limit_resp = _MockResponse({"data": [{"quota_usage": 0}]})
    create_resp = _MockResponse({"id": "cont_err"})
    poll_error = _MockResponse({"status_code": "ERROR"})

    sess, _ = _make_session(rate_limit_resp, create_resp, poll_error)
    pub = IgPublisher(ig_user_id="u", access_token="t", session=sess)

    with pytest.raises(ContainerError, match="ERROR"):
        pub.publish(video_url="https://x.com/v.mp4", caption="c", idempotency_key="k")


def test_publish_container_expired_state_raises():
    rate_limit_resp = _MockResponse({"data": [{"quota_usage": 0}]})
    create_resp = _MockResponse({"id": "cont_exp"})
    poll_expired = _MockResponse({"status_code": "EXPIRED"})

    sess, _ = _make_session(rate_limit_resp, create_resp, poll_expired)
    pub = IgPublisher(ig_user_id="u", access_token="t", session=sess)

    with pytest.raises(ContainerError, match="EXPIRED"):
        pub.publish(video_url="https://x.com/v.mp4", caption="c", idempotency_key="k")


# ---------------------------------------------------------------------------
# Rate-limit path
# ---------------------------------------------------------------------------

def test_publish_rate_limited_raises():
    rate_limit_resp = _MockResponse({"data": [{"quota_usage": 50}]})

    sess, _ = _make_session(rate_limit_resp)
    pub = IgPublisher(ig_user_id="u", access_token="t", session=sess)

    with pytest.raises(RateLimited, match="quota"):
        pub.publish(video_url="https://x.com/v.mp4", caption="c", idempotency_key="k")


def test_publish_rate_limit_no_data_field_does_not_raise():
    """If quota endpoint returns no data array, treat as under limit."""
    rate_limit_resp = _MockResponse({"data": []})
    create_resp = _MockResponse({"id": "cont_ok"})
    poll_finished = _MockResponse({"status_code": "FINISHED"})
    publish_resp = _MockResponse({"id": "ig_media_ok"})

    sess, _ = _make_session(rate_limit_resp, create_resp, poll_finished, publish_resp)
    pub = IgPublisher(ig_user_id="u", access_token="t", session=sess)

    result = pub.publish(video_url="https://x.com/v.mp4", caption="c", idempotency_key="k")
    assert result == "ig_media_ok"


# ---------------------------------------------------------------------------
# Non-2xx API errors surface as RuntimeError
# ---------------------------------------------------------------------------

def test_api_error_raises_runtime_error():
    rate_limit_resp = _MockResponse({"data": [{"quota_usage": 0}]})
    error_resp = _MockResponse({"error": "bad"}, status_code=400)

    sess, _ = _make_session(rate_limit_resp, error_resp)
    pub = IgPublisher(ig_user_id="u", access_token="t", session=sess)

    with pytest.raises(RuntimeError, match="400"):
        pub.publish(video_url="https://x.com/v.mp4", caption="c", idempotency_key="k")


# ---------------------------------------------------------------------------
# Env-var credential loading
# ---------------------------------------------------------------------------

def test_env_var_credentials_loaded(monkeypatch):
    monkeypatch.setenv("IG_USER_ID", "env_user")
    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "env_token")

    rate_limit_resp = _MockResponse({"data": [{"quota_usage": 0}]})
    create_resp = _MockResponse({"id": "cont_env"})
    poll_finished = _MockResponse({"status_code": "FINISHED"})
    publish_resp = _MockResponse({"id": "ig_env_media"})

    sess, calls = _make_session(rate_limit_resp, create_resp, poll_finished, publish_resp)
    pub = IgPublisher(session=sess)  # no explicit creds — reads from env

    result = pub.publish(video_url="https://x.com/v.mp4", caption="c", idempotency_key="k")
    assert result == "ig_env_media"
    # Verify the token was passed in the rate-limit GET params
    get_params = calls[0][2].get("params", {})
    assert get_params.get("access_token") == "env_token"
