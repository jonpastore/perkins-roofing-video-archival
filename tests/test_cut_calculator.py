"""Roof-cuts custom calculator — Tim's 'Custom Tile Calc' decode (2026-07-17).

Fidelity anchor: with Tim's own sheet inputs and his tile brand (Crown), the engine reproduces
the sheet's TOTAL BASE COST cell (B22 = $811) to the dollar. Everything else pins the shipped
FBC/Eagle behavior and the graceful fallbacks. See docs/plans/2026-07-17-cut-calculator-spec.md.
"""
from __future__ import annotations

import copy
import json
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


def test_unknown_tile_brand_falls_back_to_standard():
    q = QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=SHEET_SQ,
                   base_tile_brand="does_not_exist", **SHEET_CUTS)
    assert compute_cut_adjusted_base(CFG, q, "FBC", "13_tile") == pytest.approx(820.8956, abs=0.01)
