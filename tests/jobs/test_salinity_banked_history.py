"""65 of 171 USGS gauges publish only a current value — bank them or they never improve.

Written 2026-07-31, immediately after telling a client the tool builds a 30-day baseline. For the
106 gauges where USGS serves a full series that was already true. For the other 65 it was not:
each sweep overwrote the single spot reading, so a month of hourly runs left exactly one sample.

A single reading on tidal water is close to meaningless — Manatee River at Rye reads 326 uS/cm on
one sample against a 3,210 median — so those gauges were the ones that most needed a baseline and
were the ones that could never get one.

These tests drive `record()` directly through `main()`'s closure by exercising the module the way
the sweep does, and pin the two properties that matter: history accumulates across runs, and a
gauge that has not reported since the last sweep is not counted twice.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

from scripts import fetch_salinity_readings as fsr


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(fsr, "CACHE", tmp_path / "salinity-readings.json")
    return fsr.CACHE


def _run(monkeypatch, cache, *, value: float, observed_at: str, windowed: bool = False):
    """Run one sweep against a single stubbed gauge."""
    site = {"id": "0230", "name": "TEST GAUGE", "lat": 27.5, "lon": -82.3}
    monkeypatch.setattr(fsr, "sites", lambda: [site])

    def fake_get(url: str) -> bytes:
        if "startDT" in url:            # windowed request
            if not windowed:
                return json.dumps({"value": {"timeSeries": []}}).encode()
            pts = [{"value": str(value), "dateTime": observed_at}]
        else:                           # latest-value request
            if windowed:
                return json.dumps({"value": {"timeSeries": []}}).encode()
            pts = [{"value": str(value), "dateTime": observed_at}]
        return json.dumps({"value": {"timeSeries": [{
            "sourceInfo": {"siteCode": [{"value": "0230"}]},
            "values": [{"value": pts}],
        }]}}).encode()

    monkeypatch.setattr(fsr, "_get", fake_get)
    monkeypatch.setattr(fsr.time, "sleep", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["fetch_salinity_readings"])
    fsr.main()
    return json.loads(cache.read_text())["gauges"]["0230"]


def test_a_latest_only_gauge_accumulates_across_sweeps(monkeypatch, cache):
    """Three sweeps, three distinct observation times -> three banked samples, banked median."""
    now = datetime.now(timezone.utc)
    for i, v in enumerate([400.0, 5000.0, 9000.0]):
        at = (now - timedelta(hours=48 - i * 24)).isoformat()
        rec = _run(monkeypatch, cache, value=v, observed_at=at)

    assert rec["samples"] == 3, "each distinct observation should be banked"
    assert rec["banked"] is True
    assert rec["median_us_cm"] == 5000.0, "median follows the banked set, not the latest value"
    assert rec["latest_us_cm"] == 9000.0


def test_a_stale_gauge_is_not_counted_twice(monkeypatch, cache):
    """Same observation time twice = the gauge has not reported; banking it again would bias."""
    at = datetime.now(timezone.utc).isoformat()
    _run(monkeypatch, cache, value=400.0, observed_at=at)
    rec = _run(monkeypatch, cache, value=400.0, observed_at=at)

    assert rec["samples"] == 1
    assert rec["banked"] is False, "one observation is one observation, however many times we ask"


def test_samples_older_than_the_window_fall_out(monkeypatch, cache):
    """The baseline is a ROLLING 30 days, so a stale sample must not anchor it forever."""
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=fsr.WINDOW_DAYS + 5)).isoformat()
    _run(monkeypatch, cache, value=50000.0, observed_at=old)
    rec = _run(monkeypatch, cache, value=400.0, observed_at=now.isoformat())

    assert rec["samples"] == 1, "the out-of-window sample should have been pruned"
    assert rec["median_us_cm"] == 400.0


def test_a_gauge_whose_only_reading_is_stale_does_not_abort_the_sweep(monkeypatch, cache):
    """Pruning to an empty history hit st.median([]) and would have killed the whole run.

    One station that stopped reporting a month ago must not take the other 170 down with it.
    """
    old = (datetime.now(timezone.utc) - timedelta(days=fsr.WINDOW_DAYS + 5)).isoformat()
    rec = _run(monkeypatch, cache, value=50000.0, observed_at=old)

    assert rec["median_us_cm"] == 50000.0, "keep the reading; staleness shows via latest_at"
    assert rec["stale"] is True
    assert rec.get("banked") is not True


def test_a_windowed_gauge_is_left_alone(monkeypatch, cache):
    """USGS's own ~2,800-sample series beats anything we could bank — do not touch it."""
    at = datetime.now(timezone.utc).isoformat()
    rec = _run(monkeypatch, cache, value=46600.0, observed_at=at, windowed=True)

    assert rec["windowed"] is True
    assert "history" not in rec, "windowed gauges must not carry a banked history"
    assert rec["median_us_cm"] == 46600.0
