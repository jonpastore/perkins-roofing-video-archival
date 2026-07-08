"""Behavioral validation for the roofing estimate engine (core.estimator).

Pins the workbook math: the sheet's own worked example (28 sq 13" tile → $20,280 pre-incentive),
the per-square build-up, the profit sliding scale, every adder branch, both region variants,
and the project-total assembly. Money path — R1 behavioral validation for the stub.
"""
import pytest

from core import estimator as E
from core.estimator import QuoteInput, estimate, profit_per_sq


def test_selfcheck_runs():
    E._selfcheck()  # reproduces the workbook's $20,280 example


def test_worked_example_pre_incentive():
    q = QuoteInput(region="HVHZ", roof_type="13_tile", num_squares=28,
                   override_base_cost=430, override_overhead=115, override_profit_per_sq=90)
    r = estimate(q)
    assert r["per_square_total"] == 635
    assert r["squares_subtotal"] == 17780
    assert r["project_total"] - r["pm_incentive"] == 20280
    assert r["pm_incentive"] == 150  # residential


@pytest.mark.parametrize("n,expected", [(1, 400), (2, 200), (4, 200), (7, 160),
                                        (8, 140), (20, 120), (25, 110), (30, 100), (1000, 100)])
def test_profit_sliding_scale(n, expected):
    assert profit_per_sq(n) == expected


def test_lookup_base_and_overhead_per_type():
    # FBC standing seam: base 750 + oh 205 + profit(20→120) + height 2 stories 50 + metal demo 60
    q = QuoteInput(region="FBC", roof_type="standing_seam_metal", num_squares=20,
                   roof_height="2_stories", demo=True)
    assert estimate(q)["per_square_total"] == 750 + 205 + 120 + 50 + 60


def test_all_per_square_adders_tile():
    q = QuoteInput(region="HVHZ", roof_type="13_tile", num_squares=10,
                   roof_cuts="high", roof_height="2_stories", tile_pointing="yes",
                   specialty_tile="santa_fe_clay_s", pitch_7_12=True, demo=True,
                   secondary_water_barrier=True, winterguard=True)
    # base 780 + oh 270 + profit(10→140) + cuts 50 + height 50 + pointing 200
    # + specialty 160 + pitch 200 + tile demo 40 + swb 75 + winterguard 140
    assert estimate(q)["per_square_total"] == 780 + 270 + 140 + 50 + 50 + 200 + 160 + 200 + 40 + 75 + 140


def test_demo_on_shingle_adds_nothing():
    base = QuoteInput(region="FBC", roof_type="3tab_shingle", num_squares=10)
    demo = QuoteInput(region="FBC", roof_type="3tab_shingle", num_squares=10, demo=True)
    assert estimate(base)["per_square_total"] == estimate(demo)["per_square_total"]


def test_height_none_tier_adds_nothing():
    # 6_plus → None → no per-sq height charge (crane job quoted manually)
    q = QuoteInput(region="FBC", roof_type="3tab_shingle", num_squares=10, roof_height="6_plus")
    ground = QuoteInput(region="FBC", roof_type="3tab_shingle", num_squares=10, roof_height="1_story")
    assert estimate(q)["per_square_total"] == estimate(ground)["per_square_total"]


def test_commercial_permit_and_pm_incentive():
    q = QuoteInput(region="FBC", roof_type="3tab_shingle", num_squares=10, project_kind="commercial")
    r = estimate(q)
    assert r["project_fixed_costs"]["permit_processing"] == 1000  # 500 + 500 commercial
    assert r["pm_incentive"] == 300


def test_dumpster_opt_in_only_for_tile():
    tile = QuoteInput(region="HVHZ", roof_type="13_tile", num_squares=20, include_dumpster=True)
    assert estimate(tile)["project_fixed_costs"]["tile_dumpster"] == 300
    # not tile → no dumpster even when opted in
    metal = QuoteInput(region="HVHZ", roof_type="standing_seam_metal", num_squares=20, include_dumpster=True)
    assert "tile_dumpster" not in estimate(metal)["project_fixed_costs"]
    # tile but not opted in → absent (matches the sheet's headline total)
    off = QuoteInput(region="HVHZ", roof_type="13_tile", num_squares=20)
    assert "tile_dumpster" not in estimate(off)["project_fixed_costs"]


def test_three_five_stories_flat_add():
    q = QuoteInput(region="FBC", roof_type="3tab_shingle", num_squares=10, roof_height="3_5_stories")
    assert estimate(q)["project_fixed_costs"]["stories_3_5_delivery_chute"] == 1200


def test_line_items_stucco_penetrations_ridge_and_extra():
    q = QuoteInput(region="FBC", roof_type="3tab_shingle", num_squares=10,
                   stucco_metal_lf=10, penetrations=3, ridge_vent_lf=20,
                   extra_line_items=["turbine_vents", "not_a_key"])
    li = estimate(q)["line_items"]
    assert li["stucco_metal"] == 90        # 10 * $9
    assert li["penetrations"] == 225       # 3 * $75
    assert li["ridge_vents"] == 195.8      # 20 * $9.79
    assert li["turbine_vents"] == 257.50
    assert "not_a_key" not in li           # unknown keys dropped


def test_specialty_tile_region_variant():
    # FBC has terracottagres instead of verea_caribbean
    q = QuoteInput(region="FBC", roof_type="13_tile", num_squares=10, specialty_tile="terracottagres_s_rustic")
    ground = QuoteInput(region="FBC", roof_type="13_tile", num_squares=10)
    assert estimate(q)["per_square_total"] - estimate(ground)["per_square_total"] == 120


def test_margin_ok_flag():
    # thin margin (metal, low profit tier, big commercial job) → margin_ok False
    thin = QuoteInput(region="FBC", roof_type="standing_seam_metal", num_squares=20,
                      project_kind="commercial", demo=True, roof_height="2_stories")
    assert estimate(thin)["margin_ok"] is False
    # fat margin via override → True
    fat = QuoteInput(region="FBC", roof_type="3tab_shingle", num_squares=1, override_profit_per_sq=5000)
    assert estimate(fat)["margin_ok"] is True


def test_solar_vents_region_price_differs():
    hvhz = estimate(QuoteInput(region="HVHZ", roof_type="3tab_shingle", num_squares=10,
                               extra_line_items=["solar_vents"]))["line_items"]["solar_vents"]
    fbc = estimate(QuoteInput(region="FBC", roof_type="3tab_shingle", num_squares=10,
                              extra_line_items=["solar_vents"]))["line_items"]["solar_vents"]
    assert (hvhz, fbc) == (1339.00, 1489.00)
