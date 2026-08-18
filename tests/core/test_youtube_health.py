"""YouTube catalog + bot-block classification for the digest."""
from __future__ import annotations

from datetime import datetime

from core.youtube_health import (
    apply_block_logs,
    apply_job_runs,
    classify_pull,
    collect_youtube_health,
    is_absent_optional_tab,
    is_bot_block,
    material_failed_tabs,
    parse_upload_date,
)


def test_parse_upload_date():
    assert parse_upload_date("20260814") == datetime(2026, 8, 14)
    assert parse_upload_date("2026-08-14") == datetime(2026, 8, 14)
    assert parse_upload_date("nope") is None
    assert parse_upload_date(None) is None
    assert parse_upload_date("20261399") is None


def test_is_bot_block():
    assert is_bot_block("ERROR: Sign in to confirm you’re not a bot")
    assert is_bot_block("Only images are available")
    assert not is_bot_block("Video unavailable")
    assert not is_bot_block(None)


def test_absent_streams_tab_is_not_a_failure():
    assert is_absent_optional_tab("streams", "ERROR: [youtube] This tab is not available") is True
    assert is_absent_optional_tab("streams", "Sign in to confirm you're not a bot") is False
    assert is_absent_optional_tab("streams", "timed out") is False
    assert is_absent_optional_tab("videos", "exit 1") is False
    assert material_failed_tabs(["streams", "videos"]) == ["videos"]


def test_classify_pull_bot_is_blocked():
    out = classify_pull(
        newest_age_days=1, unarchived=2, bot_hits=3,
        failed_tabs=["streams"], incomplete=False,
    )
    assert out["blocked"] is True
    assert out["pull_ok"] is False
    assert any("bot-check" in r for r in out["reasons"])


def test_classify_pull_streams_tab_is_not_block():
    out = classify_pull(
        newest_age_days=3, unarchived=0, bot_hits=0,
        failed_tabs=["streams"], incomplete=False,
    )
    assert out["blocked"] is False
    assert out["pull_ok"] is True
    assert not any("streams" in r for r in out["reasons"])


def test_classify_pull_videos_tab_fails():
    out = classify_pull(
        newest_age_days=3, unarchived=0, bot_hits=0,
        failed_tabs=["videos"], incomplete=True,
    )
    assert out["blocked"] is False
    assert out["pull_ok"] is False
    assert any("incomplete" in r for r in out["reasons"])


def test_classify_pull_stale_and_backlog():
    out = classify_pull(
        newest_age_days=20, unarchived=4, bot_hits=0,
        failed_tabs=[], incomplete=False,
    )
    assert out["blocked"] is False
    assert out["pull_ok"] is False
    assert any("unarchived" in r for r in out["reasons"])
    assert any("20 days" in r for r in out["reasons"])


class _Q:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def all(self):
        return self._rows


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


def test_collect_youtube_health_from_catalog():
    class _V:
        def __init__(self, vid, title, upload, archive=None, unavailable=None):
            self.id = vid
            self.title = title
            self.upload_date = upload
            self.archive_uri = archive
            self.unavailable_since = unavailable

    class _Run:
        video_id = "abc"
        stage = "stt"
        status = "error"
        last_error = "Sign in to confirm you're not a bot"

    class _Ok:
        video_id = "ok"
        stage = "stt"
        status = "done"
        last_error = None

    class _Scan:
        scan_type = "youtube_enumerate"
        ran_at = datetime(2026, 8, 17, 11, 0)
        payload = {
            "enumerated": 120, "failed_tabs": ["streams"], "incomplete": False,
            "videos_in_db": 870,
        }

    class _Arch:
        scan_type = "youtube_archive"
        ran_at = None
        payload = {"archived": 0, "total": 0}

    payload = collect_youtube_health(
        _Db({
            "Video": [
                _V("new", "Clay vs Concrete", "20260814", archive="gs://x"),
                _V("old", "Old one", "20260101", archive=None),
            ],
            "IngestionRun": [_Run(), _Ok()],
            "ScanReport": [_Scan(), _Arch()],
        }),
        since=datetime(2026, 8, 10),
        now=datetime(2026, 8, 17),
    )
    assert payload["videos"] == 2
    assert payload["archived"] == 1
    assert payload["unarchived"] == 1
    assert payload["newest_id"] == "new"
    assert payload["newest_age_days"] == 3
    assert payload["new_this_week"] == 1
    assert payload["blocked"] is True
    assert payload["bot_hits"] == 1
    assert payload["failed_tabs"] == ["streams"]
    assert payload["incomplete"] is False


def test_apply_job_runs_marks_failed_pull():
    yt = {"pull_ok": True, "reasons": []}
    out = apply_job_runs(yt, {"jobs": [
        {"name": "archive", "attention": "failed", "last_execution": "archive-1"},
        {"name": "social", "attention": "ok"},
    ]})
    assert out["pull_ok"] is False
    assert any("archive" in r for r in out["reasons"])


def test_apply_block_logs_historic_does_not_flip_clean_catalog():
    yt = {"blocked": False, "pull_ok": True, "unarchived": 0, "incomplete": False, "reasons": []}
    out = apply_block_logs(yt, [{"timestamp": "2026-08-16", "message": "bot-blocked"}])
    assert out["blocked"] is False
    assert out["recent_blocks"]
    assert any("bot-block" in r for r in out["reasons"])


def test_collect_archive_scan_without_enumerate():
    class _V:
        id = "x"
        title = "t"
        upload_date = None
        archive_uri = "gs://x"
        unavailable_since = None

    class _Scan:
        scan_type = "youtube_archive"
        ran_at = datetime(2026, 8, 17)
        payload = {"archived": 1, "failed_tabs": ["streams"], "incomplete": False}

    payload = collect_youtube_health(
        _Db({"Video": [_V()], "ScanReport": [_Scan()]}),
        since=datetime(2026, 8, 10),
        now=datetime(2026, 8, 17),
    )
    assert payload["failed_tabs"] == ["streams"]
    assert payload["newest_id"] == "x"


def test_collect_scan_query_failure():
    class _Boom(_Db):
        def query(self, model):
            name = getattr(model, "__name__", str(model))
            if "ScanReport" in name:
                raise RuntimeError("no table")
            return super().query(model)

    payload = collect_youtube_health(_Boom({}), since=datetime(2026, 8, 10), now=datetime(2026, 8, 17))
    assert payload["videos"] == 0


def test_fetch_bot_block_logs_filters_and_limit():
    from core.youtube_health import fetch_bot_block_logs

    entries = [
        {"timestamp": "1", "resource": "archive", "message": "ok"},
        {"timestamp": "2", "resource": "archive", "message": "egress 1/14 bot-blocked"},
        {"timestamp": "3", "resource": "archive", "message": "Sign in to confirm you're not a bot"},
    ]
    hits = fetch_bot_block_logs(reader=lambda **k: entries, limit=1)
    assert len(hits) == 1
    assert "bot-blocked" in hits[0]["message"]


def test_fetch_bot_block_logs_reader_fail():
    from core.youtube_health import fetch_bot_block_logs

    def _boom(**k):
        raise RuntimeError("no logs")

    assert fetch_bot_block_logs(reader=_boom) == []


def test_apply_block_logs_plus_backlog_is_blocked():
    yt = {"blocked": False, "pull_ok": True, "unarchived": 2, "incomplete": False, "reasons": []}
    out = apply_block_logs(yt, [{"message": "Sign in to confirm you're not a bot"}])
    assert out["blocked"] is True
    assert out["pull_ok"] is False
