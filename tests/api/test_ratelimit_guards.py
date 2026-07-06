"""Behavioral tests for the single-flight + cooldown guards on expensive endpoints.

Tests:
  - concurrent call returns 409
  - too-soon call returns 429
  - check-new: lock-only (no cooldown) — concurrent → 409, immediate retry → 200
  - happy path still works after reset
"""
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.routes.comments import router as comments_router, _crawl_guard
from api.routes.archive import router as archive_router, _backfill_guard, _poll_kpis_guard, _check_new_guard

AUTH = {"Authorization": "Bearer tok"}


def _make_comments_client(role: str = "admin") -> TestClient:
    set_verifier(lambda token: {"uid": "u1", "email": "t@x.com", "role": role})
    app = FastAPI()
    app.include_router(comments_router)
    return TestClient(app, raise_server_exceptions=False)


def _make_archive_client(role: str = "admin") -> TestClient:
    set_verifier(lambda token: {"uid": "u1", "email": "t@x.com", "role": role})
    app = FastAPI()
    app.include_router(archive_router)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def reset_all_guards():
    """Wipe all guard state before every test in this module."""
    _crawl_guard._reset_for_testing()
    _backfill_guard._reset_for_testing()
    _poll_kpis_guard._reset_for_testing()
    _check_new_guard._reset_for_testing()
    yield


# ---------------------------------------------------------------------------
# POST /comments/crawl — lock guard (409) + cooldown (429)
# ---------------------------------------------------------------------------

class TestCrawlGuard:
    def test_concurrent_call_returns_409(self, monkeypatch):
        """Simulate a crawl already in-flight: manually hold the lock, then call."""
        import jobs.crawl_comments as jmod
        monkeypatch.setattr(jmod, "run", lambda limit, max_drafts=25: {
            "videos_processed": 1, "comments_upserted": 0, "flagged": 0, "drafted": 0, "errors": 0,
        })

        # Hold the lock to simulate an in-flight operation.
        _crawl_guard._lock.acquire()
        try:
            client = _make_comments_client()
            resp = client.post("/comments/crawl", json={"limit": 1}, headers=AUTH)
            assert resp.status_code == 409
            assert "already running" in resp.json()["detail"]
        finally:
            _crawl_guard._lock.release()

    def test_too_soon_returns_429(self, monkeypatch):
        """Simulate a recently-finished crawl: set last_finished_at to now."""
        import jobs.crawl_comments as jmod
        monkeypatch.setattr(jmod, "run", lambda limit, max_drafts=25: {
            "videos_processed": 0, "comments_upserted": 0, "flagged": 0, "drafted": 0, "errors": 0,
        })

        # Mark as just-finished.
        with _crawl_guard._ts_lock:
            _crawl_guard._last_finished_at = time.monotonic()

        client = _make_comments_client()
        resp = client.post("/comments/crawl", json={"limit": 1}, headers=AUTH)
        assert resp.status_code == 429
        assert "cooldown" in resp.json()["detail"]

    def test_happy_path_after_reset(self, monkeypatch):
        """Normal call succeeds when guard is clean."""
        import jobs.crawl_comments as jmod
        monkeypatch.setattr(jmod, "run", lambda limit, max_drafts=25: {
            "videos_processed": 1, "comments_upserted": 0, "flagged": 0, "drafted": 0, "errors": 0,
        })
        client = _make_comments_client()
        resp = client.post("/comments/crawl", json={"limit": 1}, headers=AUTH)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /archive/backfill — lock guard (409) + cooldown (429)
# ---------------------------------------------------------------------------

