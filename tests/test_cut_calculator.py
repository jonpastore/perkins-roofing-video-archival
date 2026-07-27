"""Roof-cuts custom calculator — Tim's 'Custom Tile Calc' decode (2026-07-17).

Fidelity anchor: with Tim's own sheet inputs and his tile brand (Crown), the engine reproduces
the sheet's TOTAL BASE COST cell (B22 = $811) to the dollar. Everything else pins the shipped
FBC/Eagle behavior and the graceful fallbacks. See docs/plans/2026-07-17-cut-calculator-spec.md.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from core.estimator import QuoteInput, compute_cut_adjusted_base, estimate
from core.pricing_config import load_config

ROOT = Path(__file__).resolve().parent.parent
CFG = load_config(json.loads((ROOT / "infra/fixtures/pricing_config_exhibit_b.json").read_text()))

# Tim's live-sheet example inputs (Custom Tile Calc tab).
SHEET_CUTS = dict(eaves_lf=299, hips_lf=142, ridges_lf=103,
                  valleys_lf=102, rakes_lf=74, wall_flashings_lf=47)
SHEET_SQ = 29


def test_reproduces_tims_sheet_total_with_crown_tile():
    """Formula fidelity: Tim's inputs + his Crown tile → sheet cell B22 ($811)."""
    raw = copy.deepcopy(CFG.raw)
    raw["cuts_calc"]["standard_tile"] = {"field": 143.19, "rake": 4.30}  # Crown, as on the sheet
    cfg = load_config(raw)
    q = QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=SHEET_SQ, **SHEET_CUTS)
    base = compute_cut_adjusted_base(cfg, q, "FBC", "13_tile")
    assert round(base) == 811
    assert base == pytest.approx(810.5783, abs=0.01)


def test_fbc_eagle_standard_tile_base():
    """Shipped FBC config uses Eagle standard tile → cut-adjusted base for the sheet geometry."""
    q = QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=SHEET_SQ, **SHEET_CUTS)
    base = compute_cut_adjusted_base(CFG, q, "FBC", "13_tile")
    assert base == pytest.approx(820.8956, abs=0.01)
    assert base > CFG.sloped_base("FBC", "13_tile")  # cut-heavy roof costs more than flat $770


def test_ceiling_rounds_each_cut_up_to_material_pieces():
    """A roof just over a piece boundary rounds UP (valleys→50ft, others→10ft)."""
    q = QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=20,
                   eaves_lf=291, valleys_lf=101)  # 291→300, 101→150
    q2 = QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=20,
                    eaves_lf=300, valleys_lf=150)
    assert compute_cut_adjusted_base(CFG, q, "FBC", "13_tile") == \
        compute_cut_adjusted_base(CFG, q2, "FBC", "13_tile")


def test_non_tile_scales_by_tile_ratio():
    """Shingle/metal get the flat base scaled by the tile custom/standard ratio (same % diff)."""
    q = QuoteInput(code_zone="FBC", roof_type="dimensional_shingle", num_squares=SHEET_SQ, **SHEET_CUTS)
    tile_q = QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=SHEET_SQ, **SHEET_CUTS)
    tile_base = compute_cut_adjusted_base(CFG, tile_q, "FBC", "13_tile")
    ratio = tile_base / CFG.sloped_base("FBC", "13_tile")
    expected = CFG.sloped_base("FBC", "dimensional_shingle") * ratio
    assert compute_cut_adjusted_base(CFG, q, "FBC", "dimensional_shingle") == pytest.approx(expected)


def test_no_cut_measurements_falls_back_to_flat():
    q = QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=SHEET_SQ)
    assert compute_cut_adjusted_base(CFG, q, "FBC", "13_tile") is None


def test_uncalibrated_zone_falls_back_to_flat():
    """HVHZ has no fixed block yet (needs Tim's HVHZ detail) → None → flat base."""
    q = QuoteInput(code_zone="HVHZ", roof_type="13_tile", num_squares=SHEET_SQ, **SHEET_CUTS)
    assert compute_cut_adjusted_base(CFG, q, "HVHZ", "13_tile") is None


