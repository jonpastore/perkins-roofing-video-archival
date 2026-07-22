"""Mocked-HTTP tests for adapters/search_indexing.py (adapters/ are coverage-omitted)."""
import json

import pytest

import adapters.search_indexing as SI
from app.models import Base, PlatformConfig, PlatformSessionLocal, engine


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


class _MockResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)


# ── status() / _enabled() ────────────────────────────────────────────────────

def test_enabled_defaults_true_with_no_env_or_db_override(monkeypatch):
    monkeypatch.delenv("SEARCH_INDEXING_ENABLED", raising=False)
    assert SI._enabled() is True


def test_enabled_false_via_env(monkeypatch):
    monkeypatch.setenv("SEARCH_INDEXING_ENABLED", "false")
    assert SI._enabled() is False


def test_enabled_db_override_wins_over_env(monkeypatch):
    monkeypatch.setenv("SEARCH_INDEXING_ENABLED", "true")
    with PlatformSessionLocal() as db:
        db.merge(PlatformConfig(key="SEARCH_INDEXING_ENABLED", value="false"))
        db.commit()
    assert SI._enabled() is False


def test_status_reports_provider_config(monkeypatch):
    monkeypatch.setenv("INDEXNOW_KEY", "abc123")
    monkeypatch.delenv("GOOGLE_INDEXING_CREDENTIALS", raising=False)
    st = SI.status()
    assert st.indexnow_configured is True
    assert st.google_configured is False


# ── submit_indexnow ───────────────────────────────────────────────────────────

def test_submit_indexnow_missing_key(monkeypatch):
    monkeypatch.delenv("INDEXNOW_KEY", raising=False)
    result = SI.submit_indexnow(["https://perkinsroofing.net/a/"])
    assert result == {"ok": False, "error": "INDEXNOW_KEY not configured"}


def test_submit_indexnow_no_urls(monkeypatch):
    monkeypatch.setenv("INDEXNOW_KEY", "key1")
    assert SI.submit_indexnow([]) == {"ok": False, "error": "no urls"}


def test_submit_indexnow_success_posts_expected_payload(monkeypatch):
    monkeypatch.setenv("INDEXNOW_KEY", "key1")
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return _MockResponse(status_code=202)

    monkeypatch.setattr(SI.requests, "post", fake_post)
    result = SI.submit_indexnow(["https://perkinsroofing.net/a/", "https://perkinsroofing.net/b/"])

    assert result == {"ok": True, "status": 202, "error": None}
    assert calls[0][0] == SI._INDEXNOW_ENDPOINT
    assert calls[0][1] == {
        "host": "perkinsroofing.net",
        "key": "key1",
        "keyLocation": "https://perkinsroofing.net/key1.txt",
        "urlList": ["https://perkinsroofing.net/a/", "https://perkinsroofing.net/b/"],
    }


def test_submit_indexnow_key_rejected(monkeypatch):
    monkeypatch.setenv("INDEXNOW_KEY", "key1")
    monkeypatch.setattr(SI.requests, "post", lambda *a, **k: _MockResponse(status_code=422, text="bad key"))
    result = SI.submit_indexnow(["https://perkinsroofing.net/a/"])
    assert result["ok"] is False
    assert result["status"] == 422


def test_submit_indexnow_network_error(monkeypatch):
    monkeypatch.setenv("INDEXNOW_KEY", "key1")

    def raise_err(*a, **k):
        raise SI.requests.RequestException("timeout")

    monkeypatch.setattr(SI.requests, "post", raise_err)
    result = SI.submit_indexnow(["https://perkinsroofing.net/a/"])
    assert result == {"ok": False, "error": "timeout"}


# ── submit_google_indexing ──────────────────────────────────────────────────

def test_submit_google_indexing_missing_creds(monkeypatch):
    monkeypatch.delenv("GOOGLE_INDEXING_CREDENTIALS", raising=False)
    results = SI.submit_google_indexing(["https://perkinsroofing.net/a/"])
    assert results == [{
        "ok": False, "url": "https://perkinsroofing.net/a/",
        "error": "GOOGLE_INDEXING_CREDENTIALS not configured",
    }]


