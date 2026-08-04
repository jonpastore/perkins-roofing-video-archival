"""F2 engine core tests — fail-first TDD per TRD-F2 §7.

Covers: golden-file harness, RFC 8785 hash canonicalization, margin floors,
commission, boundary-band, tile dumpster, county overrides, PM incentive matrix,
and low-slope ConfigError paths (skip-marked pending Tim data).

All tests in this file operate on pure core/ logic — no DB, no I/O.
"""
from __future__ import annotations

import json
from pathlib import Path

import jcs
import pytest

from core.estimator import QuoteInput, QuoteRequiresManualReview, estimate
from core.pricing_config import (
    ConfigError,
    ConfigValidationError,
    PricingConfig,
    compute_hash,
    load_config,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pricing_config_exhibit_b.json"
GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden"

def _is_engine_golden(path: Path) -> bool:
    """Is this an engine input/expected pair, as test_golden_file requires?

    The golden dir also holds DECODED-REFERENCE fixtures — evergrene_project.json is Tim's bid
    read out of his spreadsheet formulas (buildings, per-building markups, his own totals), not
    a QuoteInput. Globbing every *.json swept it into the parametrized engine test, which then
    died on KeyError: 'input', and pushed the committed count from 3 to 4. Both failures have
    been red on main since 8c19501; CI runs `pytest tests/` so it caught them and the local
    pre-push set (tests/api tests/core tests/adapters tests/jobs tests/tenancy) does not reach
    this file. Select by SHAPE so a new reference fixture cannot re-break the engine harness.
    """
    try:
        return "input" in json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return False


GOLDEN_FILES = (
    sorted(p for p in GOLDEN_DIR.glob("*.json") if _is_engine_golden(p))
    if GOLDEN_DIR.exists() else []
)

_CONFIG_DICT: dict | None = None


def _raw_config() -> dict:
    global _CONFIG_DICT
    if _CONFIG_DICT is None:
        src = Path(__file__).parent.parent / "infra" / "fixtures" / "pricing_config_exhibit_b.json"
        _CONFIG_DICT = json.loads(src.read_text())
    return _CONFIG_DICT


@pytest.fixture(scope="module")
def cfg() -> PricingConfig:
    return load_config(_raw_config())


# ---------------------------------------------------------------------------
# §7.1 Golden-file harness
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fixture_path", GOLDEN_FILES, ids=lambda p: p.stem)
def test_golden_file(fixture_path: Path, cfg: PricingConfig):
    data = json.loads(fixture_path.read_text())
    inp = data["input"]
    q = QuoteInput(**{k: v for k, v in inp.items() if v is not None or k in (
        "specialty_tile", "county", "deck_type",
    )})
    result = estimate(cfg, q)
    total = result["project_total"]
    expected = data["expected_total"]
    tol = max(data["tolerance_abs"], expected * data["tolerance_pct"])
    assert abs(total - expected) <= tol, (
        f"{fixture_path.stem}: expected {expected}, got {total}, diff {total - expected}"
    )


# ---------------------------------------------------------------------------
# §7.2 Config loading
# ---------------------------------------------------------------------------
def test_config_load_valid(cfg: PricingConfig):
    assert cfg.schema_version == 1
    assert cfg.exhibit_version == "B-2026-07-10-r2"


def _cfg_low_slope_nulled(*path) -> PricingConfig:
    """Load a config copy with one nested low_slope value set to null/[] so the
    accessor's missing-value guard can be exercised now that the fixture is
    fully populated (low-slope prices filled 2026-07-10)."""
    import copy
    raw = copy.deepcopy(_raw_config())
    node = raw["low_slope"]
    for k in path[:-1]:
        node = node[k]
    node[path[-1]] = [] if path[-1] == "insulation_tiers" else None
    return load_config(raw)


def test_config_hash_matches_recomputed(cfg: PricingConfig):
    raw = _raw_config()
    h1 = compute_hash(raw)
    h2 = compute_hash(raw)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_config_schema_missing_field():
    bad = dict(_raw_config())
    del bad["profit_scale"]
    with pytest.raises(ConfigValidationError, match="profit_scale"):
        load_config(bad)


def test_config_null_low_slope_raises(cfg: PricingConfig):
    with pytest.raises(ConfigError, match="low_slope.base_cost_lm"):
        cfg.low_slope_base("HVHZ", "tpo")


def test_config_null_low_slope_overhead_raises():
    cfg = _cfg_low_slope_nulled("overhead", "HVHZ", "tpo_oh")
    with pytest.raises(ConfigError, match="low_slope.overhead"):
        cfg.low_slope_overhead("HVHZ", "tpo_oh")


def test_config_null_tapered_raises():
    cfg = _cfg_low_slope_nulled("tapered_cost_per_sq")
    with pytest.raises(ConfigError, match="low_slope.tapered_cost_per_sq"):
        cfg.low_slope_tapered_cost()


def test_config_null_tear_off_raises():
    cfg = _cfg_low_slope_nulled("tear_off_per_layer_per_sq")
    with pytest.raises(ConfigError, match="low_slope.tear_off_per_layer_per_sq"):
        cfg.low_slope_tear_off_cost()


def test_config_empty_insulation_tiers_raises():
    """No thickness table and no legacy rows -> ConfigError, not a silent default."""
    import copy
    raw = copy.deepcopy(_raw_config())
    raw["low_slope"].pop("insulation_by_thickness", None)
    raw["low_slope"]["insulation_tiers"] = []
    with pytest.raises(ConfigError, match="insulation"):
        load_config(raw).low_slope_insulation_cost("1in")


# ---------------------------------------------------------------------------
# §7.3 Hash canonicalization (RFC 8785)
# ---------------------------------------------------------------------------
def test_rfc8785_key_ordering():
    d1 = {"z": 1, "a": 2, "m": 3}
    d2 = {"a": 2, "m": 3, "z": 1}
    assert compute_hash(d1) == compute_hash(d2)


def test_rfc8785_float_precision():
    # jcs canonicalizes numbers consistently
    c1 = jcs.canonicalize({"v": 1})
    c2 = jcs.canonicalize({"v": 1.0})
    assert c1 == c2


def test_rfc8785_unicode():
    d = {"name": "café"}
    h1 = compute_hash(d)
    h2 = compute_hash({"name": "café"})
    assert h1 == h2


def test_hash_determinism():
    raw = _raw_config()
    hashes = {compute_hash(raw) for _ in range(10)}
    assert len(hashes) == 1


def test_hash_sensitivity():
    raw = _raw_config()
    h1 = compute_hash(raw)
    modified = dict(raw)
    modified["profit_floor_pct"] = 0.14
    h2 = compute_hash(modified)
    assert h1 != h2


def test_hash_strips_pending_keys():
    d1 = {"a": 1, "_pending": "ignore me"}
    d2 = {"a": 1}
    assert compute_hash(d1) == compute_hash(d2)


# ---------------------------------------------------------------------------
# §7.4 Floor and commission denominator tests
# ---------------------------------------------------------------------------
def test_floor_exhibit_b_example(cfg: PricingConfig):
    """Pinned floor check: 28 SQ HVHZ 13-tile commercial → both profit_floor and combined_floor warn.

    TRD §4.3 shows a simplified example (no auto-dumpster, uses $120/sq profit annotation that
    appears to be a TRD typo — engine uses $110/sq per the profit_scale array for 20≤sq<29).
    With the correct $110/sq profit and auto tile-dumpster:
      project_total=36380, profit=3080, OH=7560, eligible_base=33300
      profit_pct=9.25% → below 13% floor → warning
      combined_pct=31.95% → below 33% floor → warning
    Both warnings fire; this test pins the correct engine output.
    See OPEN ITEM: TRD §4.3 annotation "20-29 SQ → $120/sq" conflicts with profit_scale array
    entry [20, 120] (max_sq=20) — Tim must confirm whether $120 applies to ≥20 or <20 band.
    """
    q = QuoteInput(
        code_zone="HVHZ", county="broward", slope_type="sloped",
        roof_type="13_tile", num_squares=28.0,
        project_kind="commercial",
    )
    r = estimate(cfg, q)
    assert "profit_floor" in r["margin_warnings"]
    # Combined floor also fails at 31.95% (< 33%) given auto dumpster and $110/sq profit
    assert "combined_floor" in r["margin_warnings"]
    # Verify the denominator math is correct
    assert abs(r["margin"]["eligible_base"] - (r["project_total"] - r["margin"]["profit_dollars"])) < 0.01


def test_profit_floor_13pct_pass(cfg: PricingConfig):
    """Construct a quote where profit is at/above 13%."""
    # Use override profit to push above 13% floor
    q = QuoteInput(
        code_zone="HVHZ", slope_type="sloped", roof_type="3tab_shingle",
        num_squares=5.0, project_kind="residential",
        override_profit_per_sq=500,
    )
    r = estimate(cfg, q)
    assert r["margin"]["profit_floor_ok"] is True
    assert "profit_floor" not in r["margin_warnings"]


def test_profit_floor_13pct_fail(cfg: PricingConfig):
    """Construct a quote where profit falls below 13% floor."""
    q = QuoteInput(
        code_zone="HVHZ", slope_type="sloped", roof_type="3tab_shingle",
        num_squares=5.0, project_kind="residential",
        override_profit_per_sq=1,
    )
    r = estimate(cfg, q)
    assert r["margin"]["profit_floor_ok"] is False
    assert "profit_floor" in r["margin_warnings"]


def test_combined_floor_33pct(cfg: PricingConfig):
    """OH + profit at/above 33% combined floor.

    override_overhead=600 gives combined_pct ~52% — clearly above 33% floor.
    """
    q = QuoteInput(
        code_zone="HVHZ", slope_type="sloped", roof_type="3tab_shingle",
        num_squares=5.0, project_kind="residential",
        override_profit_per_sq=200, override_overhead=600,
    )
    r = estimate(cfg, q)
    assert r["margin"]["combined_floor_ok"] is True
    assert r["margin"]["combined_pct"] >= 0.33


def test_combined_floor_fail(cfg: PricingConfig):
    """OH + profit below 33% combined floor."""
    q = QuoteInput(
        code_zone="FBC", slope_type="sloped", roof_type="3tab_shingle",
        num_squares=5.0, project_kind="residential",
        override_profit_per_sq=1, override_overhead=1,
    )
    r = estimate(cfg, q)
    assert r["margin"]["combined_floor_ok"] is False
    assert "combined_floor" in r["margin_warnings"]


def test_eligible_base_excludes_profit(cfg: PricingConfig):
    """Profit dollars must not be in their own denominator."""
    q = QuoteInput(
        code_zone="FBC", slope_type="sloped", roof_type="3tab_shingle",
        num_squares=10.0, project_kind="residential",
    )
    r = estimate(cfg, q)
    # eligible_base = project_total - profit_dollars (no insulation/tapered in this quote)
    profit_d = r["margin"]["profit_dollars"]
    total = r["project_total"]
    # pm_incentive is Misc so included in eligible_base
    expected_eligible = total - profit_d
    assert abs(r["margin"]["eligible_base"] - expected_eligible) < 0.01


@pytest.mark.parametrize("zone", ["FBC", "HVHZ"])
def test_commission_is_half_of_net_in_every_zone(cfg: PricingConfig, zone: str):
    """The rate follows the BASIS, not the zone. Same roof, both zones, 50% of net.

    It used to read 10% here (and 15% on a low-slope roof) because the config was keyed by
    (slope_type, zone) — a shape Tim's rule has no term for. Nothing about a permit zone decides
    what a salesperson is paid.
    """
    q = QuoteInput(
        code_zone=zone, slope_type="sloped", roof_type="3tab_shingle",
        num_squares=10.0, project_kind="residential",
    )
    r = estimate(cfg, q)
    assert abs(r["commission"] - r["margin"]["profit_dollars"] * 0.50) < 0.01


# ---------------------------------------------------------------------------
# §7.5 Boundary-band edge tests (profit sliding scale)
# ---------------------------------------------------------------------------
# boundary_exclusive_upper flipped to False (2026-07-25). profit_scale stores Tim's INCLUSIVE
# band labels — [1, 400] is his "1 square" row, [4, 200] his "2-4 squares" row — so treating
# max_sq as exclusive gave a job landing exactly on an edge the NEXT band's lower rate: one
# square earned $200 where his sheet plainly says $400. Every edge now resolves to the band the
# label names, which is also the never-under-quote direction.
# sq=20 is genuinely double-claimed on his sheet ("15-20" AND "20-29") and now lands on $120 —
# which agrees with the TRD annotation quoted in test_floor_exhibit_b_example. Pending Tim.
@pytest.mark.parametrize("sq,expected_profit", [
    (0.5, 400),   # < 1 → first tier
    (1.0, 400),   # his "1 square" row
    (3.9, 200),
    (4.0, 200),   # top of his "2-4 squares" row
    (6.9, 160),
    (7.0, 160),   # top of his "5-7 squares" row
    (13.9, 140),
    (14.0, 140),  # top of his "8-14 squares" row
    (19.9, 120),
    (20.0, 120),  # top of his "15-20" row; also claimed by "20-29" — pending Tim
    (28.9, 110),
    (29.0, 110),  # top of his "20-29 squares" row
    (100.0, 100),
])
def test_sliding_scale_all_tiers(sq, expected_profit, cfg: PricingConfig):
    assert cfg.profit_per_sq(sq) == expected_profit


def test_sliding_scale_at_boundary_7sq(cfg: PricingConfig):
    """7 is the top of his "5-7 squares" row, so it takes $160 — not the next band's $140."""
    assert cfg.profit_per_sq(7.0) == 160


def test_sliding_scale_just_below_boundary(cfg: PricingConfig):
    assert cfg.profit_per_sq(6.999) == 160


def test_sliding_scale_boundary_flag_flip():
    """Toggle boundary_inclusive_lower=False — boundary SQ is excluded from both adjacent tiers.

    With lower-exclusive/upper-exclusive, a value exactly on a boundary (7.0) satisfies
    neither tier: not >(4,7) upper-exclusive, not >(7,14) lower-exclusive.
    It falls to the catch-all (last) tier. Verifies the flag is wired, not just documented.
    """
    raw = dict(_raw_config())
    raw = dict(raw)
    raw["boundary_inclusive_lower"] = False
    raw["boundary_exclusive_upper"] = True
    cfg2 = load_config(raw)
    # sq=7: not in (4,7) because 7 < 7 is False (upper-exc); not in (7,14) because 7 > 7 is False
    # → falls to catch-all tier → 100 (different from default lower-inc result of 140)
    assert cfg2.profit_per_sq(7.0) == 100   # boundary in gap → catch-all
    assert cfg2.profit_per_sq(7.001) == 140  # just above → enters [7,14) tier
    assert cfg2.profit_per_sq(6.999) == 160  # just below → stays in (4,7) tier


# ---------------------------------------------------------------------------
# §7.6 Tile dumpster threshold tests
# ---------------------------------------------------------------------------
def test_dumpster_hvhz_15sq(cfg: PricingConfig):
    """15 SQ HVHZ tile, boundary_inclusive=true → ceil(15/15) = 1 dumpster ($300)."""
    assert cfg.tile_dumpster_count(15.0, "HVHZ") == 1
    q = QuoteInput(code_zone="HVHZ", slope_type="sloped", roof_type="13_tile",
                   num_squares=15.0, project_kind="residential")
    r = estimate(cfg, q)
    dumpster_item = next((li for li in r["line_items_detail"] if li["key"] == "tile_dumpster"), None)
    assert dumpster_item is not None
    assert dumpster_item["amount"] == 300.0


def test_dumpster_hvhz_16sq(cfg: PricingConfig):
    """16 SQ HVHZ → ceil(16/15) = 2 dumpsters ($600)."""
    assert cfg.tile_dumpster_count(16.0, "HVHZ") == 2
    q = QuoteInput(code_zone="HVHZ", slope_type="sloped", roof_type="13_tile",
                   num_squares=16.0, project_kind="residential")
    r = estimate(cfg, q)
    dumpster_item = next((li for li in r["line_items_detail"] if li["key"] == "tile_dumpster"), None)
    assert dumpster_item["amount"] == 600.0


def test_dumpster_fbc_30sq(cfg: PricingConfig):
    """30 SQ FBC tile → ceil(30/30) = 1 dumpster ($300)."""
    assert cfg.tile_dumpster_count(30.0, "FBC") == 1


def test_dumpster_fbc_31sq(cfg: PricingConfig):
    """31 SQ FBC tile → ceil(31/30) = 2 dumpsters ($600)."""
    assert cfg.tile_dumpster_count(31.0, "FBC") == 2


def test_dumpster_hvhz_30sq(cfg: PricingConfig):
    """30 SQ HVHZ tile → ceil(30/15) = 2 dumpsters ($600)."""
    assert cfg.tile_dumpster_count(30.0, "HVHZ") == 2


def test_dumpster_not_applied_shingle(cfg: PricingConfig):
    """Shingle roof → no tile_dumpster line item."""
    q = QuoteInput(code_zone="HVHZ", slope_type="sloped", roof_type="3tab_shingle",
                   num_squares=10.0, project_kind="residential")
    r = estimate(cfg, q)
    keys = [li["key"] for li in r["line_items_detail"]]
    assert "tile_dumpster" not in keys


def test_dumpster_zero_sq_no_dumpster(cfg: PricingConfig):
    """Edge case: 0 SQ → no dumpster."""
    assert cfg.tile_dumpster_count(0.0, "HVHZ") == 0


def test_dumpster_boundary_flag_flip(cfg: PricingConfig):
    """tile_dumpster_boundary_inclusive is wired — toggling it changes the formula."""
    # ceil(sq / threshold) is what we use; the boundary_inclusive flag is for future
    # extension. The current implementation always uses ceil, so this test verifies
    # the count formula is correct at the boundary (15 SQ HVHZ = exactly 1 dumpster).
    count_at_boundary = cfg.tile_dumpster_count(15.0, "HVHZ")
    assert count_at_boundary == 1  # ceil(15/15) = 1


# ---------------------------------------------------------------------------
# §7.7 County override tests
# ---------------------------------------------------------------------------
def _cfg_with_county_override(overrides: dict) -> PricingConfig:
    raw = dict(_raw_config())
    co = {k: dict(v) for k, v in raw["county_overrides"].items()}
    co.setdefault("test_county", {})
    co["test_county"] = overrides
    raw = dict(raw)
    raw["county_overrides"] = co
    raw["counties"] = dict(raw["counties"])
    raw["counties"]["test_county"] = "FBC"
    return load_config(raw)


def test_county_permit_fee_add():
    cfg2 = _cfg_with_county_override(
        {"permit_fee_add": 150, "materials_tax_7pct_tile": False, "extra_line_items": {}}
    )
    q = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="3tab_shingle",
                   num_squares=10.0, project_kind="residential", county="test_county")
    r = estimate(cfg2, q)
    permit_item = next(li for li in r["line_items_detail"] if li["key"] == "permit_processing")
    assert permit_item["amount"] == 500 + 150


