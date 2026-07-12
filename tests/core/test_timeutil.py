from datetime import datetime, timedelta, timezone

from core.timeutil import iso_utc, to_naive_utc


def test_iso_utc_none():
    assert iso_utc(None) is None


def test_iso_utc_naive_assumed_utc():
    assert iso_utc(datetime(2026, 7, 15, 13, 0, 0)) == "2026-07-15T13:00:00Z"


def test_iso_utc_aware_converted_to_utc():
    eastern = timezone(timedelta(hours=-4))
    assert iso_utc(datetime(2026, 7, 15, 9, 0, 0, tzinfo=eastern)) == "2026-07-15T13:00:00Z"


def test_to_naive_utc_treats_naive_as_new_york_wall_time():
    assert to_naive_utc(datetime(2026, 7, 15, 9, 0, 0)) == datetime(2026, 7, 15, 13, 0, 0)


def test_to_naive_utc_converts_aware_input():
    eastern = timezone(timedelta(hours=-4))
    assert to_naive_utc(datetime(2026, 7, 15, 9, 0, 0, tzinfo=eastern)) == datetime(2026, 7, 15, 13, 0, 0)
