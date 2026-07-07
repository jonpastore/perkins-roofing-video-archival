"""Mocked-HTTP tests for adapters/tiktok.py."""
import pytest

from adapters.tiktok import PublishFailed, TikTokPublisher, refresh_access_token

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
    """Return a session stub that returns *responses* in order (post-only)."""
    calls = []
    _queue = list(responses)

    class _Sess:
        def post(self, url, **kwargs):
            calls.append(("POST", url, kwargs))
            return _queue.pop(0)

    return _Sess(), calls


# ---------------------------------------------------------------------------
# Happy-path: init → poll PUBLISH_COMPLETE → returns publish_id
# ---------------------------------------------------------------------------

def test_publish_happy_path():
    """PULL_FROM_URL init + poll to PUBLISH_COMPLETE."""
    init_resp = _MockResponse({"data": {"publish_id": "pub_abc123"}})
    poll_resp = _MockResponse({"data": {"status": "PUBLISH_COMPLETE", "publicly_available_post_id": ["tt_999"]}})

    sess, calls = _make_session(init_resp, poll_resp)
    pub = TikTokPublisher(access_token="tok", open_id="oid", session=sess)

    result = pub.publish(
        video_url="https://example.com/reel.mp4",
        caption="Roof repair tips",
        idempotency_key="series-1-part-0",
    )

    assert result == "pub_abc123"
    assert len(calls) == 2

    # Init call
    assert "init" in calls[0][1]
    init_body = calls[0][2].get("json", {})
    assert init_body["source_info"]["source"] == "PULL_FROM_URL"
    assert init_body["source_info"]["video_url"] == "https://example.com/reel.mp4"
    assert init_body["post_info"]["title"] == "Roof repair tips"

    # Poll call
    assert "status/fetch" in calls[1][1]
    poll_body = calls[1][2].get("json", {})
    assert poll_body["publish_id"] == "pub_abc123"


def test_publish_polls_processing_then_complete():
    """PROCESSING_DOWNLOAD on first poll, PUBLISH_COMPLETE on second."""
    init_resp = _MockResponse({"data": {"publish_id": "pub_poll"}})
    poll_processing = _MockResponse({"data": {"status": "PROCESSING_DOWNLOAD"}})
    poll_complete = _MockResponse({"data": {"status": "PUBLISH_COMPLETE"}})

    sess, calls = _make_session(init_resp, poll_processing, poll_complete)

    import adapters.tiktok as _mod
    original_sleep = _mod.time.sleep
    _mod.time.sleep = lambda _: None
    try:
        pub = TikTokPublisher(access_token="tok", open_id="oid", session=sess)
        result = pub.publish(
            video_url="https://x.com/v.mp4",
            caption="cap",
            idempotency_key="k",
        )
    finally:
        _mod.time.sleep = original_sleep

    assert result == "pub_poll"
    assert len(calls) == 3  # init + 2 polls


# ---------------------------------------------------------------------------
# FAILED status raises PublishFailed
# ---------------------------------------------------------------------------

def test_publish_failed_status_raises():
    init_resp = _MockResponse({"data": {"publish_id": "pub_fail"}})
    fail_reason = "UNAUDITED_CLIENT_CAN_ONLY_POST_TO_PRIVATE_ACCOUNTS"
    poll_failed = _MockResponse({"data": {"status": "FAILED", "fail_reason": fail_reason}})

    sess, _ = _make_session(init_resp, poll_failed)
    pub = TikTokPublisher(access_token="tok", open_id="oid", session=sess)

    with pytest.raises(PublishFailed, match="UNAUDITED_CLIENT"):
        pub.publish(video_url="https://x.com/v.mp4", caption="c", idempotency_key="k")


def test_publish_failed_status_with_unknown_reason():
    init_resp = _MockResponse({"data": {"publish_id": "pub_fail2"}})
    poll_failed = _MockResponse({"data": {"status": "FAILED"}})  # no fail_reason key

    sess, _ = _make_session(init_resp, poll_failed)
    pub = TikTokPublisher(access_token="tok", open_id="oid", session=sess)

    with pytest.raises(PublishFailed, match="unknown"):
        pub.publish(video_url="https://x.com/v.mp4", caption="c", idempotency_key="k")


# ---------------------------------------------------------------------------
# Non-2xx API errors surface as RuntimeError
# ---------------------------------------------------------------------------