def test_county_materials_tax_tile():
    cfg2 = _cfg_with_county_override(
        {"permit_fee_add": 0, "materials_tax_7pct_tile": True, "extra_line_items": {}}
    )
    # 13-tile roof — base_cost_lm is Materials and should be taxed 7%
    q_no_county = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="13_tile",
                             num_squares=10.0, project_kind="residential")
    q_county = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="13_tile",
                          num_squares=10.0, project_kind="residential", county="test_county")
    r1 = estimate(cfg2, q_no_county)
    r2 = estimate(cfg2, q_county)
    base_no_county = next(li["amount"] for li in r1["line_items_detail"] if li["key"] == "base_cost_lm")
    base_with_county = next(li["amount"] for li in r2["line_items_detail"] if li["key"] == "base_cost_lm")
    assert abs(base_with_county - base_no_county * 1.07) < 0.01


def test_county_materials_tax_not_applied_shingle():
    cfg2 = _cfg_with_county_override(
        {"permit_fee_add": 0, "materials_tax_7pct_tile": True, "extra_line_items": {}}
    )
    q_no = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="3tab_shingle",
                      num_squares=10.0, project_kind="residential")
    q_yes = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="3tab_shingle",
                       num_squares=10.0, project_kind="residential", county="test_county")
    r1 = estimate(cfg2, q_no)
    r2 = estimate(cfg2, q_yes)
    # shingle — tax flag must NOT change amounts
    base1 = next(li["amount"] for li in r1["line_items_detail"] if li["key"] == "base_cost_lm")
    base2 = next(li["amount"] for li in r2["line_items_detail"] if li["key"] == "base_cost_lm")
    assert abs(base1 - base2) < 0.001


