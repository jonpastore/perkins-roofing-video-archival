"""Estimator v2 — day-based overhead + flat-dollar profit mode.

TDD: these tests were written BEFORE the engine changes; they drive the implementation.
All golden examples are from Tim's worked examples in docs/superpowers/specs/2026-07-10-estimator-v2-tim-feedback.md.

Spec decisions documented here:
- on-site weeks = ceil(total_series_days / 5)  — scheduling-window model: inspections after
  a 7-day job still tie up ~2 weeks of window, so we use ceil. Configurable via
  daily_overhead_rates.weeks_rounding_mode ("ceil" | "floor"); default "ceil".
- Validation: each series days must be a multiple of 0.5 and > 0.
- Flat-dollar profit mode does NOT hard-enforce the floor; it surfaces guidance fields
  (profit_floor_guidance, implied_weekly_profit) for UI display. The engine returns them
  alongside the flat profit value so the UI can warn without blocking the estimate.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from core.pricing_config import load_config, PricingConfig
from core.estimator import (
    QuoteInput,
    estimate,
    DailyOverheadSeries,
    compute_daily_overhead,
    compute_profit_guidance,
    derive_daily_series,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _raw_config() -> dict:
    src = Path(__file__).parent.parent.parent / "infra" / "fixtures" / "pricing_config_exhibit_b.json"
    return json.loads(src.read_text())


def _cfg_v2() -> PricingConfig:
    """Config with v2 keys (daily_overhead_rates + profit_mode) present."""
    raw = _raw_config()
    return load_config(raw)


# ---------------------------------------------------------------------------
# Golden test 1: Tim's 40 SQ shingle→metal worked example — day-based OH
# ---------------------------------------------------------------------------

def test_daily_oh_golden_40sq_shingle_metal():
    """Tim's exact worked example: 40 SQ demo 2d + metal 5d → OH_total 6350 → 158.75/sq."""
    series = [
        DailyOverheadSeries(series="demo_dry_in_flat", days=2.0),
        DailyOverheadSeries(series="metal", days=5.0),
    ]
    cfg = _cfg_v2()
    oh_total, per_sq_oh = compute_daily_overhead(cfg, series, num_squares=40.0)
    assert oh_total == 6350.0, f"expected OH_total=6350, got {oh_total}"
    assert per_sq_oh == 158.75, f"expected per_sq_OH=158.75, got {per_sq_oh}"


# ---------------------------------------------------------------------------
# Golden test 2: 7-day job, 40 SQ — flat profit guidance ≥ $5,000
# ---------------------------------------------------------------------------

def test_profit_guidance_golden_7days_40sq():
    """7 days on-site → 2 weeks (ceil(7/5)) → floor = 2 × $2500 = $5000."""
    series = [
        DailyOverheadSeries(series="demo_dry_in_flat", days=2.0),
        DailyOverheadSeries(series="metal", days=5.0),
    ]
    cfg = _cfg_v2()
    guidance = compute_profit_guidance(cfg, series)
    assert guidance["on_site_weeks"] == 2, f"expected 2 on-site weeks, got {guidance['on_site_weeks']}"
    assert guidance["weekly_floor"] == 2500.0
    assert guidance["profit_floor_guidance"] == 5000.0, (
        f"expected profit_floor_guidance=5000, got {guidance['profit_floor_guidance']}"
    )
    assert guidance["absolute_floor"] == 2500.0
    assert guidance["effective_floor"] == 5000.0, "max(absolute, weekly) = 5000"


# ---------------------------------------------------------------------------
# Unit tests: DailyOverheadSeries validation
# ---------------------------------------------------------------------------

def test_daily_series_valid_half_day():
    """0.5-day increments are valid."""
    series = [DailyOverheadSeries(series="shingle", days=0.5)]
    cfg = _cfg_v2()
    oh_total, per_sq = compute_daily_overhead(cfg, series, num_squares=10.0)
    # shingle: 0.5 * 700 = 350 → per_sq = 35
    assert oh_total == 350.0
    assert per_sq == 35.0


def test_daily_series_invalid_not_half_increment():
    """Days not a multiple of 0.5 must raise ValueError."""
    with pytest.raises(ValueError, match="0.5"):
        DailyOverheadSeries(series="shingle", days=0.3)


def test_daily_series_invalid_zero_days():
    """days=0 must raise ValueError."""
    with pytest.raises(ValueError, match="positive"):
        DailyOverheadSeries(series="shingle", days=0.0)


def test_daily_series_invalid_negative():
    """Negative days must raise ValueError."""
    with pytest.raises(ValueError, match="positive"):
        DailyOverheadSeries(series="shingle", days=-1.0)


