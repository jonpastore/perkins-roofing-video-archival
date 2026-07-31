"""A gauge reading is evidence about the water TODAY, not about the water in 2011.

Found 2026-07-31 while building the banked-history feature. USGS `siteStatus=active` returns
stations that are nominally active but whose last instantaneous value can be years old, and the
latest-value endpoint serves it without complaint.

Measured against the live cache at the time: 65 of 171 gauges had not reported in over 30 days,
and 33 of those were classified salt/brackish — including MCCORMICK CREEK AT MOUTH NEAR KEY LARGO
at 42,300 uS/cm from a reading 5,415 DAYS old. All of them were moving warranty verdicts while the
UI cited "measured at ... uS/cm", which a homeowner reads as current.

The cache `_note` had always claimed a reading older than the window "degrades from 'measured' to
'mapped'". Nothing implemented it — documentation of a rule that did not exist, the same shape as
the PRICING_RULES HVHZ adder no config ever carried.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.build_tidal_layer import MAX_READING_AGE_DAYS, _reading_expired

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


def test_a_fresh_reading_is_evidence():
    at = (NOW - timedelta(hours=6)).isoformat()
    assert _reading_expired(at, now=NOW) is False


def test_the_decade_old_key_largo_reading_is_not_evidence():
    """The actual value that was moving verdicts: 42,300 uS/cm, last reported 5,415 days ago."""
    at = (NOW - timedelta(days=5415)).isoformat()
    assert _reading_expired(at, now=NOW) is True


def test_the_boundary_is_the_window():
    just_inside = (NOW - timedelta(days=MAX_READING_AGE_DAYS - 1)).isoformat()
    just_outside = (NOW - timedelta(days=MAX_READING_AGE_DAYS + 1)).isoformat()
    assert _reading_expired(just_inside, now=NOW) is False
    assert _reading_expired(just_outside, now=NOW) is True


def test_a_naive_timestamp_is_treated_as_utc_not_rejected():
    """USGS sends offsets, but a naive stamp must not be discarded as unparseable."""
    at = (NOW - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    assert _reading_expired(at, now=NOW) is False


def test_a_usgs_offset_timestamp_parses():
    """Real shape from NWIS: '2026-07-31T00:15:00.000-04:00'."""
    assert _reading_expired("2026-07-31T00:15:00.000-04:00", now=NOW) is False
    assert _reading_expired("2016-10-11T23:45:00.000-04:00", now=NOW) is True


def test_missing_or_unparseable_timestamps_expire_closed():
    """Fail SAFE: an undateable reading must not be allowed to void someone's warranty.

    Dropping a good reading costs a caveat. Keeping a bad one costs a homeowner being told their
    roof warranty is dead on a measurement nobody can date.
    """
    for bad in (None, "", "not-a-date", "2026-13-45T99:99:99"):
        assert _reading_expired(bad, now=NOW) is True, bad


def test_the_builder_and_the_fetcher_agree_on_the_window():
    """Two files, two constants, one fact — and the gap between them is a false VOID.

    The fetcher marks a gauge `stale` when its only observation prunes out of WINDOW_DAYS. The
    builder independently re-derives expiry from `latest_at` against MAX_READING_AGE_DAYS and
    never reads `stale`. That is safe only while the two numbers match.

    Raise MAX_READING_AGE_DAYS to 60 and every stale record — undated, ancient, carrying a single
    spot reading — becomes a verdict-moving `measured` citation again. That is the 5,415-day
    McCormick Creek failure returning through a different door, and it would reach a homeowner as
    "measured at 42,300 uS/cm". Flagged by the architect review, 2026-07-31.
    """
    from scripts.fetch_salinity_readings import WINDOW_DAYS

    assert float(MAX_READING_AGE_DAYS) == float(WINDOW_DAYS), (
        f"build_tidal_layer.MAX_READING_AGE_DAYS={MAX_READING_AGE_DAYS} but "
        f"fetch_salinity_readings.WINDOW_DAYS={WINDOW_DAYS}. If the builder's window is the LONGER "
        "of the two, gauges the fetcher gave up on are resurrected as measured evidence."
    )


def test_a_record_the_fetcher_marked_stale_is_ignored_by_the_builder():
    """Cross the boundary the other two test files each stop at."""
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    from datetime import timezone as _tz

    from scripts.fetch_salinity_readings import WINDOW_DAYS

    ancient = (_dt.now(_tz.utc) - _td(days=WINDOW_DAYS + 10)).isoformat()
    stale_record = {"id": "0230", "name": "DEAD GAUGE", "lat": 27.5, "lon": -82.3,
                    "median_us_cm": 42300.0, "latest_at": ancient, "stale": True}

    assert _reading_expired(stale_record["latest_at"]) is True, (
        "the builder must reject exactly what the fetcher gave up on"
    )