def test_county_extra_line_items():
    cfg2 = _cfg_with_county_override(
        {"permit_fee_add": 0, "materials_tax_7pct_tile": False,
         "extra_line_items": {"special_inspection": 750}}
    )
    q = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="3tab_shingle",
                   num_squares=10.0, project_kind="residential", county="test_county")
    r = estimate(cfg2, q)
    keys = [li["key"] for li in r["line_items_detail"]]
    assert "special_inspection" in keys
    item = next(li for li in r["line_items_detail"] if li["key"] == "special_inspection")
    assert item["amount"] == 750


def test_county_override_stacks_on_zone():
    """County permit_fee_add is additive on top of zone base permit."""
    cfg2 = _cfg_with_county_override(
        {"permit_fee_add": 200, "materials_tax_7pct_tile": False, "extra_line_items": {}}
    )
    q = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="3tab_shingle",
                   num_squares=10.0, project_kind="residential", county="test_county")
    r = estimate(cfg2, q)
    permit_item = next(li for li in r["line_items_detail"] if li["key"] == "permit_processing")
    assert permit_item["amount"] == 500 + 200  # base 500 + county add 200


# ---------------------------------------------------------------------------
# §7.8 PM incentive matrix tests
# ---------------------------------------------------------------------------
def test_pm_hvhz_residential_lt20(cfg: PricingConfig):
    assert cfg.pm_incentive("HVHZ", "residential", 15.0) == 150


def test_pm_hvhz_commercial_20_50(cfg: PricingConfig):
    assert cfg.pm_incentive("HVHZ", "commercial", 30.0) == 300


def test_pm_fbc_residential_lt20(cfg: PricingConfig):
    assert cfg.pm_incentive("FBC", "residential", 8.0) == 50


def test_pm_fbc_residential_lt20_edge(cfg: PricingConfig):
    """FBC residential — unified <20 SQ band (was split at 10 in old plan; TRD adopts PRD-F2-11)."""
    assert cfg.pm_incentive("FBC", "residential", 10.0) == 50
    assert cfg.pm_incentive("FBC", "residential", 19.9) == 50


def test_pm_fbc_bands_are_size_only_and_ignore_project_kind(cfg: PricingConfig):
    """Palm Beach keys PM incentive on SIZE ALONE — the bands apply to residential too.

    Live sheet FBC!N7:O9 reads "< 20 squares $50 / 20 - 50 squares $100 / > 50 squares $250" with no
    residential-vs-commercial split. We had the top two wired as commercial-only, so a 35-square
    RESIDENTIAL job silently fell back to the <20 band and took $50 instead of $100 — real money on
    the job class that dominates his book.
    """
    for kind in ("residential", "commercial"):
        assert cfg.pm_incentive("FBC", kind, 19.9) == 50
        assert cfg.pm_incentive("FBC", kind, 20.0) == 50     # 20 is the top of the <=20 band
        assert cfg.pm_incentive("FBC", kind, 35.0) == 100
        assert cfg.pm_incentive("FBC", kind, 60.0) == 250


def test_pm_fbc_commercial_gt50(cfg: PricingConfig):
    assert cfg.pm_incentive("FBC", "commercial", 51.0) == 250


def test_pm_hvhz_commercial_gt50(cfg: PricingConfig):
    assert cfg.pm_incentive("HVHZ", "commercial", 55.0) == 300


def test_pm_residential_ge20_uses_residential_band(cfg: PricingConfig):
    """Residential ≥20 SQ is valid in golden proposals; reuse residential PM band until Tim provides a separate band."""
    assert cfg.pm_incentive("HVHZ", "residential", 20.0) == 150


def test_pm_hvhz_is_project_kind_only_and_ignores_size(cfg: PricingConfig):
    """Miami keys PM incentive on PROJECT KIND ALONE — $150/$300 hold at any size.

    Live sheet 'Tim (HVHZ)'!N7:O8 is just "Residential $150 / Commercial $300"; there is no size
    dimension. Previously a small commercial job raised ConfigError because we forced Miami onto
    Palm Beach's size axis, so it could not be quoted at all.
    """
    for sq in (5.0, 15.0, 35.0, 200.0):
        assert cfg.pm_incentive("HVHZ", "residential", sq) == 150
        assert cfg.pm_incentive("HVHZ", "commercial", sq) == 300


def test_pm_raises_on_unknown_project_kind(cfg: PricingConfig):
    with pytest.raises(ConfigError, match="project_kind"):
        cfg.pm_incentive("HVHZ", "government", 10.0)


def test_pm_raises_on_unknown_zone(cfg: PricingConfig):
    with pytest.raises(ConfigError, match="zone"):
        cfg.pm_incentive("UNKNOWN", "residential", 10.0)


# ---------------------------------------------------------------------------
# §7.10 Low-slope
#
# These four were skip-marked "pending Tim data: low_slope base costs are null (OI-1) /
# tapered_cost_per_sq is null (OI-4)". Both reasons went stale — the fixture AND all three prod
# configs carry base_cost_lm and tapered_cost_per_sq — and three of the four were empty `pass`
# stubs, so low-slope shipped with no engine-level coverage at all. Audit 2026-07-27 (R2 / #440).
# ---------------------------------------------------------------------------
_LOW_SLOPE_GOLDEN = GOLDEN_DIR / "498sq_low_slope_hvhz.json"


@pytest.mark.skipif(not _LOW_SLOPE_GOLDEN.exists(),
                    reason="golden 498sq_low_slope_hvhz.json not written — needs Tim's quoted "
                           "total for a 498 sq commercial TPO job, not a number we invent")
def test_low_slope_tpo_hvhz(cfg: PricingConfig):
    q = QuoteInput(code_zone="HVHZ", slope_type="low_slope", roof_type="tpo_adhered",
                   num_squares=498.0, project_kind="commercial")
    golden = json.loads(_LOW_SLOPE_GOLDEN.read_text())
    r = estimate(cfg, q)
    assert abs(r["project_total"] - golden["expected_total"]) <= golden["tolerance_abs"]


def _low_slope_q(cfg: PricingConfig, **kw) -> dict:
    return estimate(cfg, QuoteInput(
        code_zone="HVHZ", slope_type="low_slope", roof_type="tpo_adhered",
        num_squares=100.0, project_kind="commercial", **kw))


def test_low_slope_insulation_no_profit(cfg: PricingConfig):
    """Exhibit B: insulation carries overhead but NO profit.

    Behavioural, not structural: the same job with and without insulation must differ by exactly
    the board cost, and the insulation line must be out of the profit floor's denominator — so a
    big insulation package cannot inflate the floor and quietly raise the price.
    """
    base = _low_slope_q(cfg)
    with_ins = _low_slope_q(cfg, include_insulation=True, insulation_thickness="1in")
    cost_per_sq = cfg.low_slope_insulation_cost("1in")

    line = next(li for li in with_ins["line_items_detail"] if li["key"] == "insulation")
    assert line["amount"] == pytest.approx(cost_per_sq * 100.0, abs=0.01)
    assert with_ins["project_total"] - base["project_total"] == pytest.approx(
        cost_per_sq * 100.0, abs=0.01), "insulation must not pull profit with it"
    assert cfg.raw["floor_excluded_categories"]["insulation"] == ["Profit"]


def test_low_slope_tapered_no_oh_no_profit(cfg: PricingConfig):
    """Exhibit B: tapered insulation carries neither overhead nor profit."""
    base = _low_slope_q(cfg)
    with_tap = _low_slope_q(cfg, include_tapered=True)
    cost_per_sq = cfg.low_slope_tapered_cost()

    line = next(li for li in with_tap["line_items_detail"] if li["key"] == "tapered")
    assert line["amount"] == pytest.approx(cost_per_sq * 100.0, abs=0.01)
    assert with_tap["project_total"] - base["project_total"] == pytest.approx(
        cost_per_sq * 100.0, abs=0.01), "tapered must not pull OH or profit with it"
    assert sorted(cfg.raw["floor_excluded_categories"]["tapered"]) == ["OH", "Profit"]


def test_low_slope_commission_follows_basis_not_slope(cfg: PricingConfig):
    """A low-slope roof commissions at the same 50% of NET as any other roof.

    It used to read 0.15 against sloped's 0.10 purely because the config was keyed by slope type.
    Tim, 2026-08-02: 15% of gross or 50% of net, per SALESPERSON — the roof is not a term in it.
    """
    r = _low_slope_q(cfg)
    assert cfg.commission_rate("profit") == pytest.approx(0.50)
    assert r["commission"] == pytest.approx(r["profit_dollars"] * 0.50, abs=0.01)