def test_daily_series_unknown_series_raises():
    """Unknown series name must raise a ConfigError (not silently produce 0)."""
    from core.pricing_config import ConfigError
    cfg = _cfg_v2()
    series = [DailyOverheadSeries(series="mystery_series", days=1.0)]
    with pytest.raises(ConfigError, match="mystery_series"):
        compute_daily_overhead(cfg, series, num_squares=10.0)


# ---------------------------------------------------------------------------
# Unit tests: all four daily overhead rates
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("series_name,rate", [
    ("demo_dry_in_flat", 1050),
    ("tile", 745),
    ("metal", 850),
    ("shingle", 700),
])
def test_daily_rate_per_series(series_name, rate):
    """Each series has the correct daily rate from config."""
    cfg = _cfg_v2()
    series = [DailyOverheadSeries(series=series_name, days=1.0)]
    oh_total, per_sq = compute_daily_overhead(cfg, series, num_squares=1.0)
    assert oh_total == float(rate)
    assert per_sq == float(rate)


# ---------------------------------------------------------------------------
# Unit tests: multi-series OH accumulation
# ---------------------------------------------------------------------------

def test_daily_oh_multi_series():
    """OH from multiple series sums correctly."""
    cfg = _cfg_v2()
    series = [
        DailyOverheadSeries(series="demo_dry_in_flat", days=1.0),   # 1050
        DailyOverheadSeries(series="tile", days=2.0),                 # 1490
        DailyOverheadSeries(series="shingle", days=0.5),              # 350
    ]
    oh_total, per_sq = compute_daily_overhead(cfg, series, num_squares=10.0)
    expected_total = 1050 + 745 * 2 + 700 * 0.5
    assert oh_total == expected_total
    assert abs(per_sq - expected_total / 10.0) < 0.001


# ---------------------------------------------------------------------------
# Unit tests: profit guidance edge cases
# ---------------------------------------------------------------------------

def test_profit_guidance_1_day():
    """1-day job → ceil(1/5) = 1 week → floor = 2500 (weekly=2500, absolute=2500)."""
    cfg = _cfg_v2()
    series = [DailyOverheadSeries(series="shingle", days=1.0)]
    guidance = compute_profit_guidance(cfg, series)
    assert guidance["on_site_weeks"] == 1
    assert guidance["profit_floor_guidance"] == 2500.0
    assert guidance["effective_floor"] == 2500.0


def test_profit_guidance_5_days():
    """5-day job → ceil(5/5) = 1 week → floor = 2500."""
    cfg = _cfg_v2()
    series = [DailyOverheadSeries(series="shingle", days=5.0)]
    guidance = compute_profit_guidance(cfg, series)
    assert guidance["on_site_weeks"] == 1
    assert guidance["effective_floor"] == 2500.0


def test_profit_guidance_6_days():
    """6-day job → ceil(6/5) = 2 weeks → floor = 5000."""
    cfg = _cfg_v2()
    series = [DailyOverheadSeries(series="shingle", days=6.0)]
    guidance = compute_profit_guidance(cfg, series)
    assert guidance["on_site_weeks"] == 2
    assert guidance["effective_floor"] == 5000.0


def test_profit_guidance_absolute_floor_dominates():
    """Very short job: 0.5 days → 1 week → weekly=2500 = absolute=2500 → effective=2500."""
    cfg = _cfg_v2()
    series = [DailyOverheadSeries(series="shingle", days=0.5)]
    guidance = compute_profit_guidance(cfg, series)
    assert guidance["on_site_weeks"] == 1
    assert guidance["effective_floor"] == 2500.0  # max(2500, 2500) = 2500


def test_profit_guidance_implied_weekly():
    """implied_weekly_profit = flat_profit / on_site_weeks; surfaced as readout for UI."""
    cfg = _cfg_v2()
    series = [DailyOverheadSeries(series="shingle", days=5.0)]
    guidance = compute_profit_guidance(cfg, series, flat_profit=7500.0)
    # 1 week → implied = 7500 / 1 = 7500
    assert guidance["implied_weekly_profit"] == 7500.0


def test_profit_guidance_implied_weekly_multi_week():
    """Multi-week: flat_profit / weeks = implied weekly."""
    cfg = _cfg_v2()
    series = [DailyOverheadSeries(series="shingle", days=10.0)]
    guidance = compute_profit_guidance(cfg, series, flat_profit=6000.0)
    # ceil(10/5) = 2 weeks → implied = 6000 / 2 = 3000
    assert guidance["implied_weekly_profit"] == 3000.0


# ---------------------------------------------------------------------------
# Integration: estimate() with overhead_mode="daily" in QuoteInput
# ---------------------------------------------------------------------------

