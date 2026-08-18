"""Ops issue classification, persist/diff, and alert email."""
from __future__ import annotations

from core.ops_issues import (
    collect_issues,
    new_issue_keys,
    persist_and_diff,
    render_ops_html,
    send_ops_alert,
)


def test_collect_issues_orders_errors_first():
    issues = collect_issues({
        "youtube": {
            "blocked": True,
            "failed_tabs": ["streams"],
            "unarchived_ids": [],
            "ingest_errors": [{
                "video_id": "abc",
                "error": "no archive_uri for abc; run archive_job before STT",
            }],
        },
        "scheduled_jobs": {
            "ok": True,
            "schedulers": [
                {"name": "companycam-sync", "attention": "failed",
                 "message": "varchar(1000)"},
                {"name": "knowify-sync", "attention": "paused"},
            ],
            "run_jobs": [
                {"name": "companycam-sync", "attention": "failed"},
                {"name": "article", "attention": "failed", "last_execution": "article-1"},
            ],
        },
        "cloud_spend": {"ok": False, "error": "HTTP 403", "hint": "grant viewer"},
        "profit_below_minimum": [{"id": 9}],
        "scans_latest": [{"scan_type": "portfolio", "error": "lock held"}],
    })
    keys = [i["key"] for i in issues]
    assert keys[0].startswith("youtube.blocked") or issues[0]["severity"] == "error"
    assert all(
        issues[i]["severity"] <= issues[i + 1]["severity"]
        or (issues[i]["severity"] == "error" or issues[i + 1]["severity"] == "warning")
        for i in range(len(issues) - 1)
    )
    assert "job.failed:companycam-sync" in keys
    assert keys.count("job.failed:companycam-sync") == 1
    assert "job.paused:knowify-sync" not in keys
    assert "job.on_demand:article" in keys
    assert "spend.unavailable" in keys
    assert "profit.below" in keys
    assert "scan.error:portfolio" in keys
    assert "ingest.stale:abc" in keys
    cam = next(i for i in issues if i["key"] == "job.failed:companycam-sync")
    assert "public_api/v1" in cam["fix"] or "OOM" in cam["fix"]


def test_collect_issues_streams_only_is_silent():
    issues = collect_issues({
        "youtube": {"blocked": False, "pull_ok": True, "failed_tabs": ["streams"]},
        "scheduled_jobs": {"ok": True, "schedulers": [], "run_jobs": []},
        "cloud_spend": {"ok": True},
    })
    assert issues == []


def test_collect_issues_videos_tab_is_error():
    issues = collect_issues({
        "youtube": {"blocked": False, "pull_ok": False, "failed_tabs": ["videos"]},
        "scheduled_jobs": {"ok": True, "schedulers": [], "run_jobs": []},
        "cloud_spend": {"ok": True},
    })
    assert issues[0]["severity"] == "error"
    assert "videos" in issues[0]["title"]


def test_collect_issues_stale_on_demand_is_silent():
    issues = collect_issues({
        "scheduled_jobs": {
            "ok": True,
            "schedulers": [],
            "run_jobs": [{
                "name": "article", "attention": "failed",
                "completed": "2026-07-09T07:58:57Z",
            }],
        },
        "youtube": {"blocked": False, "pull_ok": True},
        "cloud_spend": {"ok": True},
    })
    assert not any(i["key"].startswith("job.on_demand:article") for i in issues)


def test_collect_issues_jobs_unavailable():
    issues = collect_issues({
        "scheduled_jobs": {"ok": False, "error": "HTTP 403", "hint": "grant viewer"},
        "youtube": {"blocked": False, "pull_ok": True},
        "cloud_spend": {"ok": True},
    })
    assert issues[0]["key"] == "jobs.unavailable"
    assert "grant viewer" in issues[0]["fix"]


