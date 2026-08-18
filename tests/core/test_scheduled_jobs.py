"""Scheduler / Cloud Run job classification for the digest."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.error import HTTPError

from core import scheduled_jobs as sj


class _Resp:
    def __init__(self, raw: bytes):
        self._raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._raw


def test_classify_scheduler_paused():
    out = sj.classify_scheduler({
        "name": "projects/p/locations/us-central1/jobs/knowify-sync",
        "state": "PAUSED",
        "schedule": "0 8-18 * * *",
        "timeZone": "America/New_York",
    }, now=datetime(2026, 8, 17, tzinfo=timezone.utc))
    assert out["attention"] == "paused"
    assert out["name"] == "knowify-sync"


def test_classify_scheduler_failed():
    out = sj.classify_scheduler({
        "name": "archive",
        "state": "ENABLED",
        "schedule": "30 7 * * *",
        "status": {
            "code": 13,
            "message": "HTTP 500",
            "lastAttemptTime": "2026-08-17T11:30:00Z",
        },
    }, now=datetime(2026, 8, 17, 12, tzinfo=timezone.utc))
    assert out["attention"] == "failed"


def test_classify_scheduler_missed():
    out = sj.classify_scheduler({
        "name": "enumerate-channel",
        "state": "ENABLED",
        "schedule": "0 7 * * *",
        "status": {"code": 0, "lastAttemptTime": "2026-08-01T11:00:00Z"},
    }, now=datetime(2026, 8, 17, 12, tzinfo=timezone.utc))
    assert out["attention"] == "not_running"


def test_classify_scheduler_empty_status_is_ok():
    out = sj.classify_scheduler({
        "name": "enumerate-channel",
        "state": "ENABLED",
        "schedule": "0 7 * * *",
        "status": {},
    }, now=datetime(2026, 8, 17, 12, tzinfo=timezone.utc))
    assert out["attention"] == "ok"


def test_classify_scheduler_ok():
    out = sj.classify_scheduler({
        "name": "promote-scheduled-content",
        "state": "ENABLED",
        "schedule": "*/15 * * * *",
        "status": {"code": 0, "lastAttemptTime": "2026-08-17T11:45:00Z"},
    }, now=datetime(2026, 8, 17, 12, tzinfo=timezone.utc))
    assert out["attention"] == "ok"


def test_stale_hours_weekly():
    assert sj.stale_hours_for("weekly-digest", "0 8 * * 1") == sj.WEEKLY_STALE_HOURS
    assert sj.stale_hours_for("crawl-comments", "0 */2 * * *") == sj.FREQUENT_STALE_HOURS
    assert sj.stale_hours_for("archive", "30 7 * * *") == sj.DAILY_STALE_HOURS


def test_classify_run_job_failed():
    out = sj.classify_run_job(
        {"name": "projects/p/locations/us-central1/jobs/archive"},
        {
            "name": "archive-abc",
            "succeededCount": 0,
            "failedCount": 1,
            "conditions": [{"type": "Completed", "state": "CONDITION_FAILED",
                            "message": "exit 1"}],
        },
    )
    assert out["attention"] == "failed"
    assert out["last_execution"] == "archive-abc"


def test_classify_run_job_ok():
    out = sj.classify_run_job(
        {"name": "enumerate-channel"},
        {"name": "enumerate-channel-xyz", "succeededCount": 1, "failedCount": 0,
         "conditions": [{"type": "Completed", "state": "CONDITION_SUCCEEDED"}]},
    )
    assert out["attention"] == "ok"


def test_classify_run_job_never_ran_scheduled():
    out = sj.classify_run_job({"name": "archive"}, None)
    assert out["attention"] == "not_running"


def test_classify_run_job_on_demand_idle_ok():
    out = sj.classify_run_job({"name": "render"}, None)
    assert out["attention"] == "ok"


def test_overlay_copies_run_failure_onto_scheduler():
    schedulers = [sj.classify_scheduler({
        "name": "archive", "state": "ENABLED", "schedule": "30 7 * * *", "status": {},
    }, now=datetime(2026, 8, 17, 12, tzinfo=timezone.utc))]
    runs = [sj.classify_run_job(
        {"name": "archive"},
        {"name": "archive-x", "succeededCount": 0, "failedCount": 1,
         "createTime": "2026-08-17T11:30:00Z",
         "conditions": [{"type": "Completed", "state": "CONDITION_FAILED", "message": "exit 1"}]},
        now=datetime(2026, 8, 17, 12, tzinfo=timezone.utc),
    )]
    sj._overlay_scheduler_from_runs(schedulers, runs)
    assert schedulers[0]["attention"] == "failed"
    assert schedulers[0]["last_attempt"]


def test_overlay_paused_swallows_stale_run():
    schedulers = [sj.classify_scheduler({
        "name": "knowify-sync", "state": "PAUSED", "schedule": "0 8-18 * * *",
    }, now=datetime(2026, 8, 17, tzinfo=timezone.utc))]
    runs = [sj.classify_run_job(
        {"name": "knowify-sync"},
        {"name": "old", "succeededCount": 1, "failedCount": 0,
         "createTime": "2026-07-23T12:00:00Z",
         "conditions": [{"type": "Completed", "state": "CONDITION_SUCCEEDED"}]},
        now=datetime(2026, 8, 17, tzinfo=timezone.utc),
    )]
    assert runs[0]["attention"] == "not_running"
    sj._overlay_scheduler_from_runs(schedulers, runs)
    assert runs[0]["attention"] == "paused"


def test_fetch_scheduled_jobs_403(monkeypatch):
    monkeypatch.setattr(sj, "_adc_token", lambda: "t")

    def _boom(req, timeout=12):
        raise HTTPError(req.full_url, 403, "forbidden", hdrs=None, fp=None)

    monkeypatch.setattr(sj.urllib.request, "urlopen", _boom)
    out = sj.fetch_scheduled_jobs()
    assert out["ok"] is False
    assert "403" in out["error"]
    assert "viewer" in out["hint"]


def test_fetch_scheduled_jobs_parses(monkeypatch):
    monkeypatch.setattr(sj, "_adc_token", lambda: "t")

    def _open(req, timeout=12):
        url = req.full_url
        if "cloudscheduler" in url:
            body = {"jobs": [{
                "name": "projects/p/locations/us-central1/jobs/archive",
                "state": "ENABLED",
                "schedule": "30 7 * * *",
                "timeZone": "America/New_York",
                "status": {"code": 0, "lastAttemptTime": "2026-08-17T11:30:00Z"},
            }]}
        elif "/executions" in url:
            body = {"executions": [{
                "name": "archive-1", "succeededCount": 1, "failedCount": 0,
                "conditions": [{"type": "Completed", "state": "CONDITION_SUCCEEDED"}],
            }]}
        else:
            body = {"jobs": [{
                "name": "projects/p/locations/us-central1/jobs/archive",
            }]}
        return _Resp(json.dumps(body).encode())

    monkeypatch.setattr(sj.urllib.request, "urlopen", _open)
    out = sj.fetch_scheduled_jobs()
    assert out["ok"] is True
    assert out["schedulers"][0]["name"] == "archive"
    assert out["run_jobs"][0]["attention"] == "ok"


def test_parse_ts_bad():
    assert sj._parse_ts(None) is None
    assert sj._parse_ts("not-a-date") is None


def test_adc_token_refreshes(monkeypatch):
    class _Creds:
        token = "abc"

        def refresh(self, _req):
            self.token = "xyz"

    import google.auth
    import google.auth.transport.requests

    monkeypatch.setattr(google.auth, "default", lambda scopes=None: (_Creds(), None))
    monkeypatch.setattr(google.auth.transport.requests, "Request", lambda: None)
    assert sj._adc_token() == "xyz"


def test_fetch_import_error(monkeypatch):
    def _boom():
        raise ImportError("no")

    monkeypatch.setattr(sj, "_adc_token", _boom)
    out = sj.fetch_scheduled_jobs()
    assert "google-auth" in out["error"]


def test_fetch_urlopen_timeout(monkeypatch):
    monkeypatch.setattr(sj, "_adc_token", lambda: "t")

    def _fail(*a, **k):
        raise TimeoutError("timeout")

    monkeypatch.setattr(sj.urllib.request, "urlopen", _fail)
    out = sj.fetch_scheduled_jobs()
    assert out["ok"] is False
    assert "timeout" in out["error"]


def test_fetch_execution_fallback(monkeypatch):
    monkeypatch.setattr(sj, "_adc_token", lambda: "t")

    def _open(req, timeout=12):
        url = req.full_url
        if "cloudscheduler" in url:
            body = {"jobs": []}
        elif "/executions" in url:
            raise TimeoutError("exec timeout")
        else:
            body = {"jobs": [{
                "name": "projects/p/locations/us-central1/jobs/archive",
                "latestCreatedExecution": {
                    "name": "archive-fallback", "succeededCount": 1, "failedCount": 0,
                    "createTime": "2026-08-17T11:30:00Z",
                    "conditions": [{"type": "Completed", "state": "CONDITION_SUCCEEDED"}],
                },
            }]}
        return _Resp(json.dumps(body).encode())

    monkeypatch.setattr(sj.urllib.request, "urlopen", _open)
    out = sj.fetch_scheduled_jobs()
    assert out["ok"] is True
    assert out["run_jobs"][0]["last_execution"] == "archive-fallback"


def test_overlay_skips_unmatched_scheduler():
    schedulers = [sj.classify_scheduler({
        "name": "promote-scheduled-content", "state": "ENABLED",
        "schedule": "*/15 * * * *", "status": {"code": 0, "lastAttemptTime": "2026-08-17T11:45:00Z"},
    }, now=datetime(2026, 8, 17, 12, tzinfo=timezone.utc))]
    sj._overlay_scheduler_from_runs(schedulers, [])
    assert schedulers[0]["attention"] == "ok"


def test_fetch_adc_fail(monkeypatch):
    def _fail():
        raise RuntimeError("no adc")

    monkeypatch.setattr(sj, "_adc_token", _fail)
    out = sj.fetch_scheduled_jobs()
    assert out["ok"] is False
    assert "adc" in out["error"]