def test_estimate_daily_oh_mode_golden():
    """Full estimate with daily OH mode: 40 SQ metal, 2d demo + 5d metal.

    OH portion replaces the per-sq overhead line item.
    per_sq_OH = 158.75 should appear in the overhead line item.
    40 SQ must be commercial — the PM incentive matrix has no residential ≥20 SQ band.
    """
    cfg = _cfg_v2()
    q = QuoteInput(
        code_zone="FBC",
        slope_type="sloped",
        roof_type="standing_seam_metal",
        num_squares=40.0,
        project_kind="commercial",
        overhead_mode="daily",
        daily_series=[
            DailyOverheadSeries(series="demo_dry_in_flat", days=2.0),
            DailyOverheadSeries(series="metal", days=5.0),
        ],
    )
    r = estimate(cfg, q)
    oh_item = next(
        li for li in r["line_items_detail"] if li["key"] == "overhead"
    )
    assert abs(oh_item["amount"] - 6350.0) < 0.01, (
        f"OH line item amount should be 6350 (total), got {oh_item['amount']}"
    )
    assert abs(oh_item["per_sq"] - 158.75) < 0.001, (
        f"OH per_sq should be 158.75, got {oh_item['per_sq']}"
    )


def test_estimate_daily_oh_mode_result_has_guidance():
    """estimate() in daily mode returns profit_guidance dict in result."""
    cfg = _cfg_v2()
    q = QuoteInput(
        code_zone="FBC",
        slope_type="sloped",
        roof_type="standing_seam_metal",
        num_squares=40.0,
        project_kind="commercial",
        overhead_mode="daily",
        daily_series=[
            DailyOverheadSeries(series="demo_dry_in_flat", days=2.0),
            DailyOverheadSeries(series="metal", days=5.0),
        ],
    )
    r = estimate(cfg, q)
    assert "profit_guidance" in r, "daily mode result must include profit_guidance"
    g = r["profit_guidance"]
    assert g["on_site_weeks"] == 2
    assert g["effective_floor"] == 5000.0


def test_estimate_flat_profit_mode():
    """estimate() with profit_mode='flat' uses flat_profit_dollars for the profit line."""
    cfg = _cfg_v2()
    q = QuoteInput(
        code_zone="FBC",
        slope_type="sloped",
        roof_type="3tab_shingle",
        num_squares=10.0,
        project_kind="residential",
        profit_mode="flat",
        flat_profit_dollars=3500.0,
    )
    r = estimate(cfg, q)
    profit_item = next(
        li for li in r["line_items_detail"] if li["key"] == "profit"
    )
    assert abs(profit_item["amount"] - 3500.0) < 0.01, (
        f"Profit line should be flat 3500, got {profit_item['amount']}"
    )


def test_estimate_flat_profit_mode_guidance_in_result():
    """Flat-profit mode with daily series returns guidance fields in result."""
    cfg = _cfg_v2()
    q = QuoteInput(
        code_zone="FBC",
        slope_type="sloped",
        roof_type="standing_seam_metal",
        num_squares=40.0,
        project_kind="commercial",
        overhead_mode="daily",
        daily_series=[
            DailyOverheadSeries(series="demo_dry_in_flat", days=2.0),
            DailyOverheadSeries(series="metal", days=5.0),
        ],
        profit_mode="flat",
        flat_profit_dollars=5000.0,
    )
    r = estimate(cfg, q)
    g = r["profit_guidance"]
    assert g["effective_floor"] == 5000.0
    assert abs(g["implied_weekly_profit"] - 2500.0) < 0.01  # 5000 / 2 weeks


# ---------------------------------------------------------------------------
# Backward-compat: existing per-sq OH mode still works (default)
# ---------------------------------------------------------------------------

def test_estimate_default_mode_unchanged():
    """overhead_mode='per_sq' (default) preserves existing behavior — no regressions."""
    cfg = _cfg_v2()
    q = QuoteInput(
        code_zone="FBC",
        slope_type="sloped",
        roof_type="3tab_shingle",
        num_squares=10.0,
        project_kind="residential",
    )
    r = estimate(cfg, q)
    # Default per-sq OH for FBC 3tab_shingle = 105
    oh_item = next(li for li in r["line_items_detail"] if li["key"] == "overhead")
    assert abs(oh_item["per_sq"] - 105.0) < 0.01
    # No profit_guidance in default mode
    assert "profit_guidance" not in r


def test_estimate_scale_profit_mode_unchanged():
    """profit_mode='scale' (default) uses sliding scale — no regression."""
    cfg = _cfg_v2()
    q = QuoteInput(
        code_zone="FBC",
        slope_type="sloped",
        roof_type="3tab_shingle",
        num_squares=10.0,
        project_kind="residential",
        profit_mode="scale",
    )
    r = estimate(cfg, q)
    profit_item = next(li for li in r["line_items_detail"] if li["key"] == "profit")
    # 10 SQ → scale tier 7≤10<14 → $140/sq → total 1400
    assert abs(profit_item["amount"] - 1400.0) < 0.01