def test_collect_issues_incomplete_and_waiting():
    issues = collect_issues({
        "youtube": {
            "blocked": False, "incomplete": True, "failed_tabs": ["videos"],
            "unarchived_ids": ["xyz"],
            "ingest_errors": [{
                "video_id": "xyz",
                "error": "no archive_uri for xyz; run archive_job before STT",
            }],
        },
        "scheduled_jobs": {"ok": True, "schedulers": [], "run_jobs": []},
        "cloud_spend": {"ok": True},
    })
    keys = [i["key"] for i in issues]
    assert "youtube.incomplete" in keys
    assert "youtube.unarchived" in keys
    assert "ingest.no_archive:xyz" in keys


def test_new_issue_keys():
    current = [{"key": "a"}, {"key": "b"}]
    assert new_issue_keys(current, ["a"]) == ["b"]
    assert new_issue_keys(current, ["a", "b"]) == []


def test_render_ops_html_includes_fix_and_logo():
    html = render_ops_html(
        [{"severity": "error", "title": "Archive failed", "detail": "exit 1",
          "fix": "Check WireGuard."}],
        intro="New error.",
    )
    assert "Needs action" in html
    assert "Check WireGuard." in html
    assert "perkins-logo.png" in html
    assert "How to fix" in html


def test_render_ops_html_empty():
    html = render_ops_html([], intro="cleared")
    assert "No errors or warnings" in html


def test_send_ops_alert_skips_empty_and_blocked(monkeypatch):
    assert send_ops_alert([]) == []
    sent = []

    class _D:
        def __init__(self, allowed):
            self.allowed = allowed

    import adapters.resend as resend
    monkeypatch.setattr(resend, "send", lambda **k: sent.append(k) or "mid")
    monkeypatch.setattr(
        "core.email_gate.decide",
        lambda to: _D(to == "jon@degenito.ai"),
    )
    ids = send_ops_alert([{
        "key": "x", "severity": "error", "title": "t", "detail": "d", "fix": "f",
    }], tenant_id=1)
    assert ids == ["mid"]
    assert "error(s)" in sent[0]["subject"]
    assert sent[0]["send_type"] == "ops_alert"


class _Row:
    def __init__(self):
        self.last_error = "[]"
        self.status = "unconfigured"
        self.last_checked = None
        self.tenant_id = None
        self.integration = "ops_alerts"
        self.consecutive_failures = 0


class _Q:
    def __init__(self, row):
        self._row = row

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._row


class _Db:
    def __init__(self, row):
        self.row = row
        self.added = []

    def query(self, model):
        return _Q(self.row)

    def add(self, row):
        self.added.append(row)

    def flush(self):
        return None


def test_persist_and_diff_only_returns_new():
    row = _Row()
    row.last_error = '["job.paused:knowify-sync"]'
    db = _Db(row)
    issues = [
        {"key": "job.paused:knowify-sync", "severity": "warning",
         "title": "paused", "detail": "", "fix": ""},
        {"key": "job.failed:archive", "severity": "error",
         "title": "archive", "detail": "", "fix": ""},
    ]
    fresh = persist_and_diff(db, issues)
    assert [i["key"] for i in fresh] == ["job.failed:archive"]
    assert row.status == "broken"
    assert "job.failed:archive" in row.last_error


def test_persist_and_diff_creates_row():
    class _Empty(_Db):
        def query(self, model):
            return _Q(None)

    db = _Empty(None)
    fresh = persist_and_diff(db, [{
        "key": "spend.unavailable", "severity": "warning",
        "title": "spend", "detail": "", "fix": "",
    }])
    assert len(fresh) == 1
    assert db.added
    assert db.added[-1].status == "healthy"


def test_persist_and_diff_bad_json():
    row = _Row()
    row.last_error = "not-json"
    fresh = persist_and_diff(_Db(row), [{
        "key": "a", "severity": "warning", "title": "t", "detail": "", "fix": "",
    }])
    assert [i["key"] for i in fresh] == ["a"]
