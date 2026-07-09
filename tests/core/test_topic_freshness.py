"""Tests for core/topic_freshness.py — fail-first TDD.

Run: .venv/bin/python -m pytest tests/core/test_topic_freshness.py -v
"""
from datetime import date, datetime

import pytest

from core.topic_freshness import _to_date, topic_freshness


# ---------------------------------------------------------------------------
# _to_date
# ---------------------------------------------------------------------------

def test_to_date_none_returns_none():
    assert _to_date(None) is None


def test_to_date_date_returns_itself():
    d = date(2025, 3, 15)
    assert _to_date(d) is d


def test_to_date_datetime_returns_date_part():
    dt = datetime(2025, 3, 15, 12, 30, 0)
    assert _to_date(dt) == date(2025, 3, 15)


def test_to_date_string_iso_parses():
    assert _to_date("2025-03-15") == date(2025, 3, 15)


def test_to_date_string_with_trailing_time_parses_first_10():
    # upload_date may arrive as "2025-03-15T10:00:00" — take first 10 chars
    assert _to_date("2025-03-15T10:00:00") == date(2025, 3, 15)


def test_to_date_bad_string_returns_none():
    assert _to_date("not-a-date") is None


def test_to_date_empty_string_returns_none():
    assert _to_date("") is None


def test_to_date_unknown_type_returns_none():
    """Any value that is not None/datetime/date/str returns None (defensive fallback)."""
    assert _to_date(12345) is None


# ---------------------------------------------------------------------------
# topic_freshness — no articles case
# ---------------------------------------------------------------------------

def test_freshness_no_articles_not_stale():
    """latest_article_at=None → never stale (no articles generated yet)."""
    result = topic_freshness(["2025-01-01", "2025-06-01"], None)
    assert result == {"stale": False, "new_source_count": 0}


def test_freshness_empty_video_list_no_articles():
    result = topic_freshness([], None)
    assert result == {"stale": False, "new_source_count": 0}


# ---------------------------------------------------------------------------
# topic_freshness — with articles
# ---------------------------------------------------------------------------

def test_freshness_newer_video_is_stale():
    """A video uploaded AFTER the article date makes the topic stale."""
    result = topic_freshness(["2025-06-01"], date(2025, 5, 1))
    assert result["stale"] is True
    assert result["new_source_count"] == 1


def test_freshness_older_video_not_stale():
    """A video uploaded BEFORE the article date does not make the topic stale."""
    result = topic_freshness(["2025-04-01"], date(2025, 5, 1))
    assert result["stale"] is False
    assert result["new_source_count"] == 0


def test_freshness_same_day_video_not_stale():
    """A video uploaded ON the article date is not strictly greater → not stale."""
    result = topic_freshness(["2025-05-01"], date(2025, 5, 1))
    assert result["stale"] is False
    assert result["new_source_count"] == 0


def test_freshness_mixed_videos_correct_count():
    """Some newer, some older — count only the newer ones."""
    upload_dates = ["2025-04-01", "2025-06-01", "2025-07-01", "2025-01-01"]
    result = topic_freshness(upload_dates, date(2025, 5, 1))
    assert result["stale"] is True
    assert result["new_source_count"] == 2


def test_freshness_all_newer_stale():
    """All videos newer than article → stale, count = len(videos)."""
    result = topic_freshness(["2025-06-01", "2025-07-01"], date(2025, 5, 1))
    assert result["stale"] is True
    assert result["new_source_count"] == 2


def test_freshness_empty_video_list_with_article():
    """No videos at all, article exists → not stale, count=0."""
    result = topic_freshness([], date(2025, 5, 1))
    assert result == {"stale": False, "new_source_count": 0}


# ---------------------------------------------------------------------------
# _to_date called on various input types within topic_freshness
# ---------------------------------------------------------------------------

def test_freshness_datetime_article_at():
    """latest_article_at as datetime is normalized correctly."""
    result = topic_freshness(["2025-06-01"], datetime(2025, 5, 1, 8, 0, 0))
    assert result["stale"] is True
    assert result["new_source_count"] == 1


def test_freshness_string_article_at():
    """latest_article_at as ISO string is normalized correctly."""
    result = topic_freshness(["2025-06-01"], "2025-05-01")
    assert result["stale"] is True
    assert result["new_source_count"] == 1


def test_freshness_none_upload_dates_ignored():
    """None values in upload_dates list are silently ignored."""
    result = topic_freshness([None, "2025-06-01", None], date(2025, 5, 1))
    assert result["stale"] is True
    assert result["new_source_count"] == 1


def test_freshness_malformed_upload_dates_ignored():
    """Malformed upload_date strings are silently ignored (not counted)."""
    result = topic_freshness(["bad-date", "2025-06-01", "also-bad"], date(2025, 5, 1))
    assert result["stale"] is True
    assert result["new_source_count"] == 1


def test_freshness_all_malformed_not_stale():
    """All malformed → 0 new source count, not stale."""
    result = topic_freshness(["bad", "worse", None], date(2025, 5, 1))
    assert result == {"stale": False, "new_source_count": 0}


def test_freshness_date_objects_in_upload_list():
    """date objects in the upload_dates list are handled."""
    result = topic_freshness([date(2025, 6, 1), date(2025, 4, 1)], date(2025, 5, 1))
    assert result["stale"] is True
    assert result["new_source_count"] == 1


def test_freshness_datetime_objects_in_upload_list():
    """datetime objects in the upload_dates list are handled."""
    result = topic_freshness([datetime(2025, 6, 1, 0, 0)], date(2025, 5, 1))
    assert result["stale"] is True
    assert result["new_source_count"] == 1