# ---------------------------------------------------------------------------
# Config: daily_overhead_rates present in exhibit_b fixture
# ---------------------------------------------------------------------------

def test_config_has_daily_overhead_rates():
    """pricing_config_exhibit_b.json must contain daily_overhead_rates after our additive patch."""
    cfg = _cfg_v2()
    rates = cfg.daily_overhead_rates()
    assert "demo_dry_in_flat" in rates, "demo_dry_in_flat key missing"
    assert "tile" in rates, "tile key missing"
    assert "metal" in rates, "metal key missing"
    assert "shingle" in rates, "shingle key missing"
    assert rates["demo_dry_in_flat"] == 1050
    assert rates["tile"] == 745
    assert rates["metal"] == 850
    assert rates["shingle"] == 700


def test_config_has_profit_mode_defaults():
    """pricing_config_exhibit_b.json must contain profit_mode_default config key."""
    cfg = _cfg_v2()
    assert cfg.profit_mode_default() in ("scale", "flat"), (
        "profit_mode_default must be 'scale' or 'flat'"
    )
    assert cfg.profit_mode_default() == "scale", "default must be 'scale' for backward compat"


def test_config_has_weekly_profit_floor():
    """Config must expose weekly_profit_floor ($2500) and job_profit_floor ($2500)."""
    cfg = _cfg_v2()
    assert cfg.weekly_profit_floor() == 2500.0
    assert cfg.job_profit_floor() == 2500.0


# ---------------------------------------------------------------------------
# Coverage gap tests — lines not exercised by the above
# ---------------------------------------------------------------------------

def test_compute_daily_overhead_zero_squares_raises():
    """num_squares <= 0 guard in compute_daily_overhead must raise ValueError."""
    cfg = _cfg_v2()
    series = [DailyOverheadSeries(series="shingle", days=1.0)]
    with pytest.raises(ValueError, match="positive"):
        compute_daily_overhead(cfg, series, num_squares=0.0)


def test_profit_guidance_floor_rounding_mode():
    """weeks_rounding_mode='floor' path: total_days=6 → floor(6/5)=1 week, min-clamped to 1."""
    raw = _raw_config()
    raw["daily_overhead_weeks_rounding_mode"] = "floor"
    cfg = load_config(raw)
    series = [DailyOverheadSeries(series="shingle", days=6.0)]
    guidance = compute_profit_guidance(cfg, series)
    # floor(6/5) = 1 week (not 2 like ceil would give)
    assert guidance["on_site_weeks"] == 1
    assert guidance["effective_floor"] == 2500.0


def test_profit_guidance_floor_rounding_ten_days():
    """floor(10/5) = 2 weeks (same as ceil here; confirms the floor path executes)."""
    raw = _raw_config()
    raw["daily_overhead_weeks_rounding_mode"] = "floor"
    cfg = load_config(raw)
    series = [DailyOverheadSeries(series="shingle", days=10.0)]
    guidance = compute_profit_guidance(cfg, series)
    assert guidance["on_site_weeks"] == 2


# ---------------------------------------------------------------------------
# Pre-existing coverage gap: _low_slope_oh_key pb_ / flat_oh branches
# These were uncovered before v2; plugged here as part of the R1 100% mandate.
# ---------------------------------------------------------------------------

def _cfg_low_slope_with_all_types() -> PricingConfig:
    """Config with enough low-slope data to route pb_ and polyglass roof types."""
    raw = _raw_config()
    ls = dict(raw["low_slope"])
    ls["base_cost_lm"] = {
        "HVHZ": {
            "pb_acrylic_2coat": 375,
            "polyglass_sav_sap": 475,
            "tpo_adhered": 485,
        },
        "FBC": {
            "pb_acrylic_2coat": 375,
            "polyglass_sav_sap": 450,
            "tpo_adhered": 485,
        },
    }
    ls["overhead"] = {
        "HVHZ": {"flat_oh": 155, "tpo_oh": 135, "coatings_inhouse_oh": 95},
        "FBC":  {"flat_oh": 155, "tpo_oh": 135, "coatings_inhouse_oh": 95},
    }
    # pb_acrylic_2coat is all-in (no OH/profit added) — keep as-is from fixture
    raw = dict(raw)
    raw["low_slope"] = ls
    return load_config(raw)


