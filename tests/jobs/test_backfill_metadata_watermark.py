"""jobs/backfill_metadata.py selects only what it needs (jobs/ are coverage-omitted).

It used to pull EVERY video row on every run. Chained nightly behind enumerate_channel that
was ~18 YouTube API calls and ~855 no-op row rewrites a night. These tests pin the watermark:
rows that already have upload_date AND duration are not fetched at all.

_fetch_batch is monkeypatched — no real HTTP.
"""
from datetime import date

import pytest

import jobs.backfill_metadata as B
from app.models import Base, SessionLocal, Video, engine


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def _seed(s, vid, upload_date=None, duration=None):
    s.add(Video(id=vid, title=vid, url=f"https://youtu.be/{vid}",
                upload_date=upload_date, duration=duration))
    s.flush()


def _capture(monkeypatch):
    """Record every id the job actually asks the API for."""
    asked: list[str] = []

    def fake(ids, key):
        asked.extend(ids)
        return {i: {"upload_date": date(2026, 7, 28), "duration": 61.0,
                    "views": 10, "likes": 1, "comments": 0} for i in ids}

    monkeypatch.setattr(B, "_fetch_batch", fake)
    return asked


def test_skips_rows_that_already_have_both_fields(monkeypatch):
    asked = _capture(monkeypatch)
    with SessionLocal() as s:
        s.info["tenant_id"] = 1
        _seed(s, "complete1", date(2026, 7, 1), 30.0)
        _seed(s, "complete2", date(2026, 7, 2), 45.0)
        _seed(s, "needsdate", None, 30.0)
        s.commit()
        B._run_for_tenant(s, 1)
    assert asked == ["needsdate"], f"fetched rows it did not need: {asked}"


def test_missing_duration_alone_is_enough_to_be_picked_up(monkeypatch):
    asked = _capture(monkeypatch)
    with SessionLocal() as s:
        s.info["tenant_id"] = 1
        _seed(s, "nodur", date(2026, 7, 1), None)
        s.commit()
        B._run_for_tenant(s, 1)
    assert asked == ["nodur"]


def test_refresh_all_overrides_the_watermark(monkeypatch):
    asked = _capture(monkeypatch)
    with SessionLocal() as s:
        s.info["tenant_id"] = 1
        _seed(s, "complete1", date(2026, 7, 1), 30.0)
        _seed(s, "complete2", date(2026, 7, 2), 45.0)
        s.commit()
        B._run_for_tenant(s, 1, refresh_all=True)
    assert sorted(asked) == ["complete1", "complete2"]


def test_fully_populated_catalogue_makes_zero_api_calls(monkeypatch):
    """The nightly steady state: nothing new, so nothing is pulled."""
    calls = []
    monkeypatch.setattr(B, "_fetch_batch", lambda ids, key: calls.append(ids) or {})
    with SessionLocal() as s:
        s.info["tenant_id"] = 1
        _seed(s, "a", date(2026, 7, 1), 30.0)
        s.commit()
        out = B._run_for_tenant(s, 1)
    assert calls == [], "made an API call with nothing to backfill"
    assert out == {"total": 0, "updated": 0}


def test_a_picked_up_row_still_gets_its_stats(monkeypatch):
    """poll_archive_kpis only covers archive_uri IS NOT NULL, so a brand-new video's only
    chance at views/likes is this one pass."""
    _capture(monkeypatch)
    with SessionLocal() as s:
        s.info["tenant_id"] = 1
        _seed(s, "fresh", None, None)
        s.commit()
        B._run_for_tenant(s, 1)
        row = s.get(Video, "fresh")
        # Video.upload_date is a String column, so it round-trips as "2026-07-28".
        assert str(row.upload_date) == "2026-07-28"
        assert row.duration == 61.0
        assert row.views == 10