def test_submit_google_indexing_auth_failure(monkeypatch):
    monkeypatch.setenv("GOOGLE_INDEXING_CREDENTIALS", "{}")

    def raise_auth(*a, **k):
        raise RuntimeError("bad key")

    monkeypatch.setattr(SI, "_google_access_token", raise_auth)
    results = SI.submit_google_indexing(["https://perkinsroofing.net/a/"])
    assert results[0]["ok"] is False
    assert "auth failed" in results[0]["error"]


def test_submit_google_indexing_success_one_call_per_url(monkeypatch):
    monkeypatch.setenv("GOOGLE_INDEXING_CREDENTIALS", "{}")
    monkeypatch.setattr(SI, "_google_access_token", lambda: "tok")
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append((url, headers, json))
        return _MockResponse(status_code=200, text='{"ok": true}')

    monkeypatch.setattr(SI.requests, "post", fake_post)
    urls = ["https://perkinsroofing.net/a/", "https://perkinsroofing.net/b/"]
    results = SI.submit_google_indexing(urls)

    assert len(calls) == 2
    assert all(r["ok"] for r in results)
    assert calls[0][1]["Authorization"] == "Bearer tok"
    assert calls[0][2] == {"url": urls[0], "type": "URL_UPDATED"}


def test_submit_google_indexing_partial_failure(monkeypatch):
    monkeypatch.setenv("GOOGLE_INDEXING_CREDENTIALS", "{}")
    monkeypatch.setattr(SI, "_google_access_token", lambda: "tok")
    responses = [_MockResponse(status_code=200, text="{}"), _MockResponse(status_code=429, text="rate limited")]

    def fake_post(*a, **k):
        return responses.pop(0)

    monkeypatch.setattr(SI.requests, "post", fake_post)
    results = SI.submit_google_indexing(["https://perkinsroofing.net/a/", "https://perkinsroofing.net/b/"])
    assert results[0]["ok"] is True
    assert results[1]["ok"] is False
    assert results[1]["status"] == 429


def test_submit_google_indexing_network_error(monkeypatch):
    monkeypatch.setenv("GOOGLE_INDEXING_CREDENTIALS", "{}")
    monkeypatch.setattr(SI, "_google_access_token", lambda: "tok")

    def raise_err(*a, **k):
        raise SI.requests.RequestException("down")

    monkeypatch.setattr(SI.requests, "post", raise_err)
    results = SI.submit_google_indexing(["https://perkinsroofing.net/a/"])
    assert results == [{"ok": False, "url": "https://perkinsroofing.net/a/", "error": "down"}]


# ── submit_urls (orchestration + gate) ──────────────────────────────────────

def test_submit_urls_skips_when_disabled(monkeypatch):
    monkeypatch.setenv("SEARCH_INDEXING_ENABLED", "false")
    result = SI.submit_urls(["https://perkinsroofing.net/a/"])
    assert result == {"skipped": "disabled"}


def test_submit_urls_skips_when_no_urls(monkeypatch):
    monkeypatch.setenv("SEARCH_INDEXING_ENABLED", "true")
    assert SI.submit_urls([]) == {"skipped": "no_urls"}


def test_submit_urls_reports_not_configured_for_missing_providers(monkeypatch):
    monkeypatch.setenv("SEARCH_INDEXING_ENABLED", "true")
    monkeypatch.delenv("INDEXNOW_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_INDEXING_CREDENTIALS", raising=False)
    result = SI.submit_urls(["https://perkinsroofing.net/a/"])
    assert result["indexnow"] == {"ok": False, "error": "not configured"}
    assert result["google"] == [{"ok": False, "error": "not configured"}]


def test_submit_urls_calls_both_providers_when_configured(monkeypatch):
    monkeypatch.setenv("SEARCH_INDEXING_ENABLED", "true")
    monkeypatch.setenv("INDEXNOW_KEY", "key1")
    monkeypatch.setenv("GOOGLE_INDEXING_CREDENTIALS", "{}")
    monkeypatch.setattr(SI, "submit_indexnow", lambda urls: {"ok": True, "status": 202, "error": None})
    monkeypatch.setattr(SI, "submit_google_indexing", lambda urls, notification_type="URL_UPDATED": [{"ok": True}])

    result = SI.submit_urls(["https://perkinsroofing.net/a/"])
    assert result["indexnow"]["ok"] is True
    assert result["google"] == [{"ok": True}]