def test_low_slope_oh_key_pb_routes_to_coatings_inhouse_oh():
    """_low_slope_oh_key: pb_ prefix → coatings_inhouse_oh (line 634-635)."""
    from core.estimator import _low_slope_oh_key
    assert _low_slope_oh_key("pb_acrylic_2coat") == "coatings_inhouse_oh"
    assert _low_slope_oh_key("pb_silicone_2coat") == "coatings_inhouse_oh"


def test_low_slope_oh_key_stockmeier_routes_to_coatings_inhouse_oh():
    """_low_slope_oh_key: stockmeier prefix → coatings_inhouse_oh (line 634-635)."""
    from core.estimator import _low_slope_oh_key
    assert _low_slope_oh_key("stockmeier_polyurethane_2coat") == "coatings_inhouse_oh"


def test_low_slope_oh_key_flat_fallthrough():
    """_low_slope_oh_key: anything else → flat_oh (line 636)."""
    from core.estimator import _low_slope_oh_key
    assert _low_slope_oh_key("polyglass_sav_sap") == "flat_oh"
    assert _low_slope_oh_key("unknown_bur_type") == "flat_oh"


def test_low_slope_build_with_polyglass_uses_flat_oh():
    """polyglass_sav_sap routes to flat_oh in _build_low_slope (non-all-in system)."""
    cfg = _cfg_low_slope_with_all_types()
    q = QuoteInput(
        code_zone="FBC",
        slope_type="low_slope",
        roof_type="polyglass_sav_sap",
        num_squares=10.0,
        project_kind="residential",
    )
    r = estimate(cfg, q)
    oh_item = next(li for li in r["line_items_detail"] if li["key"] == "overhead")
    # flat_oh = 155 for FBC
    assert abs(oh_item["per_sq"] - 155.0) < 0.01


# ---------------------------------------------------------------------------
# R2 HIGH-1: low-slope path must support both v2 modes symmetrically
# ---------------------------------------------------------------------------

def _cfg_low_slope_v2() -> PricingConfig:
    """Low-slope config with v2 keys and real polyglass/tpo data for mode tests."""
    raw = _raw_config()
    ls = dict(raw["low_slope"])
    ls["base_cost_lm"] = {
        "HVHZ": {"polyglass_sav_sap": 475, "tpo_adhered": 485},
        "FBC":  {"polyglass_sav_sap": 450, "tpo_adhered": 485},
    }
    ls["overhead"] = {
        "HVHZ": {"flat_oh": 155, "tpo_oh": 135, "coatings_inhouse_oh": 95},
        "FBC":  {"flat_oh": 155, "tpo_oh": 135, "coatings_inhouse_oh": 95},
    }
    raw = dict(raw)
    raw["low_slope"] = ls
    return load_config(raw)


def test_low_slope_daily_oh_mode():
    """_build_low_slope with overhead_mode='daily' uses day-based OH instead of per-sq."""
    cfg = _cfg_low_slope_v2()
    q = QuoteInput(
        code_zone="FBC",
        slope_type="low_slope",
        roof_type="polyglass_sav_sap",
        num_squares=10.0,
        project_kind="residential",
        overhead_mode="daily",
        daily_series=[
            DailyOverheadSeries(series="demo_dry_in_flat", days=1.0),
            DailyOverheadSeries(series="shingle", days=1.0),
        ],
    )
    r = estimate(cfg, q)
    oh_item = next(li for li in r["line_items_detail"] if li["key"] == "overhead")
    # demo 1d×1050 + shingle 1d×700 = 1750 total OH
    assert abs(oh_item["amount"] - 1750.0) < 0.01
    assert abs(oh_item["per_sq"] - 175.0) < 0.01
    # guidance is attached
    assert "profit_guidance" in r


def test_low_slope_flat_profit_mode():
    """_build_low_slope with profit_mode='flat' uses flat_profit_dollars for profit line."""
    cfg = _cfg_low_slope_v2()
    q = QuoteInput(
        code_zone="FBC",
        slope_type="low_slope",
        roof_type="polyglass_sav_sap",
        num_squares=10.0,
        project_kind="residential",
        profit_mode="flat",
        flat_profit_dollars=4000.0,
    )
    r = estimate(cfg, q)
    profit_item = next(li for li in r["line_items_detail"] if li["key"] == "profit")
    assert abs(profit_item["amount"] - 4000.0) < 0.01
    # guidance attached even without daily_series (flat mode alone)
    assert "profit_guidance" in r
    g = r["profit_guidance"]
    assert g["on_site_weeks"] is None
    assert g["effective_floor"] == 2500.0  # absolute floor only