def test_config_without_cuts_calc_is_inert():
    raw = copy.deepcopy(CFG.raw)
    raw.pop("cuts_calc")
    cfg = load_config(raw)
    q = QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=SHEET_SQ, **SHEET_CUTS)
    assert compute_cut_adjusted_base(cfg, q, "FBC", "13_tile") is None


def test_estimate_base_line_reflects_cuts():
    """End-to-end: the estimate's base_cost_lm line carries the cut-adjusted per-sq value."""
    q = QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=SHEET_SQ, **SHEET_CUTS)
    r = estimate(CFG, q)
    base_line = next(li for li in r["line_items_detail"] if li["key"] == "base_cost_lm")
    assert base_line["per_sq"] == pytest.approx(820.9, abs=0.05)


def test_double_count_warning_when_categorical_roof_cuts_stacks():
    """Geometry base + categorical roof_cuts=high both price cuts → advisory warning."""
    q = QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=SHEET_SQ,
                   roof_cuts="high", **SHEET_CUTS)
    r = estimate(CFG, q)
    assert any(w.startswith("roof_cuts_double_count") for w in r["warnings"])


def test_no_double_count_warning_at_default_low():
    q = QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=SHEET_SQ,
                   roof_cuts="low", **SHEET_CUTS)
    r = estimate(CFG, q)
    assert not any(w.startswith("roof_cuts_double_count") for w in r["warnings"])


def test_uncalibrated_zone_warns_when_cuts_supplied():
    """HVHZ has no fixed block → flat base used, but the user is told, not silently downgraded."""
    q = QuoteInput(code_zone="HVHZ", roof_type="13_tile", num_squares=SHEET_SQ,
                   roof_cuts="high", **SHEET_CUTS)
    r = estimate(CFG, q)
    assert any(w.startswith("cut_calc_uncalibrated_zone") for w in r["warnings"])
    # ...and no double-count warning, since the categorical add is the only cut pricing here.
    assert not any(w.startswith("roof_cuts_double_count") for w in r["warnings"])


def test_base_tile_brand_crown_reproduces_sheet():
    """Selecting Crown (Tim's tile on the sheet) reproduces cell B22 ($811) with no config edit."""
    q = QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=SHEET_SQ,
                   base_tile_brand="crown", **SHEET_CUTS)
    assert round(compute_cut_adjusted_base(CFG, q, "FBC", "13_tile")) == 811


def test_base_tile_brand_default_is_eagle():
    q = QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=SHEET_SQ, **SHEET_CUTS)
    assert compute_cut_adjusted_base(CFG, q, "FBC", "13_tile") == pytest.approx(820.8956, abs=0.01)