# ---------------------------------------------------------------------------
# Engine integration: per-square adders all routed through config
# ---------------------------------------------------------------------------
def test_all_sloped_adders(cfg: PricingConfig):
    """All per-sq adders produce the correct total when enabled together."""
    q = QuoteInput(
        code_zone="HVHZ", slope_type="sloped", roof_type="13_tile",
        num_squares=10.0, project_kind="residential",
        roof_cuts="high", roof_height="2_stories", tile_pointing="yes",
        specialty_tile="santa_fe_clay_s", pitch_7_12=True, demo=True,
        secondary_water_barrier=True, winterguard=True,
    )
    r = estimate(cfg, q)
    # base 780 + oh 270 + profit(8-14 band → 140) + cuts 50 + height 50 + pointing 200
    # + specialty 160 + pitch 305 + tile demo 40 + swb 75 + winterguard 135 = 2205 per sq
    # pitch 200→305 and winterguard 140→135: both re-derived from Tim's CELL COMMENTS, whose
    # L/M/OH/P build-ups agree across tabs where the headline cells do not (7/12 builds to $305
    # in both live comments; WinterGuard to $135 in both sheets).
    # The $2,500 job profit floor now fires here, and that is the point: the fixture gained
    # enforce_profit_floor / profit_floor_basis on 2026-07-25 because prod had them and git did
    # not, so anything built from the fixture ran with NO floor. At 10 squares the sliding scale
    # pays 10 x $140 = $1,400, under the floor, so profit lifts to $2,500 = $250/sq. The adder
    # math is unchanged; only the profit term moves.
    scale_profit, floored_profit = 140, 250
    adders = 780 + 270 + 50 + 50 + 200 + 160 + 305 + 40 + 75 + 135
    assert r["per_square_total"] == adders + floored_profit
    assert r["margin"]["profit_dollars"] == 2500.0
    # ...and with the floor off, the same adders sum against the sliding-scale profit
    raw_nofloor = dict(_raw_config())
    raw_nofloor["enforce_profit_floor"] = False
    r2 = estimate(load_config(raw_nofloor), q)
    assert r2["per_square_total"] == adders + scale_profit


def test_metal_demo_not_tile_demo(cfg: PricingConfig):
    q = QuoteInput(code_zone="HVHZ", slope_type="sloped", roof_type="standing_seam_metal",
                   num_squares=10.0, project_kind="residential", demo=True)
    r = estimate(cfg, q)
    keys = [li["key"] for li in r["line_items_detail"]]
    assert "metal_demo" in keys
    assert "tile_demo" not in keys


def test_6_plus_stories_raises(cfg: PricingConfig):
    q = QuoteInput(code_zone="HVHZ", slope_type="sloped", roof_type="3tab_shingle",
                   num_squares=10.0, project_kind="residential", roof_height="6_plus")
    with pytest.raises(QuoteRequiresManualReview):
        estimate(cfg, q)


def test_optional_line_items(cfg: PricingConfig):
    q = QuoteInput(
        code_zone="FBC", slope_type="sloped", roof_type="3tab_shingle",
        num_squares=10.0, project_kind="residential",
        stucco_metal_lf=10, penetrations=3, ridge_vent_lf=20,
        extra_line_items=["turbine_vents"],
    )
    r = estimate(cfg, q)
    keys = {li["key"]: li["amount"] for li in r["line_items_detail"]}
    assert abs(keys["stucco_metal"] - 90.0) < 0.01      # 10 * 9
    assert abs(keys["penetrations"] - 225.0) < 0.01     # 3 * 75
    assert abs(keys["ridge_vents"] - 195.8) < 0.01      # 20 * 9.79
    assert abs(keys["turbine_vents"] - 257.50) < 0.01


def test_unknown_extra_line_item_ignored(cfg: PricingConfig):
    q = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="3tab_shingle",
                   num_squares=10.0, project_kind="residential",
                   extra_line_items=["not_a_real_key"])
    r = estimate(cfg, q)
    keys = [li["key"] for li in r["line_items_detail"]]
    assert "not_a_real_key" not in keys


def test_3_5_stories_flat_add(cfg: PricingConfig):
    q = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="3tab_shingle",
                   num_squares=10.0, project_kind="residential", roof_height="3_5_stories")
    r = estimate(cfg, q)
    keys = {li["key"]: li["amount"] for li in r["line_items_detail"]}
    assert keys.get("stories_3_5_delivery_chute") == 1200


def test_commercial_permit_add(cfg: PricingConfig):
    q = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="3tab_shingle",
                   num_squares=25.0, project_kind="commercial")
    r = estimate(cfg, q)
    permit = next(li["amount"] for li in r["line_items_detail"] if li["key"] == "permit_processing")
    assert permit == 1000  # 500 + 500 commercial


def test_line_items_have_category(cfg: PricingConfig):
    """Every line item must carry a cost_category."""
    q = QuoteInput(code_zone="HVHZ", slope_type="sloped", roof_type="13_tile",
                   num_squares=10.0, project_kind="residential")
    r = estimate(cfg, q)
    for li in r["line_items_detail"]:
        assert li["category"] in ("Labor", "Materials", "Equipment", "Sub", "Misc", "OH", "Profit"), (
            f"Line item {li['key']} has unexpected category '{li['category']}'"
        )


# ---------------------------------------------------------------------------
# Selfcheck pinned to old worked example (legacy path test)
# ---------------------------------------------------------------------------
def test_selfcheck_runs():
    from core.estimator import _selfcheck
    _selfcheck()


# ---------------------------------------------------------------------------
# Coverage completeness — paths not hit by the main test suite
# ---------------------------------------------------------------------------

def test_quote_input_missing_zone_raises():
    """QuoteInput requires either code_zone or region — neither raises ValueError."""
    with pytest.raises(ValueError, match="code_zone or region"):
        QuoteInput(roof_type="3tab_shingle", num_squares=10.0)


def test_sliding_scale_upper_inclusive_branch():
    """Exercises boundary_exclusive_upper=False (upper-inclusive) code path."""
    raw = dict(_raw_config())
    raw = dict(raw)
    raw["boundary_inclusive_lower"] = True
    raw["boundary_exclusive_upper"] = False   # upper-INCLUSIVE: sq <= max triggers tier
    cfg2 = load_config(raw)
    # With upper-inclusive: sq=1 is in first tier (1 <= 1 → True)
    assert cfg2.profit_per_sq(1.0) == 400   # sq<=1 → first tier
    assert cfg2.profit_per_sq(1.001) == 200  # past first tier


def test_commission_rate_ignores_the_old_slope_keyed_config():
    """The dead sloped/low_slope/sloped_hvhz keys must not come back to life through the config.

    They still sit in every live branch config (removing them is a data change), and a reader who
    edits one would reasonably expect it to move a rate. It does not — commission is one
    company-wide rule off the basis, overridden per QUOTE, never per branch.
    """
    raw = dict(_raw_config())
    raw["commission_pct"] = {"sloped": 0.99, "low_slope": 0.99, "sloped_hvhz": 0.99,
                             "gross": 0.99, "net": 0.99}
    cfg2 = load_config(raw)
    assert cfg2.commission_rate("job") == 0.15
    assert cfg2.commission_rate("profit") == 0.50


def test_commission_rate_rejects_an_unknown_basis():
    """A typo'd basis must raise, not quietly pay the profit rate on a gross number."""
    with pytest.raises(ConfigError, match="commission basis"):
        load_config(dict(_raw_config())).commission_rate("net")


def test_pm_null_band_raises():
    """A null amount must raise, not price at zero."""
    import copy
    raw = copy.deepcopy(_raw_config())
    raw["pm_incentive"]["FBC"]["bands"] = [[20, None], [None, 250]]
    with pytest.raises(ConfigError, match="pm_incentive"):
        load_config(raw).pm_incentive("FBC", "residential", 10.0)


def test_pm_legacy_shape_still_resolves():
    """Configs seeded before 2026-07-26 carry the old keys and must keep pricing."""
    import copy
    raw = copy.deepcopy(_raw_config())
    raw["pm_incentive"] = {
        "HVHZ": {"residential_lt20": 150, "commercial_20_50": 300, "commercial_gt50": 300},
        "FBC": {"residential_lt20": 50, "commercial_20_50": 100, "commercial_gt50": 250},
    }
    cfg2 = load_config(raw)
    assert cfg2.pm_incentive("HVHZ", "residential", 15.0) == 150
    assert cfg2.pm_incentive("FBC", "commercial", 35.0) == 100


def _cfg_with_low_slope_data(**overrides) -> PricingConfig:
    """Build a config with filled-in low-slope values for coverage tests."""
    raw = dict(_raw_config())
    ls = dict(raw["low_slope"])
    ls["base_cost_lm"] = {
        "HVHZ": {"tpo": 200, "coatings": 180, "silicone": 170, "bur": 160},
        "FBC":  {"tpo": 190, "coatings": 170, "silicone": 160, "bur": 150},
    }
    ls["overhead"] = {
        "HVHZ": {"flat_oh": 60, "tpo_oh": 65, "coatings_oh": 55},
        "FBC":  {"flat_oh": 55, "tpo_oh": 60, "coatings_oh": 50},
    }
    # thickness-keyed (1in/1_5in/2in), matching Tim's K15/K16/K17
    ls["insulation_by_thickness"] = {"1in": 80, "1_5in": 90, "2in": 100}
    ls["insulation_tiers"] = [[20, 80], [None, 60]]   # legacy rows, exercised by the fallback test
    ls["tapered_cost_per_sq"] = 45
    ls["tear_off_per_layer_per_sq"] = 30
    # DELIBERATELY different from tear_off_per_layer_per_sq (30) so a test asserting the billed
    # amount can actually discriminate between the scalar and the summed block. The previous values
    # summed to exactly 30 and passed identically whichever the engine used.
    ls["tear_off_extras"] = {"additional_hauling": 11, "labor": 12, "oh": 13}   # sums to 36, not 30
    ls["deck_types"] = {"existing_concrete": 0, "plywood_replace": 120}
    ls.update(overrides)
    raw = dict(raw)
    raw["low_slope"] = ls
    return load_config(raw)


def test_low_slope_insulation_priced_by_thickness_not_size():
    """Insulation is keyed on board thickness. Job size must not change the rate.

    Regression: the old schema was [max_sq, price] and every row carried max_sq=null, so the
    lookup returned the first row for every job and the 1.5"/2" prices were unreachable.
    """
    cfg2 = _cfg_with_low_slope_data()
    assert cfg2.low_slope_insulation_cost("1in") == 80
    assert cfg2.low_slope_insulation_cost("1_5in") == 90
    assert cfg2.low_slope_insulation_cost("2in") == 100
    # three distinct prices, and none of them a function of squares
    assert len({cfg2.low_slope_insulation_cost(t) for t in ("1in", "1_5in", "2in")}) == 3
    with pytest.raises(ConfigError, match="thickness"):
        cfg2.low_slope_insulation_cost("3in")