def test_low_slope_daily_oh_and_flat_profit_combined():
    """Low-slope path supports both modes simultaneously — correct OH + profit + guidance."""
    cfg = _cfg_low_slope_v2()
    q = QuoteInput(
        code_zone="FBC",
        slope_type="low_slope",
        roof_type="tpo_adhered",
        num_squares=20.0,
        project_kind="commercial",
        overhead_mode="daily",
        daily_series=[DailyOverheadSeries(series="demo_dry_in_flat", days=3.0)],
        profit_mode="flat",
        flat_profit_dollars=5000.0,
    )
    r = estimate(cfg, q)
    oh_item = next(li for li in r["line_items_detail"] if li["key"] == "overhead")
    profit_item = next(li for li in r["line_items_detail"] if li["key"] == "profit")
    # demo 3d×1050=3150 OH total, /20 sq = 157.5/sq
    assert abs(oh_item["amount"] - 3150.0) < 0.01
    assert abs(profit_item["amount"] - 5000.0) < 0.01
    g = r["profit_guidance"]
    # ceil(3/5)=1 week → floor=2500; flat=5000 → implied=5000/1=5000
    assert g["on_site_weeks"] == 1
    assert abs(g["implied_weekly_profit"] - 5000.0) < 0.01


# ---------------------------------------------------------------------------
# R2 HIGH-2: guidance attachment — flat mode alone (no daily series)
# ---------------------------------------------------------------------------

def test_guidance_attached_for_flat_profit_no_series():
    """profit_mode='flat' without daily_series still attaches profit_guidance."""
    cfg = _cfg_v2()
    q = QuoteInput(
        code_zone="FBC",
        slope_type="sloped",
        roof_type="3tab_shingle",
        num_squares=10.0,
        project_kind="residential",
        profit_mode="flat",
        flat_profit_dollars=3000.0,
    )
    r = estimate(cfg, q)
    assert "profit_guidance" in r
    g = r["profit_guidance"]
    # No series days → on_site_weeks is None, only absolute floor applies
    assert g["on_site_weeks"] is None
    assert g["effective_floor"] == 2500.0
    assert "implied_weekly_profit" not in g


def test_guidance_not_attached_default_mode():
    """Default per_sq/scale mode — profit_guidance must not appear in result."""
    cfg = _cfg_v2()
    q = QuoteInput(
        code_zone="FBC",
        slope_type="sloped",
        roof_type="3tab_shingle",
        num_squares=10.0,
        project_kind="residential",
    )
    r = estimate(cfg, q)
    assert "profit_guidance" not in r


# ---------------------------------------------------------------------------
# R2 MEDIUM-2: margin badge — flat profit below effective floor → margin_ok False
# ---------------------------------------------------------------------------

def test_margin_ok_false_when_flat_profit_below_floor():
    """Flat profit below effective floor must set margin_ok=False (via margin_warnings)."""
    cfg = _cfg_v2()
    q = QuoteInput(
        code_zone="FBC",
        slope_type="sloped",
        roof_type="3tab_shingle",
        num_squares=10.0,
        project_kind="residential",
        overhead_mode="daily",
        daily_series=[DailyOverheadSeries(series="shingle", days=5.0)],
        profit_mode="flat",
        flat_profit_dollars=1000.0,  # below 2500 floor
    )
    r = estimate(cfg, q)
    # margin_ok must be False — flat profit $1000 < effective_floor $2500
    assert r["margin_ok"] is False
    assert "flat_profit_floor" in r["margin_warnings"]


def test_margin_ok_true_when_flat_profit_above_floor():
    """Flat profit above effective floor → no flat_profit_floor warning."""
    cfg = _cfg_v2()
    q = QuoteInput(
        code_zone="FBC",
        slope_type="sloped",
        roof_type="3tab_shingle",
        num_squares=10.0,
        project_kind="residential",
        overhead_mode="daily",
        daily_series=[DailyOverheadSeries(series="shingle", days=5.0)],
        profit_mode="flat",
        flat_profit_dollars=3000.0,  # above 2500 floor
    )
    r = estimate(cfg, q)
    assert "flat_profit_floor" not in r["margin_warnings"]


# ---------------------------------------------------------------------------
# Auto-derived labor days (days = setup + rate x SQ) — Tim's time-learning model
# (docs/ROOFR_OVERHEAD_TIERS.md). Daily mode with no days supplied used to fall
# silently back to per-square OH, which is the ~$2k PROTECTOR gap.
# ---------------------------------------------------------------------------

def test_derive_daily_series_tile_tear_off():
    """43 SQ tile over tile: tile 0.45+0.129*43=6.0d, demo 1.31+0.044*43=3.2→3.0d."""
    cfg = _cfg_v2()
    q = QuoteInput(code_zone="HVHZ", roof_type="13_tile", num_squares=43.0,
                   existing_roof="tile", overhead_mode="daily")
    got = {s.series: s.days for s in derive_daily_series(cfg, q)}
    assert got == {"tile": 6.0, "demo_dry_in_flat": 3.0}, got


