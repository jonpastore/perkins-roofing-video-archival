"""Weekly digest collects profit-below-floor quotes, queues, and pipeline."""
from __future__ import annotations

from datetime import datetime, timezone

from core.profit_alerts import has_profit_below_minimum
import pytest

import core.weekly_digest as wd
from core.weekly_digest import collect_digest, proposal_total, render_html, send_digest


@pytest.fixture(autouse=True)
def _mute_gcp(monkeypatch):
    monkeypatch.setattr(wd, "fetch_cloud_spend", lambda: {"ok": False, "error": "muted"})
    monkeypatch.setattr(wd, "fetch_scheduled_jobs", lambda: {"ok": False, "error": "muted", "jobs": []})
    monkeypatch.setattr(wd, "fetch_bot_block_logs", lambda: [])


class _Q:
    def __init__(self, rows=None):
        self._rows = rows or []

    def filter(self, *a, **k):
        return self

    def distinct(self):
        return self

    def all(self):
        return self._rows

    def count(self):
        return len(self._rows)


class _Db:
    def __init__(self, mapping):
        self.mapping = mapping

    def query(self, model):
        name = getattr(model, "__name__", str(model))
        for key, rows in self.mapping.items():
            if key in name:
                return _Q(rows)
        return _Q([])

    def rollback(self):
        return None


def test_has_profit_below_minimum_reads_warning():
    assert has_profit_below_minimum({"warnings": ["profit_below_minimum: $400"]})
    assert not has_profit_below_minimum({"warnings": ["daily_days_auto_filled: x"]})
    assert not has_profit_below_minimum({})


def test_proposal_total_reads_nested_or_flat():
    assert proposal_total({"project_totals": {"project_total": 12345}}) == 12345
    assert proposal_total({"project_total": "99.5"}) == 99.5
    assert proposal_total({}) == 0
    assert proposal_total(None) == 0


def test_render_html_lists_below_floor_quotes():
    html = render_html({
        "since": "2026-08-08",
        "until": "2026-08-15",
        "audit_count": 2,
        "by_action": {"proposal.send": 1},
        "by_actor": {"marco@perkinsroofing.net": 1},
        "estimates": 3,
        "quote_value": 12000,
        "customers_new": 2,
        "customer_names": ["Ada", "Ben"],
        "proposals_created": 1,
        "proposals_signed": 1,
        "signed_value": 8800,
        "signed_titles": ["Ada tile"],
        "queues": {
            "article_topics": 10,
            "reels": 1,
            "faqs": 4,
            "unused_videos": 2,
            "pending_video_approvals": 32,
            "scheduled_articles": 0,
            "scheduled_content": 0,
            "comment_drafts": 184,
        },
        "comments_new": 5,
        "cloud_spend": {"ok": True, "amount": 240, "currency": "USD", "display_name": "monthly"},
        "profit_below_minimum": [
            {"id": 9, "created_by": "marco@perkinsroofing.net",
             "roof_type": "13_tile", "profit": 400, "total": 5550},
        ],
    })
    assert "Profit under $2,500 (1)" in html
    assert "#9" in html
    assert "$400" in html
    assert "proposal.send" in html
    assert "Video approvals waiting" in html
    assert "32" in html
    assert "YouTube comments needing a reply" in html
    assert "184" in html
    assert "2 — Ada, Ben" in html
    assert "$8,800" in html
    assert "$240" in html
    assert "Needs attention" in html
    assert "Needs action" in html
    assert html.find("Needs action") < html.find("Needs attention")
    assert "How to fix" in html
    assert "perkins-logo.png" in html
    assert "<table" in html
    assert "What this means" in html


def test_render_html_includes_scans():
    html = render_html({
        "since": "2026-08-08",
        "until": "2026-08-15",
        "audit_count": 0,
        "by_action": {},
        "by_actor": {},
        "estimates": 0,
        "profit_below_minimum": [],
        "scan_runs": 7,
        "scans_latest": [{
            "scan_type": "portfolio",
            "ran_at": "2026-08-15T07:30:00",
            "ready_count": 2,
            "blocked_count": 11,
            "total": 13,
            "ready_slugs": ["evergrene-clubhouse", "bus-stop"],
            "blockers": {"client permission not recorded": 8, "no photos selected": 3},
        }],
        "cloud_spend": {"ok": False, "error": "HTTP 403"},
    })
    assert "portfolio" in html
    assert "2 ready" in html
    assert "evergrene-clubhouse" in html
    assert "8× client permission not recorded" in html
    assert "HTTP 403" in html
    assert "Portfolio scans (1)" in html


def test_render_html_explains_missing_scans():
    html = render_html({
        "since": "2026-08-08",
        "until": "2026-08-15",
        "scan_runs": 0,
        "scans_latest": [],
        "profit_below_minimum": [],
        "queues": {},
        "cloud_spend": {"ok": True, "note": "no budgets configured"},
    })
    assert "not persisted yet" in html