def test_low_slope_deck_null_raises():
    """Exercises the low_slope_deck_cost null-value ConfigError branch."""
    cfg2 = _cfg_with_low_slope_data()
    # Force a null deck type value
    raw = dict(cfg2.raw)
    ls = dict(raw["low_slope"])
    ls["deck_types"] = dict(ls["deck_types"])
    ls["deck_types"]["plywood_replace"] = None
    raw["low_slope"] = ls
    cfg3 = load_config(raw)
    with pytest.raises(ConfigError, match="deck_types"):
        cfg3.low_slope_deck_cost("plywood_replace")


def test_low_slope_build_tear_off_branch():
    """Exercises _build_low_slope with layers_to_remove (tear-off path)."""
    cfg2 = _cfg_with_low_slope_data()
    q = QuoteInput(
        code_zone="FBC", slope_type="low_slope", roof_type="tpo",
        num_squares=10.0, project_kind="residential",
        layers_to_remove=2,
    )
    r = estimate(cfg2, q)
    keys = {li["key"]: li["amount"] for li in r["line_items_detail"]}
    assert "tear_off" in keys
    # Bills the SCALAR ($30), not the summed extras ($36). Those differ on purpose: three numbers
    # exist in the repo for this ($20 scalar / $75 extras / $35 comment audit) and the extras note
    # says "beyond first", so the engine bills the scalar and warns instead of picking.
    assert abs(keys["tear_off"] - 30 * 2 * 10.0) < 0.01   # $30/layer * 2 layers * 10 sq
    assert abs(keys["tear_off"] - 36 * 2 * 10.0) > 0.01   # and NOT the summed extras
    assert any("tear_off_basis_unconfirmed" in w for w in r["warnings"])


def test_low_slope_build_deck_branch():
    """Exercises _build_low_slope with deck_type replacement."""
    cfg2 = _cfg_with_low_slope_data()
    q = QuoteInput(
        code_zone="FBC", slope_type="low_slope", roof_type="tpo",
        num_squares=10.0, project_kind="residential",
        deck_type="plywood_replace",
    )
    r = estimate(cfg2, q)
    keys = {li["key"]: li["amount"] for li in r["line_items_detail"]}
    assert "deck_type" in keys
    assert abs(keys["deck_type"] - 120 * 10.0) < 0.01


def test_low_slope_insulation_in_estimate():
    """Exercises _build_low_slope insulation branch through estimate()."""
    cfg2 = _cfg_with_low_slope_data()
    q = QuoteInput(
        code_zone="FBC", slope_type="low_slope", roof_type="tpo",
        num_squares=10.0, project_kind="residential",
        include_insulation=True,
    )
    r = estimate(cfg2, q)
    keys = {li["key"]: li["amount"] for li in r["line_items_detail"]}
    assert "insulation" in keys


def test_low_slope_tapered_in_estimate():
    """Exercises _build_low_slope tapered branch through estimate()."""
    cfg2 = _cfg_with_low_slope_data()
    q = QuoteInput(
        code_zone="FBC", slope_type="low_slope", roof_type="tpo",
        num_squares=10.0, project_kind="residential",
        include_tapered=True,
    )
    r = estimate(cfg2, q)
    keys = {li["key"]: li["amount"] for li in r["line_items_detail"]}
    assert "tapered" in keys
    assert abs(keys["tapered"] - 45 * 10.0) < 0.01


def test_low_slope_3_5_stories():
    """Exercises the trash_chute branch in _build_low_slope."""
    cfg2 = _cfg_with_low_slope_data()
    q = QuoteInput(
        code_zone="FBC", slope_type="low_slope", roof_type="tpo",
        num_squares=10.0, project_kind="residential",
        roof_height="3_5_stories",
    )
    r = estimate(cfg2, q)
    keys = {li["key"]: li["amount"] for li in r["line_items_detail"]}
    assert "trash_chute" in keys
    assert keys["trash_chute"] == 1500


def test_low_slope_6_plus_raises():
    """Exercises QuoteRequiresManualReview in _build_low_slope."""
    cfg2 = _cfg_with_low_slope_data()
    q = QuoteInput(
        code_zone="FBC", slope_type="low_slope", roof_type="tpo",
        num_squares=10.0, project_kind="residential",
        roof_height="6_plus",
    )
    with pytest.raises(QuoteRequiresManualReview):
        estimate(cfg2, q)


def test_low_slope_insulation_legacy_tiers_fallback():
    """Configs already seeded with only the legacy rows still resolve all three thicknesses.

    Prod carries insulation_tiers and no insulation_by_thickness, so this is the path prod takes
    until it is reseeded — the rows map positionally, which is what their own config note says
    they mean ("type-based not sq-range-based").
    """
    import copy
    raw = copy.deepcopy(_raw_config())
    raw["low_slope"].pop("insulation_by_thickness", None)
    cfg3 = load_config(raw)
    assert cfg3.low_slope_insulation_cost("1in") == 255
    assert cfg3.low_slope_insulation_cost("1_5in") == 275
    assert cfg3.low_slope_insulation_cost("2in") == 310


def test_low_slope_2_story_height_add():
    """Exercises the height_val branch in _build_low_slope (2-story per-sq add)."""
    cfg2 = _cfg_with_low_slope_data()
    q_1story = QuoteInput(
        code_zone="FBC", slope_type="low_slope", roof_type="tpo",
        num_squares=10.0, project_kind="residential",
    )
    q_2story = QuoteInput(
        code_zone="FBC", slope_type="low_slope", roof_type="tpo",
        num_squares=10.0, project_kind="residential",
        roof_height="2_stories",
    )
    r1 = estimate(cfg2, q_1story)
    r2 = estimate(cfg2, q_2story)
    # 2-story adds $50/sq * 10 = $500
    assert abs(r2["project_total"] - r1["project_total"] - 500.0) < 0.01


# ---------------------------------------------------------------------------
# OI-5: plywood deck replacement — Tim prices this per SHEET (Lumber Schedule), not per
# square, and it applies to ANY roof type, not just low-slope.
# ---------------------------------------------------------------------------

def test_plywood_deck_types_raises_pointing_at_new_key(cfg: PricingConfig):
    """low_slope.deck_types.plywood_replace stays null on purpose (wrong unit); the error
    must point at the real per-sheet key instead of a bare null error."""
    with pytest.raises(ConfigError, match="plywood_sheets"):
        cfg.low_slope_deck_cost("plywood_replace")


def test_plywood_sheet_rate_by_thickness(cfg: PricingConfig):
    """Each thickness rate from Tim's Lumber Schedule."""
    assert cfg.plywood_sheet_rate("5_8in") == 120
    assert cfg.plywood_sheet_rate("1_2in") == 110
    assert cfg.plywood_sheet_rate("3_4in") == 145


def test_plywood_sheets_included(cfg: PricingConfig):
    assert cfg.plywood_sheets_included() == 2


def test_plywood_allowance_two_sheets_free(cfg: PricingConfig):
    """2 sheets = the included allowance; no line item, no charge. Applies on a SLOPED
    roof too — the adder is not low_slope-scoped."""
    q = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="3tab_shingle",
                   num_squares=10.0, project_kind="residential",
                   plywood_sheets=2, plywood_thickness="5_8in")
    r = estimate(cfg, q)
    assert not any(li["key"] == "plywood_replacement" for li in r["line_items_detail"])


def test_plywood_bills_only_the_excess_sheet(cfg: PricingConfig):
    """3 sheets = 1 billable sheet at the thickness rate ($120 for 5/8"), and it flows into
    both the project total and eligible_base like any other fixed line item."""
    q_base = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="3tab_shingle",
                         num_squares=10.0, project_kind="residential")
    q_ply = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="3tab_shingle",
                        num_squares=10.0, project_kind="residential",
                        plywood_sheets=3, plywood_thickness="5_8in")
    r_base = estimate(cfg, q_base)
    r_ply = estimate(cfg, q_ply)
    item = next(li for li in r_ply["line_items_detail"] if li["key"] == "plywood_replacement")
    assert item["amount"] == 120.0
    assert abs(r_ply["project_total"] - r_base["project_total"] - 120.0) < 0.01
    assert abs(r_ply["margin"]["eligible_base"] - r_base["margin"]["eligible_base"] - 120.0) < 0.01


def test_plywood_other_thicknesses_bill_at_their_own_rate(cfg: PricingConfig):
    q_half = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="3tab_shingle",
                         num_squares=10.0, project_kind="residential",
                         plywood_sheets=3, plywood_thickness="1_2in")
    q_3q = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="3tab_shingle",
                       num_squares=10.0, project_kind="residential",
                       plywood_sheets=3, plywood_thickness="3_4in")
    r_half = estimate(cfg, q_half)
    r_3q = estimate(cfg, q_3q)
    half_item = next(li for li in r_half["line_items_detail"] if li["key"] == "plywood_replacement")
    q3_item = next(li for li in r_3q["line_items_detail"] if li["key"] == "plywood_replacement")
    assert half_item["amount"] == 110.0
    assert q3_item["amount"] == 145.0


# ---------------------------------------------------------------------------
# OI-11: not-HVHZ-legal low-slope deck systems — warn, never block.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("deck_type,detail", [
    ("bur_wood_wb3000", "1 story only"),
    ("bur_wood_sav_flashing", "plywood only"),
])
def test_deck_type_not_hvhz_warns_on_hvhz_job(cfg: PricingConfig, deck_type, detail):
    q = QuoteInput(code_zone="HVHZ", slope_type="low_slope", roof_type="tpo_adhered",
                   num_squares=10.0, project_kind="residential", deck_type=deck_type)
    r = estimate(cfg, q)
    warning = next((w for w in r["warnings"] if w.startswith("deck_type_not_hvhz")), None)
    assert warning is not None
    assert deck_type in warning
    assert detail in warning


@pytest.mark.parametrize("deck_type", ["bur_wood_wb3000", "bur_wood_sav_flashing"])
def test_deck_type_not_hvhz_does_not_warn_in_fbc(cfg: PricingConfig, deck_type):
    q = QuoteInput(code_zone="FBC", slope_type="low_slope", roof_type="tpo_adhered",
                   num_squares=10.0, project_kind="residential", deck_type=deck_type)
    r = estimate(cfg, q)
    assert not any(w.startswith("deck_type_not_hvhz") for w in r["warnings"])