def test_derive_daily_series_skips_demo_on_new_construction():
    """existing_roof='none' → install days only, no tear-off days."""
    cfg = _cfg_v2()
    q = QuoteInput(code_zone="HVHZ", roof_type="13_tile", num_squares=43.0,
                   existing_roof="none", overhead_mode="daily")
    assert [s.series for s in derive_daily_series(cfg, q)] == ["tile"]


def test_derive_daily_series_empty_for_unmodelled_roof():
    """Low-slope systems have no fitted model → no derivation (stays manual)."""
    cfg = _cfg_v2()
    q = QuoteInput(code_zone="HVHZ", roof_type="tpo_adhered", num_squares=40.0,
                   slope_type="low_slope", existing_roof="flat", overhead_mode="daily")
    assert derive_daily_series(cfg, q) == []


def test_derive_daily_series_always_half_day_multiples():
    """Derived days must satisfy the DailyOverheadSeries contract for any job size."""
    cfg = _cfg_v2()
    for sq in [1, 7, 12.5, 23, 40, 61, 97, 150]:
        for rt in ["13_tile", "standing_seam_metal", "3tab_shingle"]:
            q = QuoteInput(code_zone="FBC", roof_type=rt, num_squares=float(sq),
                           existing_roof="shingle", overhead_mode="daily")
            for s in derive_daily_series(cfg, q):
                assert s.days >= 0.5 and round(s.days % 0.5, 10) == 0.0, (rt, sq, s)


def test_estimate_auto_fills_days_when_none_supplied():
    """40 SQ metal over shingle: demo 3.0d ($1050) + metal 5.0d ($850) = $7,400 OH."""
    cfg = _cfg_v2()
    q = QuoteInput(code_zone="FBC", roof_type="standing_seam_metal", num_squares=40.0,
                   project_kind="commercial", existing_roof="shingle", overhead_mode="daily")
    r = estimate(cfg, q)
    oh = next(li for li in r["line_items_detail"] if li["key"] == "overhead")
    assert abs(oh["amount"] - 7400.0) < 0.01, oh
    assert abs(oh["per_sq"] - 185.0) < 0.001, oh
    assert {d["series"]: d["days"] for d in r["daily_series"]} == {
        "demo_dry_in_flat": 3.0, "metal": 5.0,
    }
    assert r["profit_guidance"]["total_series_days"] == 8.0


def test_estimate_typed_days_beat_derived_days():
    """Days the estimator typed are never overwritten by the model."""
    cfg = _cfg_v2()
    q = QuoteInput(code_zone="FBC", roof_type="standing_seam_metal", num_squares=40.0,
                   project_kind="commercial", existing_roof="shingle", overhead_mode="daily",
                   daily_series=[DailyOverheadSeries(series="metal", days=1.0)])
    r = estimate(cfg, q)
    oh = next(li for li in r["line_items_detail"] if li["key"] == "overhead")
    assert abs(oh["amount"] - 850.0) < 0.01, oh


def test_estimate_per_sq_fallback_preserved_without_day_model():
    """No day model in config → daily mode with no days still falls back to per-sq OH."""
    raw = _raw_config()
    raw.pop("daily_overhead_day_model")
    cfg = load_config(raw)
    q = QuoteInput(code_zone="FBC", roof_type="standing_seam_metal", num_squares=40.0,
                   project_kind="commercial", existing_roof="shingle", overhead_mode="daily")
    r = estimate(cfg, q)
    oh = next(li for li in r["line_items_detail"] if li["key"] == "overhead")
    assert abs(oh["per_sq"] - cfg.sloped_overhead("FBC", "standing_seam_metal")) < 0.001, oh


def test_auto_filled_days_are_warned_about():
    """Auto-fill must be visible: by-days OH is far below per-sq OH on tile/metal."""
    cfg = _cfg_v2()
    q = QuoteInput(code_zone="HVHZ", roof_type="barrel_tile", num_squares=43.0,
                   project_kind="commercial", existing_roof="tile", overhead_mode="daily")
    r = estimate(cfg, q)
    assert any(w.startswith("daily_days_auto_filled") for w in r["warnings"]), r["warnings"]


def test_typed_days_are_not_warned_about():
    cfg = _cfg_v2()
    q = QuoteInput(code_zone="HVHZ", roof_type="barrel_tile", num_squares=43.0,
                   project_kind="commercial", existing_roof="tile", overhead_mode="daily",
                   daily_series=[DailyOverheadSeries(series="tile", days=6.0)])
    r = estimate(cfg, q)
    assert not any(w.startswith("daily_days_auto_filled") for w in r["warnings"])