def test_collect_digest_finds_flagged_estimate():
    class _Est:
        id = 3
        created_by = "tim@perkinsroofing.net"
        branch = "jupiter"
        created_at = datetime(2026, 8, 14)
        result_json = {
            "profit_dollars": 400,
            "project_total": 5550,
            "roof_type": "3tab_shingle",
            "warnings": ["profit_below_minimum: profit $400.00 is under the $2,500 job minimum"],
        }

    class _Audit:
        action = "estimator.quote"
        actor_email = None
        occurred_at = datetime(2026, 8, 14)

    payload = collect_digest(
        _Db({"Estimate": [_Est()], "AuditLog": [_Audit()]}),
        now=datetime(2026, 8, 15),
    )
    assert payload["by_action"]["estimator.quote"] == 1
    assert payload["by_actor"]["(system)"] == 1
    assert payload["estimates"] == 1
    assert payload["quote_value"] == 5550
    assert len(payload["profit_below_minimum"]) == 1
    assert payload["profit_below_minimum"][0]["id"] == 3
    assert payload["scan_runs"] == 0
    assert payload["customers_new"] == 0
    assert payload["proposals_signed"] == 0
    assert "youtube" in payload
    assert payload["youtube"]["videos"] == 0
    assert payload["scheduled_jobs"]["ok"] is False


def test_collect_digest_includes_scan_reports():
    class _Scan:
        id = 1
        scan_type = "portfolio"
        tenant_id = 1
        ran_at = datetime(2026, 8, 14, 7, 30)
        payload = {"ready_count": 1, "blocked_count": 4, "total": 5,
                   "ready_slugs": ["clubhouse"], "blockers": {"no photos selected": 4}}

    payload = collect_digest(
        _Db({"ScanReport": [_Scan()]}),
        now=datetime(2026, 8, 15),
    )
    assert payload["scan_runs"] == 1
    assert payload["scans_latest"][0]["scan_type"] == "portfolio"
    assert payload["scans_latest"][0]["ready_count"] == 1


def test_collect_digest_counts_signed_proposals_and_customers():
    class _Cust:
        display_name = "Ada Roof"
        created_at = datetime(2026, 8, 14)

    class _Prop:
        title = "Ada tile reroof"
        status = "accepted"
        created_at = datetime(2026, 8, 14)
        accepted_at = datetime(2026, 8, 14)
        quote_snapshot = {"project_totals": {"project_total": 22000}}

    payload = collect_digest(
        _Db({"Customer": [_Cust()], "Proposal": [_Prop()]}),
        now=datetime(2026, 8, 15),
    )
    assert payload["customers_new"] == 1
    assert payload["customer_names"] == ["Ada Roof"]
    assert payload["proposals_signed"] == 1
    assert payload["signed_value"] == 22000


def test_proposal_total_skips_bad_values():
    assert proposal_total({"project_total": object(), "total": "nope"}) == 0


def test_collect_digest_strips_tzinfo():
    payload = collect_digest(_Db({}), now=datetime(2026, 8, 15, tzinfo=timezone.utc))
    assert payload["until"].startswith("2026-08-15")


def test_collect_digest_scan_query_failure():
    class _Boom(_Db):
        def query(self, model):
            name = getattr(model, "__name__", str(model))
            if "ScanReport" in name:
                raise RuntimeError("no table")
            return super().query(model)

    payload = collect_digest(_Boom({}), now=datetime(2026, 8, 15))
    assert payload["scan_runs"] == 0