def test_init_api_error_raises_runtime_error():
    error_resp = _MockResponse({"error": {"code": 4000000}}, status_code=400)

    sess, _ = _make_session(error_resp)
    pub = TikTokPublisher(access_token="tok", open_id="oid", session=sess)

    with pytest.raises(RuntimeError, match="400"):
        pub.publish(video_url="https://x.com/v.mp4", caption="c", idempotency_key="k")


def test_poll_api_error_raises_runtime_error():
    init_resp = _MockResponse({"data": {"publish_id": "pub_err"}})
    error_resp = _MockResponse({"error": "internal"}, status_code=500)

    sess, _ = _make_session(init_resp, error_resp)
    pub = TikTokPublisher(access_token="tok", open_id="oid", session=sess)

    with pytest.raises(RuntimeError, match="500"):
        pub.publish(video_url="https://x.com/v.mp4", caption="c", idempotency_key="k")


# ---------------------------------------------------------------------------
# Auth header is sent correctly
# ---------------------------------------------------------------------------

def test_bearer_token_in_auth_header():
    init_resp = _MockResponse({"data": {"publish_id": "pub_auth"}})
    poll_resp = _MockResponse({"data": {"status": "PUBLISH_COMPLETE"}})

    sess, calls = _make_session(init_resp, poll_resp)
    pub = TikTokPublisher(access_token="my_bearer_token", open_id="oid", session=sess)
    pub.publish(video_url="https://x.com/v.mp4", caption="c", idempotency_key="k")

    for _, _, kwargs in calls:
        headers = kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer my_bearer_token"


# ---------------------------------------------------------------------------
# Env-var credential loading
# ---------------------------------------------------------------------------

def test_env_var_credentials_loaded(monkeypatch):
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "env_tok")
    monkeypatch.setenv("TIKTOK_OPEN_ID", "env_oid")

    init_resp = _MockResponse({"data": {"publish_id": "pub_env"}})
    poll_resp = _MockResponse({"data": {"status": "PUBLISH_COMPLETE"}})

    sess, calls = _make_session(init_resp, poll_resp)
    pub = TikTokPublisher(session=sess)  # reads from env

    result = pub.publish(video_url="https://x.com/v.mp4", caption="c", idempotency_key="k")
    assert result == "pub_env"


# ---------------------------------------------------------------------------
# refresh_access_token
# ---------------------------------------------------------------------------

def test_refresh_access_token_calls_correct_endpoint():
    refresh_resp = _MockResponse({
        "access_token": "new_tok",
        "refresh_token": "new_ref",
        "expires_in": 86400,
    })

    sess, calls = _make_session(refresh_resp)
    result = refresh_access_token(
        client_key="ck",
        client_secret="cs",
        refresh_token="rt",
        session=sess,
    )

    assert result["access_token"] == "new_tok"
    assert len(calls) == 1
    assert "/v2/oauth/token/" in calls[0][1]
    body = calls[0][2].get("data", {})
    assert body["grant_type"] == "refresh_token"
    assert body["refresh_token"] == "rt"
    assert body["client_key"] == "ck"
    assert body["client_secret"] == "cs"


def test_refresh_access_token_error_raises():
    error_resp = _MockResponse({"error": "invalid_grant"}, status_code=401)

    sess, _ = _make_session(error_resp)
    with pytest.raises(RuntimeError, match="401"):
        refresh_access_token(
            client_key="ck", client_secret="cs", refresh_token="rt", session=sess
        )


def test_refresh_access_token_reads_env_vars(monkeypatch):
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "env_ck")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "env_cs")
    monkeypatch.setenv("TIKTOK_REFRESH_TOKEN", "env_rt")

    refresh_resp = _MockResponse({"access_token": "env_new_tok"})
    sess, calls = _make_session(refresh_resp)

    result = refresh_access_token(session=sess)
    assert result["access_token"] == "env_new_tok"
    body = calls[0][2].get("data", {})
    assert body["client_key"] == "env_ck"
    assert body["refresh_token"] == "env_rt"


def test_every_request_sets_a_timeout():
    """Regression: the social cron must never hang — every HTTP call passes a timeout."""
    sess, calls = _make_session(
        _MockResponse({"data": {"publish_id": "p1"}}),
        _MockResponse({"data": {"status": "PUBLISH_COMPLETE"}}),
    )
    TikTokPublisher(access_token="t", open_id="o", session=sess).publish(
        video_url="https://x/r.mp4", caption="c", idempotency_key="k")
    assert calls, "no HTTP calls captured"
    for method, url, kwargs in calls:
        assert kwargs.get("timeout") is not None, f"{method} {url} has no timeout"