# ---------------------------------------------------------------------------
# Geometry-driven days — Tim's actual method (Zoom 2026-07-17 [10:12]): two 30-SQ
# roofs take 2 vs 5-6 days depending on complexity, so days track cuts, not area.
# ---------------------------------------------------------------------------

def _tile_q(**kw):
    base = dict(code_zone="FBC", roof_type="13_tile", num_squares=30.0,
                project_kind="commercial", existing_roof="tile", overhead_mode="daily")
    base.update(kw)
    return QuoteInput(**base)


def test_two_same_size_roofs_differ_when_geometry_differs():
    """The whole point of Tim's method: same squares, different complexity, different days."""
    cfg = _cfg_v2()
    simple = derive_daily_series(cfg, _tile_q(hips_lf=20, ridges_lf=20))
    complex_ = derive_daily_series(cfg, _tile_q(hips_lf=260, ridges_lf=200, valleys_lf=180,
                                                rakes_lf=150, wall_flashings_lf=90))
    simple_days = sum(s.days for s in simple)
    complex_days = sum(s.days for s in complex_)
    assert complex_days > simple_days, (
        f"a heavily-cut roof must take longer than a simple one of the same size: "
        f"{complex_days} vs {simple_days}")


def test_geometry_days_beat_squares_only_on_a_cut_up_roof():
    """With cut LFs present the geometry model is used, not the squares-only fit."""
    cfg = _cfg_v2()
    cut_up = _tile_q(hips_lf=260, ridges_lf=200, valleys_lf=180, rakes_lf=150)
    plain = _tile_q()
    assert sum(s.days for s in derive_daily_series(cfg, cut_up)) > \
           sum(s.days for s in derive_daily_series(cfg, plain))


def test_squares_only_fallback_when_no_cut_measurements():
    """No cut LFs → the squares-only fit, NOT the geometry model evaluated at all-zero
    complexity (which would read as the simplest possible roof and under-quote the days)."""
    cfg = _cfg_v2()
    got = {s.series: s.days for s in derive_daily_series(cfg, _tile_q())}
    # squares-only tile fit: 0.45 + 0.129*30 = 4.32 -> 4.5; demo 1.31 + 0.044*30 = 2.63 -> 2.5
    assert got == {"tile": 4.5, "demo_dry_in_flat": 2.5}, got


def test_geometry_coefficients_are_all_non_negative():
    """More geometry must never mean fewer days — a negative coefficient would under-price
    exactly the complex roofs Tim says take longest."""
    model = _cfg_v2().daily_overhead_day_model()["geometry_model"]
    for series, coef in model.items():
        for term, value in coef.items():
            if term == "loo_r2":
                continue
            assert value >= 0, f"{series}.{term} is negative ({value})"


def test_geometry_days_still_half_day_multiples():
    cfg = _cfg_v2()
    for hips in (0, 45, 130, 300):
        for sq in (12.0, 30.0, 76.0):
            q = _tile_q(num_squares=sq, hips_lf=hips, ridges_lf=hips / 2)
            for s in derive_daily_series(cfg, q):
                assert s.days >= 0.5 and round(s.days % 0.5, 10) == 0.0, (sq, hips, s)


def test_cuts_drive_days_without_moving_the_base():
    """The bug that reached prod: the quote route withheld cut LFs from the headline quote to keep
    Tim's flat base, so the geometry day model saw zero complexity on every real quote and fell
    back to the squares-only fit. Cuts must feed the DAYS while the base stays flat."""
    cfg = _cfg_v2()
    kw = dict(code_zone="FBC", roof_type="13_tile", num_squares=30.0, project_kind="commercial",
              existing_roof="tile", overhead_mode="daily")
    cuts = dict(hips_lf=260, ridges_lf=200, valleys_lf=180, rakes_lf=150, wall_flashings_lf=90)

    flat = estimate(cfg, QuoteInput(**kw))
    geom = estimate(cfg, QuoteInput(**kw, **cuts, apply_cut_calc_to_base=False))
    cut_adj = estimate(cfg, QuoteInput(**kw, **cuts))          # default: cuts DO move the base

    def base_ps(r):
        return next(li["per_sq"] for li in r["line_items_detail"] if li["key"] == "base_cost_lm")

    assert base_ps(geom) == base_ps(flat), "flat base must survive apply_cut_calc_to_base=False"
    assert base_ps(cut_adj) != base_ps(flat), "the cut calculator still moves the base by default"
    geom_days = sum(d["days"] for d in geom["daily_series"])
    flat_days = sum(d["days"] for d in flat["daily_series"])
    assert geom_days > flat_days, (
        f"cut LFs must lengthen the job even with the flat base: {geom_days} vs {flat_days}")