class TestBackfillGuard:
    def test_concurrent_call_returns_409(self, monkeypatch):
        import jobs.backfill_archive as jmod
        monkeypatch.setattr(jmod, "run", lambda **kw: {"added": 0, "checked": 0, "failed_tabs": []})

        _backfill_guard._lock.acquire()
        try:
            client = _make_archive_client()
            resp = client.post("/archive/backfill", headers=AUTH)
            assert resp.status_code == 409
            assert "already running" in resp.json()["detail"]
        finally:
            _backfill_guard._lock.release()

    def test_too_soon_returns_429(self, monkeypatch):
        import jobs.backfill_archive as jmod
        monkeypatch.setattr(jmod, "run", lambda **kw: {"added": 0, "checked": 0, "failed_tabs": []})

        with _backfill_guard._ts_lock:
            _backfill_guard._last_finished_at = time.monotonic()

        client = _make_archive_client()
        resp = client.post("/archive/backfill", headers=AUTH)
        assert resp.status_code == 429
        assert "cooldown" in resp.json()["detail"]

    def test_happy_path_after_reset(self, monkeypatch):
        import jobs.backfill_archive as jmod
        monkeypatch.setattr(jmod, "run", lambda **kw: {"added": 2, "checked": 5, "failed_tabs": []})
        client = _make_archive_client()
        resp = client.post("/archive/backfill", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["added"] == 2


# ---------------------------------------------------------------------------
# POST /archive/poll-kpis — lock guard (409) + cooldown (429)
# ---------------------------------------------------------------------------

class TestPollKpisGuard:
    def test_concurrent_call_returns_409(self, monkeypatch):
        import jobs.poll_archive_kpis as jmod
        monkeypatch.setattr(jmod, "run", lambda limit=None: {"polled": 0})

        _poll_kpis_guard._lock.acquire()
        try:
            client = _make_archive_client()
            resp = client.post("/archive/poll-kpis", headers=AUTH)
            assert resp.status_code == 409
            assert "already running" in resp.json()["detail"]
        finally:
            _poll_kpis_guard._lock.release()

    def test_too_soon_returns_429(self, monkeypatch):
        import jobs.poll_archive_kpis as jmod
        monkeypatch.setattr(jmod, "run", lambda limit=None: {"polled": 0})

        with _poll_kpis_guard._ts_lock:
            _poll_kpis_guard._last_finished_at = time.monotonic()

        client = _make_archive_client()
        resp = client.post("/archive/poll-kpis", headers=AUTH)
        assert resp.status_code == 429
        assert "cooldown" in resp.json()["detail"]

    def test_happy_path_after_reset(self, monkeypatch):
        import jobs.poll_archive_kpis as jmod
        monkeypatch.setattr(jmod, "run", lambda limit=None: {"polled": 3})
        client = _make_archive_client()
        resp = client.post("/archive/poll-kpis", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["polled"] == 3


# ---------------------------------------------------------------------------
# GET /archive/check-new — lock guard only (no cooldown)
# ---------------------------------------------------------------------------

class TestCheckNewGuard:
    def test_concurrent_call_returns_409(self, monkeypatch):
        import jobs.backfill_archive as jmod
        monkeypatch.setattr(jmod, "check_new", lambda **kw: {"new_count": 0, "last_pulled_at": None})

        _check_new_guard._lock.acquire()
        try:
            client = _make_archive_client()
            resp = client.get("/archive/check-new", headers=AUTH)
            assert resp.status_code == 409
            assert "already running" in resp.json()["detail"]
        finally:
            _check_new_guard._lock.release()

    def test_no_cooldown_second_call_succeeds(self, monkeypatch):
        """check-new has no cooldown — a second call right after the first must succeed."""
        import jobs.backfill_archive as jmod
        monkeypatch.setattr(jmod, "check_new", lambda **kw: {"new_count": 1, "last_pulled_at": None})

        client = _make_archive_client()
        # First call
        resp1 = client.get("/archive/check-new", headers=AUTH)
        assert resp1.status_code == 200
        # Immediately second call — should NOT get 429 (no cooldown)
        resp2 = client.get("/archive/check-new", headers=AUTH)
        assert resp2.status_code == 200

    def test_happy_path_after_reset(self, monkeypatch):
        import jobs.backfill_archive as jmod
        monkeypatch.setattr(jmod, "check_new", lambda **kw: {"new_count": 4, "last_pulled_at": "2024-01-01"})
        client = _make_archive_client()
        resp = client.get("/archive/check-new", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["new_count"] == 4