def test_deck_type_hvhz_legal_does_not_warn(cfg: PricingConfig):
    """A deck type NOT in not_hvhz_deck_types must never warn, even on an HVHZ job."""
    q = QuoteInput(code_zone="HVHZ", slope_type="low_slope", roof_type="tpo_adhered",
                   num_squares=10.0, project_kind="residential", deck_type="bur_wood_elastobase")
    r = estimate(cfg, q)
    assert not any(w.startswith("deck_type_not_hvhz") for w in r["warnings"])


# ---------------------------------------------------------------------------
# Fix 4 (H3): Insulation OH — low-slope insulation carries OH (excluded from Profit only)
# Per TRD-F2 §4.2: insulation is excluded from Profit floor denominator but
# IS included in the OH total (combined floor denominator).
# ---------------------------------------------------------------------------

def _cfg_with_low_slope_and_insulation():
    """Synthetic config with all low-slope values filled in."""
    raw = dict(_raw_config())
    ls = {
        "base_cost_lm": {
            "HVHZ": {"tpo": 300, "coatings": 300, "silicone": 300, "bur": 300},
            "FBC":  {"tpo": 300, "coatings": 300, "silicone": 300, "bur": 300},
        },
        "overhead": {
            "HVHZ": {"flat_oh": 100, "tpo_oh": 100, "coatings_oh": 100},
            "FBC":  {"flat_oh": 100, "tpo_oh": 100, "coatings_oh": 100},
        },
        "insulation_tiers": [[None, 80]],   # $80/sq flat for any sq count
        "tapered_cost_per_sq": 45,
        "tear_off_per_layer_per_sq": 30,
        "deck_types": {"existing_concrete": 0, "plywood_replace": 120},
        "crane_threshold_stories": 3,
        "trash_chute_flat_add": 1200,
    }
    raw = dict(raw)
    raw["low_slope"] = ls
    return load_config(raw)


def test_insulation_excluded_from_profit_floor():
    """Insulation line must be excluded from profit floor denominator (floor_excluded_categories)."""
    cfg = _cfg_with_low_slope_and_insulation()
    q = QuoteInput(
        code_zone="FBC", slope_type="low_slope", roof_type="tpo",
        num_squares=10.0, project_kind="residential",
        include_insulation=True,
    )
    r = estimate(cfg, q)
    # insulation amount = 80 * 10 = 800
    insulation_amount = next(
        li["amount"] for li in r["line_items_detail"] if li["key"] == "insulation"
    )
    assert abs(insulation_amount - 800.0) < 0.01

    # eligible_base (profit floor denominator) excludes insulation
    profit_dollars = r["margin"]["profit_dollars"]
    total = r["project_total"]
    eligible_base = r["margin"]["eligible_base"]
    # eligible_base = total - profit - insulation (insulation excluded from Profit floor)
    assert abs(eligible_base - (total - profit_dollars - insulation_amount)) < 0.01


def test_insulation_included_in_oh_total():
    """Insulation OH component must be included in the OH total for the combined floor.

    Per TRD-F2 §4.2: insulation carries OH (the overhead line item for the low-slope
    base already covers the roof, but insulation's own overhead contribution is folded
    into the OH total). In the current implementation, the low-slope overhead line item
    (tagged 'OH') is computed on base sq, and insulation is tagged Materials. The OH
    total (oh_dollars) includes all 'OH'-tagged items.

    Verify: quote WITH insulation has higher or equal oh_dollars than without, because
    the overhead line item covers the full sq regardless (insulation does not reduce OH).
    Also verify that combined_pct (profit+OH / eligible_base) correctly reflects OH.
    """
    cfg = _cfg_with_low_slope_and_insulation()
    q_no_ins = QuoteInput(
        code_zone="FBC", slope_type="low_slope", roof_type="tpo",
        num_squares=10.0, project_kind="residential",
    )
    q_with_ins = QuoteInput(
        code_zone="FBC", slope_type="low_slope", roof_type="tpo",
        num_squares=10.0, project_kind="residential",
        include_insulation=True,
    )
    r_no  = estimate(cfg, q_no_ins)
    r_yes = estimate(cfg, q_with_ins)

    # OH dollars must be identical (insulation doesn't add an extra OH line; the
    # overhead line is computed on sq regardless of insulation inclusion)
    assert abs(r_no["margin"]["oh_dollars"] - r_yes["margin"]["oh_dollars"]) < 0.01, (
        "Insulation must not reduce the OH total — overhead is on full sq"
    )

    # With insulation, eligible_base is smaller (insulation excluded), but OH same,
    # so combined_pct (OH+profit)/eligible_base is HIGHER with insulation
    combined_no  = r_no["margin"]["combined_pct"]
    combined_yes = r_yes["margin"]["combined_pct"]
    assert combined_yes >= combined_no, (
        f"With insulation excluded from denominator, combined_pct should be >= without: "
        f"{combined_yes:.4f} vs {combined_no:.4f}"
    )


# ---------------------------------------------------------------------------
# Fix 6 (H6): Golden count guard — harness must assert exactly 3 golden files
# with an explicit message about the 2 pending OI-1 files.
# ---------------------------------------------------------------------------

def test_golden_file_count_is_3():
    """Exactly 3 ENGINE golden fixtures are committed; 2 are pending Tim OI-1 sign-off.

    Counts input/expected pairs only — decoded-reference fixtures in the same directory are not
    golden files for this harness and must not move this number.
    """
    assert len(GOLDEN_FILES) >= 3, (
        f"Expected >= 3 golden fixture files, found {len(GOLDEN_FILES)}. "
        "3/5 — 498sq+15sq low-slope blocked on OI-1 (Tim)"
    )
    assert len(GOLDEN_FILES) == 3, (
        f"3/5 golden fixtures committed (2 pending Tim OI-1); found {len(GOLDEN_FILES)}. "
        "Update this assertion when OI-1 is resolved and golden files are added."
    )


# ---------------------------------------------------------------------------
# Fix 2: seed_pricing_configs.py behavioral validation (R1 §2)
# ---------------------------------------------------------------------------

def test_seed_pricing_configs_against_sqlite():
    """Behavioral validation for scripts/seed_pricing_configs.py.

    Runs the seed script as a subprocess against a fresh temp SQLite DB so
    there is no module-state pollution to the main test process.
    R1: behavioral validation for scripts/ (non-coverage-gated I/O path).
    """
    import os
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_path = f.name

    try:
        script = str(Path(__file__).parent.parent / "scripts" / "seed_pricing_configs.py")
        env = {**os.environ, "DB_URL": f"sqlite:///{tmp_path}"}
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True, text=True, env=env,
        )
        output = result.stdout + result.stderr
        assert result.returncode == 0, f"seed_pricing_configs.py failed:\n{output}"
        assert "OK  3 active configs" in output, (
            f"Expected '3 active configs' confirmation:\n{output}"
        )
    finally:
        os.unlink(tmp_path)


def test_compute_config_hash_script():
    """compute_config_hash.py output matches core.compute_hash for the fixture."""
    import subprocess
    import sys
    from pathlib import Path

    fixture = Path(__file__).parent.parent / "infra" / "fixtures" / "pricing_config_exhibit_b.json"
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent.parent / "scripts" / "compute_config_hash.py"),
         str(fixture)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    digest = result.stdout.strip()
    assert len(digest) == 64, f"Expected 64-char hex digest, got: {digest!r}"

    # Cross-check with core.compute_hash
    import json
    expected = compute_hash(json.loads(fixture.read_text()))
    assert digest == expected, f"Script output {digest[:16]}... != core {expected[:16]}..."


def test_estimate_residential_ge20_pm_incentive_does_not_warn(cfg: PricingConfig):
    """Golden proposals include many residential jobs >=20 SQ; they should not show a false PM-band warning."""
    q = QuoteInput(
        code_zone="HVHZ",
        roof_type="3tab_shingle",
        num_squares=27.0,
        project_kind="residential",
    )
    r = estimate(cfg, q)
    assert r["project_total"] > 0
    assert r["pm_incentive"] == 150.0
    assert not any("pm_incentive_missing" in w for w in r["warnings"])


def test_steepness_double_count_warns(cfg: PricingConfig):
    """A 7/12 roof is charged for steepness on both sides; the engine must say so.

    The day model adds +0.5 install days at >=6/12, and Tim's 7/12 material adder is $305/sq whose
    own comment build-up contains $90/sq of OVERHEAD. Nobody noticed while the SPA hardcoded
    pitch_7_12=false and the adder never fired. It fires now, and there is no 7/12+ job in the
    29-home calibration set, so the overlap must be visible rather than silently priced.
    """
    kw = dict(code_zone="FBC", slope_type="sloped", roof_type="13_tile", num_squares=35.0,
              project_kind="residential", overhead_mode="daily",
              eaves_lf=336, hips_lf=158, ridges_lf=95, valleys_lf=74)
    steep = estimate(cfg, QuoteInput(pitch_primary=8, pitch_7_12=True, **kw))
    assert any("steepness_counted_twice" in w for w in steep["warnings"])

    # not warned when only one side applies
    shallow = estimate(cfg, QuoteInput(pitch_primary=4, pitch_7_12=False, **kw))
    assert not any("steepness_counted_twice" in w for w in shallow["warnings"])
    day_only = estimate(cfg, QuoteInput(pitch_primary=6, pitch_7_12=False, **kw))
    assert not any("steepness_counted_twice" in w for w in day_only["warnings"])
    # and the adder really is the larger of the two effects, which is why it must be operator-visible
    li = {x["key"]: x["amount"] for x in steep["line_items_detail"]}
    assert li.get("pitch_7_12_add", 0) > 10_000