def test_roof_cuts_material_components_match_sheet_breakdown():
    """Component-level fidelity: drip+SA-V (B16), valley metal+SA-V (B17), H&R+rake tile (B19),
    and eave closure (B20) each match Tim's per-square sheet cells, AND summing them with field
    tiles + the fixed block reproduces the engine's total base (B22 $811) — so a regression in
    any one component (not just the total) is caught.
    """
    raw = copy.deepcopy(CFG.raw)
    raw["cuts_calc"]["standard_tile"] = {"field": 143.19, "rake": 4.30}  # Crown, as on the sheet
    cfg = load_config(raw)
    cc = cfg.raw["cuts_calc"]
    r, co = cc["rounding"], cc["coeff"]

    def _ceil(x: float, m: float) -> float:
        return math.ceil(x / m) * m if x > 0 else 0.0

    sq = SHEET_SQ
    eaves_r = _ceil(SHEET_CUTS["eaves_lf"], r["eaves"])
    hipridge_r = _ceil(SHEET_CUTS["hips_lf"] + SHEET_CUTS["ridges_lf"], r["hips_ridges"])
    valleys_r = _ceil(SHEET_CUTS["valleys_lf"], r["valleys"])
    rakes_r = _ceil(SHEET_CUTS["rakes_lf"], r["rakes"])
    wall_r = _ceil(SHEET_CUTS["wall_flashings_lf"], r["wall_flashings"])

    drip_sav = ((eaves_r + rakes_r) * co["drip_a"]
                + (eaves_r + rakes_r + wall_r) * co["drip_b"]) / sq
    valley = ((valleys_r / co["valley_a_div"]) * co["valley_a_rate"]
              + (valleys_r / co["valley_b_div"]) * co["valley_b_rate"]) / sq
    hipridge_rake = (hipridge_r * co["hipridge_tile_rate"]
                     + (rakes_r + hipridge_r) * cc["standard_tile"]["rake"]) / sq
    eave = (eaves_r * co["eave_closure_rate"]) / sq
    field = cc["standard_tile"]["field"] + co["field_tiles_addon"]

    assert drip_sav == pytest.approx(21.23, abs=0.5)       # drip + SA-V strips ~$21/sq
    assert valley == pytest.approx(21.33, abs=0.5)         # valley metal + SA-V ~$21/sq
    assert hipridge_rake == pytest.approx(68.76, abs=0.5)  # H&R metal + rake tile ~$69/sq
    assert eave == pytest.approx(32.07, abs=0.5)           # eave closure metal ~$32/sq

    q = QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=sq, **SHEET_CUTS)
    total = compute_cut_adjusted_base(cfg, q, "FBC", "13_tile")
    fixed = cc["fixed_per_sq"]["FBC"]
    assert total == pytest.approx(fixed + drip_sav + valley + field + hipridge_rake + eave, abs=0.01)
    assert round(total) == 811


def test_unknown_tile_brand_falls_back_to_standard():
    q = QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=SHEET_SQ,
                   base_tile_brand="does_not_exist", **SHEET_CUTS)
    assert compute_cut_adjusted_base(CFG, q, "FBC", "13_tile") == pytest.approx(820.8956, abs=0.01)


def test_every_tile_brand_matches_the_live_custom_tile_calc():
    """Every brand now carries BOTH a field-tile cost and a rake, read off the live sheet's
    Custom Tile Calc tab (e20aa18). Caribbean's rake moved 19.14 -> 13.98 (E42): 19.14 matched
    nothing on that tab and had the cheaper Caribbean tile quoting above Verea Spanish "S".
    """
    brands = CFG.raw["cuts_calc"]["tile_brands"]
    assert brands["verea_s"]["rake"] == pytest.approx(5.78)
    assert brands["verea_caribbean"]["rake"] == pytest.approx(13.98)
    assert brands["other"]["rake"] == pytest.approx(45.00)
    assert brands["verea_s"]["field"] == pytest.approx(297.04)
    assert brands["verea_caribbean"]["field"] == pytest.approx(230.00)
    assert brands["other"]["field"] == pytest.approx(310.00)
    # The whole point of filling the field costs: no brand is un-quotable any more.
    assert all(b.get("field") for b in brands.values())
    # Caribbean is the cheaper tile and must price below Verea Spanish "S", which is what the
    # old 19.14 rake inverted.
    assert brands["verea_caribbean"]["field"] < brands["verea_s"]["field"]


def test_tile_brand_missing_a_field_cost_still_raises_config_error():
    """The guard must survive the field costs being filled in — a brand added later without one
    has to fail loudly, not price at zero. Asserted against a config with the cost removed rather
    than against a brand that happens to be blank today.
    """
    import copy

    from core.pricing_config import ConfigError, load_config
    raw = copy.deepcopy(CFG.raw)
    raw["cuts_calc"]["tile_brands"]["verea_s"]["field"] = None
    q = QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=SHEET_SQ,
                   base_tile_brand="verea_s", **SHEET_CUTS)
    with pytest.raises(ConfigError, match="verea_s"):
        compute_cut_adjusted_base(load_config(raw), q, "FBC", "13_tile")
