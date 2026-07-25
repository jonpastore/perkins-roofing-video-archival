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


# ---------------------------------------------------------------------------
# Observability pins — R2 critic C6
#
# Every golden job above is FBC, <=6/12, no demo, per-square OH mode, so a config change to the
# HVHZ, 7/12+ or WinterGuard paths moves NOTHING in this file: the critic ran the whole suite
# across two config versions and measured delta $0 on all six jobs. Two live pricing changes
# shipped that no harness in this repo could observe.
#
# These are NOT sold-price evidence — there is no sold HVHZ or 7/12 job in the corpus, and
# inventing one would be worse than having none. They pin the engine's current output on those
# paths so the NEXT change to them is visible in a diff instead of silent. Replace with real
# sold jobs the moment Tim sends one.
# ---------------------------------------------------------------------------

def _q(**kw) -> dict:
    base = dict(slope_type="sloped", roof_type="13_tile", num_squares=30.0,
                project_kind="residential")
    return estimate(CFG, QuoteInput(**{**base, **kw}))


def _per_sq(result: dict, key: str) -> float:
    return next(i["per_sq"] for i in result["line_items_detail"] if i["key"] == key)


def test_hvhz_and_fbc_are_priced_differently():
    """The zone axis must reach the total. If these ever converge, a zone lookup has collapsed
    to a scalar — which is exactly what the admin panel used to do to the zoned adders."""
    fbc, hvhz = _q(code_zone="FBC"), _q(code_zone="HVHZ")
    assert hvhz["project_total"] > fbc["project_total"]
    assert _per_sq(hvhz, "overhead") > _per_sq(fbc, "overhead")
    assert _per_sq(hvhz, "base_cost_lm") > _per_sq(fbc, "base_cost_lm")


def test_steep_tile_adder_is_305_in_both_zones():
    """Re-derived from Tim's cell comments 2026-07-25: Demo L 70 + Tile L 70 + M 40 + OH 90/95
    + P 35/30 = $305 in both live comments. The $200 headline contradicted its own comment."""
    for zone in ("FBC", "HVHZ"):
        r = _q(code_zone=zone, pitch_7_12=True, existing_roof="tile")
        assert _per_sq(r, "pitch_7_12_add") == 305, zone


def test_winterguard_is_135_in_both_zones():
    """Same comment on the live sloped AND the NEW sheet: M 60 + L 25 + OH 32 + P 18 = $135."""
    for zone in ("FBC", "HVHZ"):
        assert _per_sq(_q(code_zone=zone, winterguard=True), "winterguard") == 135, zone


def test_demo_adders_keep_their_real_zone_split():
    """tile/metal demo DO differ by zone — no comment exists on either, so the per-tab headlines
    are the evidence, and they run HVHZ > FBC like every other paired price."""
    assert _per_sq(_q(code_zone="FBC", existing_roof="tile"), "tile_demo") == 30
    assert _per_sq(_q(code_zone="HVHZ", existing_roof="tile"), "tile_demo") == 40
    assert _per_sq(_q(code_zone="FBC", roof_type="standing_seam_metal",
                      existing_roof="metal"), "metal_demo") == 45
    assert _per_sq(_q(code_zone="HVHZ", roof_type="standing_seam_metal",
                      existing_roof="metal"), "metal_demo") == 60


@pytest.mark.parametrize("sq,profit_per_sq", [
    (1.0, 400), (4.0, 200), (7.0, 160), (14.0, 140), (20.0, 120), (29.0, 110), (30.0, 100),
])
def test_profit_band_edges_match_tims_labels(sq, profit_per_sq):
    """profit_scale stores Tim's INCLUSIVE band labels, so a job landing exactly on an edge takes
    the band the label names — not the next band down. sq=20 is double-claimed on his sheet
    ("15-20" and "20-29") and resolves to $120 pending his answer."""
    assert _per_sq(_q(code_zone="FBC", num_squares=sq), "profit") == profit_per_sq