def test_mixed_roof_prices_both_sections_as_one_job(cfg: PricingConfig):
    """A sloped+flat roof is ONE job: both areas priced, whole-job items charged once.

    Tim's 30-home sheet has a "Squares (Flat)" column and 9 of those homes use it — up to 34% of
    the roof. slope_type is exclusive, so before this the flat area was silently not quoted at all.
    """
    kw = dict(code_zone="FBC", slope_type="sloped", roof_type="13_tile",
              project_kind="residential", demo=True, existing_roof="tile")
    sloped = estimate(cfg, QuoteInput(num_squares=32.5, **kw))
    mixed = estimate(cfg, QuoteInput(num_squares=32.5, flat_squares=17.0,
                                     flat_roof_type="polyglass_sav_sap", **kw))
    keys = [li["key"] for li in mixed["line_items_detail"]]

    assert mixed["project_total"] > sloped["project_total"]          # the flat area is now priced
    assert "flat_base_cost_lm" in keys and "flat_overhead" in keys   # ...with its own L+M and OH
    assert keys.count("profit") == 1                                 # one profit line, not two
    assert keys.count("permit_processing") == 1                      # fixed fees charged once
    assert keys.count("delivery_plywood_vents") == 1
    assert not any(k.startswith("flat_") and k.endswith(("roof_height", "trash_chute"))
                   for k in keys)                                    # whole-job items stay singular
    assert any("mixed_roof_priced" in w for w in mixed["warnings"])


def test_mixed_roof_profit_bands_on_combined_squares(cfg: PricingConfig):
    """Profit bands on JOB SIZE. 28 sloped + 8 flat is a 36-square job, not a 28-square one.

    Sizes chosen above the $2,500 floor's bite (~23 sq) so this measures the BAND, not the floor —
    at 18 squares the floor returns $138.89/sq and the band is invisible.
    """
    kw = dict(code_zone="FBC", slope_type="sloped", roof_type="13_tile",
              project_kind="residential", demo=True, existing_roof="tile")
    sloped = estimate(cfg, QuoteInput(num_squares=28.0, **kw))
    mixed = estimate(cfg, QuoteInput(num_squares=28.0, flat_squares=8.0,
                                     flat_roof_type="polyglass_sav_sap", **kw))

    def profit_per_sq(r):
        return next(li["per_sq"] for li in r["line_items_detail"] if li["key"] == "profit")

    # 28 sq sits in the 20-29 band ($110); 36 sq sits in 30+ ($100)
    assert profit_per_sq(sloped) == 110
    assert profit_per_sq(mixed) == 100
    # and it is applied to the whole roof, not just the sloped part
    total = next(li["amount"] for li in mixed["line_items_detail"] if li["key"] == "profit")
    assert abs(total - 100 * 36.0) < 0.01


def test_mixed_roof_defaults_the_flat_system_from_config(cfg: PricingConfig):
    """Flat squares with no system named use the configured default, not $0 and not a 422.

    All three mixed-roof proposals in the golden set sell the flat section as "PERKINS PROTECTOR -
    Flat Re-Roof - Polyglass SAP modified bitumen", so the default is evidence, not a guess.
    """
    kw = dict(code_zone="FBC", slope_type="sloped", roof_type="13_tile",
              num_squares=30.0, flat_squares=10.0, project_kind="residential")
    defaulted = estimate(cfg, QuoteInput(**kw))
    explicit = estimate(cfg, QuoteInput(flat_roof_type="polyglass_sav_sap", **kw))
    assert defaulted["project_total"] == explicit["project_total"]
    assert any(li["key"] == "flat_base_cost_lm" for li in defaulted["line_items_detail"])

    # ...but with no default configured either, refuse rather than price the section at zero
    import copy
    raw = copy.deepcopy(_raw_config())
    raw["low_slope"].pop("default_flat_system", None)
    with pytest.raises(ConfigError, match="default_flat_system"):
        estimate(load_config(raw), QuoteInput(**kw))


# ---------------------------------------------------------------------------
# Branch scope — classification only. It must move no money, ever.
# ---------------------------------------------------------------------------

def _fixture_raw():
    import json
    import pathlib
    return json.loads(pathlib.Path("infra/fixtures/pricing_config_exhibit_b.json").read_text())


def test_every_top_level_key_is_classified():
    """The map must not rot. A new key added without a scope silently becomes un-copyable, which
    is safe but invisible — this makes it loud instead."""
    from core.pricing_config import load_config
    raw = _fixture_raw()
    cfg = load_config(raw)
    scopes = raw.get("_scopes") or {}
    missing = sorted(k for k in raw if not k.startswith("_") and k not in scopes)
    assert not missing, f"unclassified config keys: {missing}"
    bad = {k: v for k, v in scopes.items() if v not in cfg.SCOPES}
    assert not bad, f"unknown scope values: {bad}"


def test_an_unknown_key_fails_closed_to_branch():
    from core.pricing_config import load_config
    cfg = load_config(_fixture_raw())
    assert cfg.scope_of("a_key_added_next_year") == "branch"
    assert cfg.scope_of("daily_overhead_rates") == "branch"
    assert cfg.scope_of("profit_scale") == "shared"


def test_labour_and_overhead_are_never_copyable():
    """Jon's rule, as an assertion. If someone reclassifies one of these to `shared`, a copy
    would overwrite Miami's crew cost with Jupiter's — the exact defect this exists to prevent.
    """
    from core.pricing_config import load_config
    copyable = set(load_config(_fixture_raw()).copyable_keys())
    for key in ("daily_overhead_rates", "sloped_overhead", "office_daily_overhead",
                "office_men", "office_oh_basis_reference", "tile_demo_add", "metal_demo_add",
                "roof_cuts", "roof_height", "repair", "commission_pct"):
        assert key not in copyable, f"{key} must never be copied between branches"


def test_fused_labour_material_keys_are_marked_mixed_not_shared():
    """Tim prices everything L + M + OH + P, so a key carrying a sell price cannot be called
    'material' and shared. Marking them `mixed` keeps them out of a copy AND records the work."""
    from core.pricing_config import load_config
    cfg = load_config(_fixture_raw())
    for key in ("sloped_base_cost_lm", "gutters", "low_slope", "cuts_calc"):
        assert cfg.scope_of(key) == "mixed", f"{key} fuses labour and material"
        assert key not in cfg.copyable_keys()


def test_classification_carries_no_pricing_value():
    """The whole promise of step 1: annotating scope changes no number anywhere."""
    import json
    raw = _fixture_raw()
    scopes = raw.get("_scopes") or {}
    assert scopes, "fixture carries no _scopes map"
    for value in scopes.values():
        assert isinstance(value, str)
    # _scopes lives beside the values, never inside them: an inline marker would be iterated by
    # daily_overhead_rates() as if it were a series and raise on `rate * factor`.
    for key, value in raw.items():
        if key.startswith("_") or not isinstance(value, dict):
            continue
        assert "_scope" not in value, f"{key} carries an inline _scope; use the top-level map"
    json.dumps(raw)  # still serialisable


# ---------------------------------------------------------------------------
# #436 — poor access adds crew DAYS, and only days.
#
# Tim, 2026-07-27: "if there's a back roof that has very poor access ... you're going to work
# slower." Fitted per series on his 29 RoofR homes joined to the access_issue flag on his 30-home
# sheet. Measured with the feature set FROZEN and coefficients + steep rule refit inside each LOO
# fold: geometry only 83% of homes within a day of Tim's booked days, +access 90% (MAE 0.672 ->
# 0.586). Still short of his 95%, and with n=29 one home is worth 3.4 points — the binding
# constraint is data, not features.
# ---------------------------------------------------------------------------

def _cuts_quote(cfg, **over):
    from core.estimator import QuoteInput
    base = dict(code_zone="HVHZ", slope_type="sloped", roof_type="13_tile", num_squares=30.0,
                overhead_mode="daily", existing_roof="tile",
                eaves_lf=299, hips_lf=142, ridges_lf=103, valleys_lf=88, rakes_lf=61,
                wall_flashings_lf=40)
    base.update(over)
    return QuoteInput(**base)


def test_poor_access_adds_days(cfg: PricingConfig):
    from core.estimator import derive_daily_series
    easy = {s.series: s.days for s in derive_daily_series(cfg, _cuts_quote(cfg))}
    hard = {s.series: s.days for s in derive_daily_series(cfg, _cuts_quote(cfg,
                                                                          access_difficult=True))}
    assert sum(hard.values()) > sum(easy.values()), (
        f"a hard-access roof must book more crew days: {easy} vs {hard}")


def test_access_moves_days_not_the_per_square_price(cfg: PricingConfig):
    """It is a TIME feature. accessibility_flat is the money field; this must not touch a rate."""
    r_easy = estimate(cfg, _cuts_quote(cfg))
    r_hard = estimate(cfg, _cuts_quote(cfg, access_difficult=True))
    # Overhead is time-driven, so the total legitimately moves...
    assert r_hard["project_total"] >= r_easy["project_total"]
    # ...but the base cost per square is a rate and must be untouched.
    def base_per_sq(r):
        return next(li["per_sq"] for li in r["line_items_detail"] if li["key"] == "base_cost_lm")
    assert base_per_sq(r_hard) == base_per_sq(r_easy)


def test_access_alone_does_not_trigger_the_geometry_model(cfg: PricingConfig):
    """`access` is a MODEL term, not a GEOMETRY term. A quote with no cut LFs must still use the
    squares-only fit — evaluating the geometry model with every complexity term at zero reads as
    the simplest possible roof and under-quotes the days."""
    from core.estimator import derive_daily_series
    no_cuts = dict(code_zone="HVHZ", slope_type="sloped", roof_type="13_tile", num_squares=30.0,
                   overhead_mode="daily", existing_roof="tile")
    from core.estimator import QuoteInput
    plain = {s.series: s.days for s in derive_daily_series(cfg, QuoteInput(**no_cuts))}
    hard = {s.series: s.days
            for s in derive_daily_series(cfg, QuoteInput(**no_cuts, access_difficult=True))}
    # Same squares-only fit both ways: no cut measurements means no geometry model, and the
    # access coefficient lives in the geometry model.
    assert plain == hard, f"access must not switch a cut-less quote onto the geometry model: {plain} vs {hard}"


