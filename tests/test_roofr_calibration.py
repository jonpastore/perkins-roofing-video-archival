"""Estimator calibration against Tim's golden Roofr measurements + sold proposals.

Source of truth for measurements is Roofr (docs/perkins-analysis/roofr_baseline.json,
extracted from Tim's golden attachments). This test feeds the Roofr squares into the
cost-plus estimator using the PRODUCTION-ACTIVE pricing config snapshot and asserts the
estimator's PROTECTOR base reproduces Tim's sold PROTECTOR base line within tolerance for
standard-slope / standard-height jobs.

Two golden jobs are excluded from the tight-tolerance assertion because Tim's sold price
carried documented surcharges the base estimate does not model:
  - Palmer   (503 Xanadu): 3-story + 6/12 slope surcharge
  - Malooley (309 Palm Trail): 76 SQ premium-tile job
They are still exercised (must produce a positive estimate) so regressions surface.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.estimator import QuoteInput, estimate
from core.pricing_config import load_config

ROOT = Path(__file__).resolve().parent.parent
FIXDIR = ROOT / "tests/fixtures/golden/roofr_calibration"
ROOFR = json.loads((FIXDIR / "roofr_baseline.json").read_text())
FIX = json.loads((FIXDIR / "proposal_fixtures.json").read_text())
CFG = load_config(json.loads((FIXDIR / "active_pricing_config.json").read_text()))

_SYS = {"shingle": "dimensional_shingle", "tile": "13_tile",
        "metal": "standing_seam_metal", "flat": "low_slope"}
_SLOPE = {"shingle": "sloped", "tile": "sloped", "metal": "sloped", "flat": "low_slope"}


def _street(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"\([^)]*\)", "", s.split(",")[0].lower())).strip()


_ROOFR_BY_STREET = {_street(k): (k, v) for k, v in ROOFR.items()}


def _dominant(fixture: dict) -> str:
    rs = (fixture.get("roof_system") or "").lower()
    for k in ("metal", "tile", "shingle", "flat"):
        if k in rs:
            return k
    return "shingle"


def _sold_base(fixture: dict) -> float:
    for ln in fixture["scope_lines"]:
        d = (ln.get("description") or "").lower()
        if "protector" in d or "built-up" in d or "3-ply" in d:
            return float(ln["line_total"])
    return float(fixture["scope_lines"][0]["line_total"])


def _roofr_for(fixture: dict):
    return _ROOFR_BY_STREET.get(_street(fixture["property_address"]))


def _estimate_base(fixture: dict) -> float:
    _addr, roofr = _roofr_for(fixture)
    sq = round(float(roofr["total_sqft"]) / 100.0, 2)
    sysk = _dominant(fixture)
    zone = "HVHZ" if "404 South M" in _addr else "FBC"
    pitch = float((roofr.get("predominant_pitch") or "4/12").split("/")[0])
    q = QuoteInput(
        code_zone=zone, slope_type=_SLOPE[sysk], roof_type=_SYS[sysk],
        num_squares=sq, project_kind="residential",
        pitch_7_12=(pitch >= 7 and sysk == "tile"),
    )
    return float(estimate(CFG, q)["project_total"])


# Jobs with a Roofr baseline AND a single dominant standard-slope system.
_STANDARD = {"butterworth-2026-05-14", "allen-2026-06-23",
             "thompson-2026-05-05", "mazzeo-2026-03-10"}
_SURCHARGED = {"palmer-2026-07-10", "malooley-2026-05-18"}


def _by_id(pid: str) -> dict:
    return next(f for f in FIX if f["proposal_id"] == pid)


@pytest.mark.parametrize("pid", sorted(_STANDARD))
def test_estimator_reproduces_sold_base_within_tolerance(pid):
    """Standard jobs: estimator base within 10% of Tim's sold PROTECTOR base."""
    fixture = _by_id(pid)
    assert _roofr_for(fixture) is not None, f"{pid} missing Roofr baseline"
    est = _estimate_base(fixture)
    sold = _sold_base(fixture)
    ratio = est / sold
    assert 0.90 <= ratio <= 1.10, f"{pid}: est={est:.2f} sold_base={sold:.2f} ratio={ratio:.3f}"


@pytest.mark.parametrize("pid", sorted(_SURCHARGED))
def test_surcharged_jobs_estimate_is_positive_and_under_sold(pid):
    """Surcharged jobs (3-story/6:12 Palmer, 76 SQ premium Malooley): base estimate is
    positive and below the sold base (the surcharge/premium is the documented delta)."""
    fixture = _by_id(pid)
    assert _roofr_for(fixture) is not None
    est = _estimate_base(fixture)
    sold = _sold_base(fixture)
    assert est > 0
    assert est < sold


def test_roofr_baseline_has_seven_addresses():
    assert len(ROOFR) == 7