def test_collect_digest_youtube_failure(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("yt down")

    monkeypatch.setattr(wd, "collect_youtube_health", _boom)
    payload = collect_digest(_Db({}), now=datetime(2026, 8, 15))
    assert payload["youtube"]["reasons"] == ["catalog query failed"]


def test_render_html_skips_youtube_scan_type():
    html = render_html({
        "scans_latest": [
            {"scan_type": "youtube_enumerate", "failed_tabs": ["streams"]},
            {"scan_type": "portfolio", "error": "lock held"},
        ],
        "scan_runs": 2,
        "profit_below_minimum": [],
        "queues": {},
        "cloud_spend": {"ok": True, "amount": 10, "currency": "USD", "display_name": "cap"},
        "scheduled_jobs": {"ok": True, "paused": [], "failed": [], "not_running": [],
                           "schedulers": [], "run_jobs": []},
    })
    assert "streams" not in html
    assert "lock held" in html
    assert "No failed or missed scheduled jobs" in html
    assert "$10" in html


def test_render_html_empty_youtube_and_incomplete():
    assert "no catalog snapshot" in render_html({
        "profit_below_minimum": [], "queues": {}, "cloud_spend": {"ok": True, "note": "x"},
    })
    html = render_html({
        "youtube": {"blocked": False, "pull_ok": False, "incomplete": True,
                    "failed_tabs": ["videos"], "reasons": []},
        "profit_below_minimum": [], "queues": {}, "cloud_spend": {"ok": True, "note": "x"},
    })
    assert "not blocked, but pull is not clean" in html
    assert "Enumerate marked incomplete" in html


def test_collect_digest_queue_failure():
    import core.weekly_digest as wd

    def _boom(_db):
        raise RuntimeError("counts failed")

    orig = wd.compute_suggestion_counts
    wd.compute_suggestion_counts = _boom
    try:
        payload = collect_digest(_Db({}), now=datetime(2026, 8, 15))
    finally:
        wd.compute_suggestion_counts = orig
    assert payload["queues"] == {}


def test_render_html_youtube_and_jobs():
    html = render_html({
        "youtube": {
            "blocked": True,
            "pull_ok": False,
            "videos": 870,
            "archived": 869,
            "unarchived": 1,
            "unavailable": 0,
            "newest_id": "eaNcmJLkd5g",
            "newest_title": "Clay vs Concrete",
            "newest_upload_date": "20260814",
            "newest_age_days": 3,
            "new_this_week": 1,
            "new_titles": ["Clay vs Concrete"],
            "failed_tabs": ["streams"],
            "bot_hits": 1,
            "unarchived_ids": ["abc"],
            "reasons": ["yt-dlp bot-check in 1 ingest error(s)"],
            "ingest_errors": [{"stage": "stt", "video_id": "abc",
                               "error": "Sign in to confirm you're not a bot"}],
            "job_runs": [{"name": "archive", "attention": "failed",
                          "last_execution": "archive-x"}],
            "recent_blocks": [{"timestamp": "2026-08-16T12:00:00Z",
                               "resource": "archive", "message": "bot-blocked"}],
        },
        "scheduled_jobs": {
            "ok": True,
            "paused": ["knowify-sync"],
            "failed": ["archive"],
            "not_running": ["weekly-digest"],
            "schedulers": [{
                "name": "archive", "state": "ENABLED", "schedule": "30 7 * * *",
                "time_zone": "America/New_York", "last_attempt": "2026-08-17T11:30:00",
                "attention": "failed", "message": "exit 1",
            }],
            "run_jobs": [{
                "name": "enumerate-channel", "last_execution": "enumerate-channel-1",
                "condition": "CONDITION_SUCCEEDED", "attention": "ok",
            }],
        },
        "profit_below_minimum": [],
        "queues": {},
        "cloud_spend": {"ok": True, "note": "n/a"},
        "scans_latest": [],
    })
    assert "BLOCKED — cannot pull from YouTube" in html
    assert "Clay vs Concrete" in html
    assert "failed tabs: streams" in html
    assert "FAILED: archive" in html
    assert "Paused (intentional): knowify-sync" in html
    assert "weekly-digest" in html
    assert "archive-x" in html
    assert "bot-blocked" in html


def test_render_html_explains_stale_archive_uri_errors():
    html = render_html({
        "youtube": {
            "blocked": False, "pull_ok": True, "videos": 2, "archived": 1,
            "unarchived": 1, "unarchived_ids": ["wait"],
            "ingest_errors": [
                {"stage": "transcript", "video_id": "done",
                 "error": "no archive_uri for done; run archive_job before STT"},
                {"stage": "transcript", "video_id": "wait",
                 "error": "no archive_uri for wait; run archive_job before STT"},
            ],
        },
        "profit_below_minimum": [], "queues": {},
        "cloud_spend": {"ok": True, "note": "n/a"},
    })
    assert "stale" in html
    assert "reset this transcript row" in html
    assert "still unarchived" in html


def test_render_html_jobs_unavailable():
    html = render_html({
        "scheduled_jobs": {"ok": False, "error": "HTTP 403", "hint": "grant viewer"},
        "youtube": {"blocked": False, "pull_ok": True, "videos": 1, "archived": 1,
                    "unarchived": 0, "new_this_week": 0},
        "profit_below_minimum": [],
        "queues": {},
        "cloud_spend": {"ok": True, "note": "n/a"},
    })
    assert "unavailable — HTTP 403" in html
    assert "pulling OK — not blocked" in html


def test_render_html_scan_error_and_spend_hint():
    html = render_html({
        "scans_latest": [{"scan_type": "portfolio", "error": "lock held"}],
        "scan_runs": 1,
        "profit_below_minimum": [],
        "cloud_spend": {"ok": False, "error": "HTTP 403", "hint": "grant viewer"},
        "queues": {},
    })
    assert "lock held" in html
    assert "grant viewer" in html


def test_render_html_logo_override():
    html = render_html({
        "profit_below_minimum": [], "queues": {},
        "cloud_spend": {"ok": True, "note": "x"},
    }, logo_url="https://cdn.example.com/logo.png")
    assert 'src="https://cdn.example.com/logo.png"' in html


def test_send_digest_calls_resend(monkeypatch):
    sent = []
    import adapters.resend as resend
    monkeypatch.setattr(resend, "send", lambda **k: sent.append(k) or "mid-1")
    ids = send_digest({
        "profit_below_minimum": [],
        "proposals_signed": 2,
        "queues": {},
        "cloud_spend": {"ok": False, "error": "x"},
    }, tenant_id=1)
    assert ids
    assert sent
    assert "2 signed" in sent[0]["subject"]