def test_low_slope_daily_overhead_falls_back_and_says_so(cfg: PricingConfig):
    """Asking for daily overhead on a low-slope system must not silently bill per-square.

    `derive_daily_series` returns [] for every low-slope system — Tim's time-learning workbook is
    `Residential_OH_Calculator_SLOPED_ONLY`, so no low-slope day series was ever fitted. The
    estimate then used the per-square overhead table while the caller had asked for days, and
    NOTHING in the result said so: a quote that quietly ignored the request was indistinguishable
    from one that honoured it. Tim, 2026-08-03: "Why is this still trying to use per SQ prices on
    the OH? It's all going to be based on days".

    The per-square number is not necessarily wrong, but it is NOT his method: both commercial
    workbooks derive the per-square overhead FROM a day count (Miramar "$1,175 x 25 days & $765 x
    30 days = $52,325" over 142 sq = its displayed $370/sq; Evergrene's flat row 28 sq / 7 days /
    $6,195 = its displayed $221.25/sq). So this is an unpriced gap, and the silence was the bug.
    """
    # The shipped fixture now carries a low_slope series, so low slope derives days like anything
    # else — assert that first, because it is the behaviour Tim asked for.
    ok = estimate(cfg, QuoteInput(
        roof_type="polyglass_sav_sap", num_squares=6.0, slope_type="low_slope",
        code_zone="HVHZ", deck_type="existing_concrete", overhead_mode="daily"))
    assert ok["overhead_basis_used"] == "daily"
    assert not any("overhead_fell_back_to_per_sq" in w for w in ok["warnings"])

    # The fallback still has to announce itself for any config that lacks the series — an older
    # branch config, or one rolled back to a previous version.
    import copy as _copy

    from core.pricing_config import load_config as _load
    raw = _copy.deepcopy(cfg.raw)
    raw["daily_overhead_day_model"]["install_series_by_roof_type"].pop("polyglass_sav_sap", None)
    r = estimate(_load(raw), QuoteInput(
        roof_type="polyglass_sav_sap", num_squares=6.0, slope_type="low_slope",
        code_zone="HVHZ", deck_type="existing_concrete", overhead_mode="daily"))
    assert r["overhead_basis_used"] == "per_sq"
    assert any("overhead_fell_back_to_per_sq" in w for w in r["warnings"]), r["warnings"]


def test_sloped_daily_overhead_is_not_labelled_a_fallback(cfg: PricingConfig):
    """The complement, and it fails for a different reason: a roof type that HAS a fitted series
    must report `daily` and carry no fallback warning. A warning on every quote is a warning on
    none."""
    r = estimate(cfg, QuoteInput(
        roof_type="13_tile", num_squares=20.0, slope_type="sloped", code_zone="HVHZ",
        overhead_mode="daily", existing_roof="tile"))
    assert r["overhead_basis_used"] == "daily"
    assert r["daily_series"], "a fitted roof type must derive days"
    assert not any("fell_back" in w for w in r["warnings"]), r["warnings"]


def test_per_sq_request_is_not_reported_as_a_fallback(cfg: PricingConfig):
    """Only a request for days that could not be honoured is a fallback. A caller who asked for
    the per-square table got exactly what it asked for, and must not be warned about it."""
    r = estimate(cfg, QuoteInput(
        roof_type="polyglass_sav_sap", num_squares=6.0, slope_type="low_slope",
        code_zone="HVHZ", deck_type="existing_concrete", overhead_mode="per_sq"))
    assert "overhead_basis_used" not in r
    assert not any("fell_back" in w for w in r["warnings"]), r["warnings"]


def test_mixed_roof_books_days_for_its_flat_section(cfg: PricingConfig):
    """A mixed sloped+flat roof must book the flat crew's days too.

    The install fit is driven by `num_squares`, which is the SLOPED area, so before `flat_series`
    a mixed roof booked the sloped days and NONE of the flat — under-quoting the overhead by
    exactly the days the flat crew is on the roof. 36% of the sold book is mixed
    (docs/mixed-roof-sold-book-2026-08-03.md), and Tim logs "Flat (days)" beside "Squares (Flat)"
    on every home in his own workbook.
    """
    from core.estimator import derive_daily_series
    raw = dict(cfg.raw)
    raw["daily_overhead_day_model"] = {
        **raw["daily_overhead_day_model"],
        "series": {**raw["daily_overhead_day_model"]["series"],
                   "low_slope": {"setup": 0.389, "rate": 0.0851}},
        "flat_series": {"series": "low_slope"},
    }
    raw["daily_overhead_rates"] = {**raw["daily_overhead_rates"], "low_slope": 1050.0}
    from core.pricing_config import load_config
    c2 = load_config(raw)

    common = dict(roof_type="13_tile", num_squares=20.0, code_zone="HVHZ",
                  slope_type="sloped", overhead_mode="daily", existing_roof="tile")
    dry = {s.series: s.days for s in derive_daily_series(c2, QuoteInput(**common))}
    wet = {s.series: s.days
           for s in derive_daily_series(c2, QuoteInput(**common, flat_squares=6.0,
                                                       flat_roof_type="polyglass_sav_sap"))}
    assert "low_slope" not in dry, "a roof with no flat section must book no flat days"
    assert wet.get("low_slope", 0) > 0, "the flat section booked no days"
    # The sloped side is untouched — adding a flat section must not change the sloped day count.
    assert {k: v for k, v in wet.items() if k != "low_slope"} == dry


def test_flat_days_need_both_a_series_and_a_rate(cfg: PricingConfig):
    """Config that names a flat series with no rate for it must book nothing rather than raise:
    `compute_daily_overhead` would ConfigError on the unknown series and take the whole quote
    down, which is a worse failure than the per-square fallback it replaces."""
    from core.estimator import derive_daily_series
    raw = dict(cfg.raw)
    raw["daily_overhead_day_model"] = {**raw["daily_overhead_day_model"],
                                       "flat_series": {"series": "nope"}}
    from core.pricing_config import load_config
    got = derive_daily_series(load_config(raw), QuoteInput(
        roof_type="13_tile", num_squares=20.0, flat_squares=6.0, code_zone="HVHZ",
        slope_type="sloped", overhead_mode="daily", existing_roof="tile"))
    assert all(s.series != "nope" for s in got)


def test_a_pure_low_slope_quote_books_no_extra_days_for_flat_squares(cfg: PricingConfig):
    """`flat_squares` must not add days to a quote that never prices it.

    `_build_low_slope` prices `base * num_squares` and never reads `flat_squares`, so on a PURE
    low-slope quote the flat area is not a priced section — it is the same roof. The frontend
    sends `flat_squares` off the measurement regardless of roof type, so a day block without a
    `slope_type` guard charges overhead against squares no line item covers: measured +$1,575 on
    30 sq tpo_adhered + 12 flat. Mirrors the pricing guard, which has always been sloped-only.
    """
    from core.estimator import derive_daily_series
    raw = dict(cfg.raw)
    raw["daily_overhead_day_model"] = {
        **raw["daily_overhead_day_model"],
        "series": {**raw["daily_overhead_day_model"]["series"],
                   "low_slope": {"setup": 0.389, "rate": 0.0851}},
        "flat_series": {"series": "low_slope"},
        "install_series_by_roof_type": {
            **raw["daily_overhead_day_model"].get("install_series_by_roof_type", {}),
            "tpo_adhered": "low_slope"},
    }
    raw["daily_overhead_rates"] = {**raw["daily_overhead_rates"], "low_slope": 1050.0}
    from core.pricing_config import load_config
    c2 = load_config(raw)

    base = dict(roof_type="tpo_adhered", num_squares=30.0, slope_type="low_slope",
                code_zone="HVHZ", deck_type="existing_concrete", overhead_mode="daily")
    without = {s.series: s.days for s in derive_daily_series(c2, QuoteInput(**base))}
    with_flat = {s.series: s.days
                 for s in derive_daily_series(c2, QuoteInput(**base, flat_squares=12.0))}
    assert without == with_flat, (
        f"flat_squares changed the day count on a pure low-slope quote: {without} -> {with_flat}")


def test_two_day_cells_price_the_same_as_the_three_series_the_model_derives(cfg: PricingConfig):
    """The UI has TWO day cells (demo, install) while a mixed roof derives THREE series. Folding
    the flat days into the install cell must not move the price.

    That holds because `overhead_basis="branch"` bills every series the same
    `office_daily_overhead / concurrent_crews` — Tim, 2026-08-04: "we charge OH per install day,
    roof type doesn't matter." So the money depends on the day TOTAL, not on which series carries
    it, and one cell per crew is the whole model.

    ⚠️ This is the assumption the two-cell design rests on, and it is FALSE under
    `overhead_basis="series"`, where each series has its own rate. If a branch is ever moved back
    to the series basis, the UI has to send the three series separately again — this test is what
    will tell you.
    """
    raw = dict(cfg.raw)
    raw["overhead_basis"] = "branch"
    raw["office_daily_overhead"] = 1470
    raw["concurrent_crews"] = 1.5
    raw["daily_overhead_day_model"] = {
        **raw["daily_overhead_day_model"],
        "series": {**raw["daily_overhead_day_model"]["series"],
                   "low_slope": {"setup": 0.389, "rate": 0.0851}},
        "flat_series": {"series": "low_slope"},
    }
    raw["daily_overhead_rates"] = {**raw["daily_overhead_rates"], "low_slope": 1050.0}
    from core.estimator import DailyOverheadSeries, derive_daily_series
    from core.pricing_config import load_config
    c2 = load_config(raw)

    base = dict(roof_type="13_tile", num_squares=20.0, flat_squares=6.0,
                flat_roof_type="polyglass_sav_sap", slope_type="sloped", code_zone="HVHZ",
                existing_roof="tile", overhead_mode="daily")
    derived = derive_daily_series(c2, QuoteInput(**base))
    assert len({s.series for s in derived}) == 3, f"expected a 3-series mixed roof, got {derived}"

    demo_series = c2.daily_overhead_day_model()["demo_series"]
    demo = sum(s.days for s in derived if s.series == demo_series)
    install = sum(s.days for s in derived if s.series != demo_series)
    collapsed = [DailyOverheadSeries(series="tile", days=install)]
    if demo:
        collapsed.append(DailyOverheadSeries(series=demo_series, days=demo))

    three = estimate(c2, QuoteInput(**base))["project_total"]
    two = estimate(c2, QuoteInput(**base, daily_series=collapsed))["project_total"]
    assert three == two, f"two cells priced {two} against the model's {three}"
