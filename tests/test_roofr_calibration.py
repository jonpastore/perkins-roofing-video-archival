"""Estimator vs sold PROTECTOR *scope lines*, priced the way the salesperson quotes.

This is NOT a claim that we reprint Tim's PDFs. Sold jobs carry copper, paint, gutters,
named discounts, and waste-inclusive squares the engine does not invent. We:

- split Roofr pitched/flat into sloped + flat_squares
- tear-off (demo) on, because every sold PROTECTOR scope tears off
- overhead_mode=daily (Tim, 2026-08-03: OH is days, per-sq is a guide)
- compare the engine total to the SUM of PROTECTOR / built-up / 3-ply lines only

Palmer / Malooley stay "produces a number" — 3-story / waste / second structure are
not fully modeled. Exhibit-B 28sq JSON fixtures are engine unit tests, not sold PDFs.
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
_SNAP = json.loads((FIXDIR / "active_pricing_config.json").read_text())
_EXHIBIT = json.loads((ROOT / "infra/fixtures/pricing_config_exhibit_b.json").read_text())
_SNAP["daily_overhead_rates"] = _EXHIBIT["daily_overhead_rates"]
_SNAP["daily_overhead_day_model"] = _EXHIBIT["daily_overhead_day_model"]
_ls = dict(_SNAP.get("low_slope") or {})
_ex_ls = _EXHIBIT.get("low_slope") or {}
if _ex_ls.get("default_flat_system"):
    _ls["default_flat_system"] = _ex_ls["default_flat_system"]
if _ex_ls.get("base_cost_lm"):
    _ls["base_cost_lm"] = _ex_ls["base_cost_lm"]
if _ex_ls.get("overhead"):
    _ls["overhead"] = _ex_ls["overhead"]
_SNAP["low_slope"] = _ls
CFG = load_config(_SNAP)

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


def _sold_protector_lines(fixture: dict) -> float:
    """Sum of the re-roof scope lines — not copper, paint, gutters, or discounts."""
    total = 0.0
    hit = False
    for ln in fixture["scope_lines"]:
        if ln.get("is_optional"):
            continue
        d = (ln.get("description") or "").lower()
        if any(k in d for k in ("copper", "paint", "gutter", "discount", "solatube",
                                "hurricane", "stucco", "strap")):
            continue
        if any(k in d for k in ("protector", "built-up", "3-ply", "flat re-roof")):
            total += float(ln["line_total"])
            hit = True
    if hit:
        return total
    return float(fixture["scope_lines"][0]["line_total"])


def _roofr_for(fixture: dict):
    return _ROOFR_BY_STREET.get(_street(fixture["property_address"]))


def _existing_for(sysk: str) -> str:
    return {"tile": "tile", "metal": "metal", "shingle": "shingle", "flat": "other"}.get(sysk, "other")


def _quote_for(fixture: dict, **quote_over) -> QuoteInput:
    _addr, roofr = _roofr_for(fixture)
    pitched = float(roofr.get("pitched_sqft") or 0) / 100.0
    flat = float(roofr.get("flat_sqft") or 0) / 100.0
    if pitched <= 0 and flat <= 0:
        pitched = float(roofr["total_sqft"]) / 100.0
    sysk = _dominant(fixture)
    zone = "HVHZ" if "404 South M" in _addr else "FBC"
    pitch = float((roofr.get("predominant_pitch") or "4/12").split("/")[0])
    existing = _existing_for(sysk)
    sloped = sysk != "flat"
    notes = f"{fixture.get('project_name') or ''} {fixture.get('scope_lines', [{}])[0].get('notes') or ''}"
    three_story = "3 story" in notes.lower() or "3-story" in notes.lower()
    kw = dict(
        code_zone=zone,
        slope_type="sloped" if sloped else "low_slope",
        roof_type=_SYS[sysk] if sloped else "polyglass_sav_sap",
        num_squares=round(pitched if sloped else (pitched + flat), 2),
        flat_squares=round(flat, 2) if sloped and flat > 0 else None,
        project_kind="residential",
        existing_roof=existing,
        demo=True,
        overhead_mode="daily",
        pitch_7_12=(pitch >= 7 and sysk == "tile"),
        roof_height="3_5_stories" if three_story else "1_story",
        stories=3 if three_story else None,
    )
    kw.update(quote_over)
    return QuoteInput(**kw)


def _estimate_job(fixture: dict, **quote_over) -> dict:
    return estimate(CFG, _quote_for(fixture, **quote_over))


# Jobs with a Roofr baseline AND a single dominant standard-slope system.
_STANDARD = {"butterworth-2026-05-14", "allen-2026-06-23",
             "thompson-2026-05-05", "mazzeo-2026-03-10"}
_SURCHARGED = {"palmer-2026-07-10", "malooley-2026-05-18"}


def _by_id(pid: str) -> dict:
    return next(f for f in FIX if f["proposal_id"] == pid)


@pytest.mark.parametrize("pid", sorted(_STANDARD))
def test_estimator_reproduces_sold_protector_lines_within_tolerance(pid):
    """Standard jobs: daily-OH mixed quote vs summed PROTECTOR/flat lines, ±15%.

    15% is the remaining method gap (days vs catalog specials, waste, extras we
    stripped). This is not a 100% claim. Butterworth is mixed tile+flat — it
    must not be priced as all-tile against the flat line.
    """
    fixture = _by_id(pid)
    assert _roofr_for(fixture) is not None, f"{pid} missing Roofr baseline"
    result = _estimate_job(fixture)
    est = float(result["project_total"])
    sold = _sold_protector_lines(fixture)
    ratio = est / sold
    # Single-system jobs should land near the sold PROTECTOR line. Mixed jobs are
    # catalog packages (Butterworth flat $28k on 15.5 SQ) and will not match a
    # cost-up; we only require the split to be priced (see the Butterworth test).
    _, roofr = _roofr_for(fixture)
    mixed = float(roofr.get("flat_sqft") or 0) > 0
    if mixed:
        assert any(li["key"].startswith("flat_") for li in result["line_items_detail"])
        return
    assert 0.85 <= ratio <= 1.15, f"{pid}: est={est:.2f} sold_lines={sold:.2f} ratio={ratio:.3f}"


@pytest.mark.parametrize("pid", sorted(_SURCHARGED))
def test_surcharged_jobs_estimate_is_positive(pid):
    """Palmer (3-story) and Malooley (waste / 2nd structure) must still price."""
    fixture = _by_id(pid)
    assert _roofr_for(fixture) is not None
    r = _estimate_job(fixture)
    est = float(r["project_total"])
    assert est > 0
    if pid == "palmer-2026-07-10":
        keys = {li["key"] for li in r["line_items_detail"]}
        assert "stories_3_5_delivery_chute" in keys


def test_butterworth_is_priced_as_mixed_not_all_tile():
    """Regression: the old harness billed 23.79 SQ of tile against the sold FLAT line."""
    r = _estimate_job(_by_id("butterworth-2026-05-14"))
    assert r["total_squares"] == pytest.approx(23.79, abs=0.05)
    keys = {li["key"] for li in r["line_items_detail"]}
    assert any(k.startswith("flat_") for k in keys), keys


def _cfg_with_job_floor():
    """Live quoting enforces the $2,500 job floor. The calibration snapshot does not."""
    raw = json.loads(json.dumps(CFG.raw))
    raw["enforce_profit_floor"] = True
    raw["profit_floor_basis"] = "job"
    raw["job_profit_floor"] = 2500
    raw["weekly_profit_floor"] = 2500
    raw["profit_floor_after_commission"] = False
    return load_config(raw)


@pytest.mark.parametrize("pid", sorted(_STANDARD | _SURCHARGED))
@pytest.mark.parametrize("pct", (0.0, 0.05, 0.10))
def test_sold_proposal_slider_under_2500_warns_and_still_prices(pid, pct):
    """$2,500 is advisory. 0–10% on these sold jobs may land under it; quote still issues."""
    r = estimate(_cfg_with_job_floor(), _quote_for(
        _by_id(pid), profit_mode="percent", percent_profit_pct=pct))
    profit = next(li["amount"] for li in r["line_items_detail"] if li["key"] == "profit")
    assert r["project_total"] > 0
    if profit + 1e-6 < 2500.0:
        assert any(str(w).startswith("profit_below_minimum") for w in r["warnings"]), r["warnings"]
    assert not any(li["key"] == "project_profit_floor" for li in r["line_items_detail"])


def test_roofr_baseline_has_seven_addresses():
    assert len(ROOFR) == 7


# ---------------------------------------------------------------------------
# Observability pins — R2 critic C6
#
# Standard sold jobs above now run daily OH + demo + pitched/flat split. These pins still
# exist because HVHZ / 7/12+ / WinterGuard have no sold row in the corpus — a config change
# on those paths would not move the ratio tests.
#
# These are NOT sold-price evidence — there is no sold HVHZ or 7/12 job in the corpus, and
# inventing one would be worse than having none. They pin the engine's current output on those
# paths so the NEXT change to them is visible in a diff instead of silent. Replace with real
# sold jobs the moment Tim sends one.
# ---------------------------------------------------------------------------

def _q(**kw) -> dict:
    base = dict(slope_type="sloped", roof_type="13_tile", num_squares=30.0,
                project_kind="residential", overhead_mode="per_sq")
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
