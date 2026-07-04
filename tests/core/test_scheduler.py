from dataclasses import dataclass
from datetime import datetime, timedelta

from core.scheduler import due


@dataclass
class Row:
    status: str
    publish_at: object


NOW = datetime(2026, 7, 4, 12, 0, 0)


def test_promotes_past_scheduled():
    r = Row("scheduled", NOW - timedelta(minutes=1))
    assert due([r], NOW) == [r]


def test_excludes_future():
    assert due([Row("scheduled", NOW + timedelta(minutes=1))], NOW) == []


def test_excludes_already_published():
    assert due([Row("published", NOW - timedelta(days=1))], NOW) == []


def test_excludes_null_publish_at():
    assert due([Row("scheduled", None)], NOW) == []


def test_at_exact_now_is_due():
    r = Row("scheduled", NOW)
    assert due([r], NOW) == [r]
