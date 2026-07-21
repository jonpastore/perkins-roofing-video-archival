"""TDD: low-slope pricing — all-in systems, OH/profit skipping, wood-deck adder.

Fail-first pass written before implementation. Once engine + fixture land these must all go green.
"""
import json

import pytest

from core.estimator import QuoteInput, QuoteRequiresManualReview, estimate
from core.pricing_config import PricingConfig, load_config

# ---------------------------------------------------------------------------
# Helpers — build a minimal config from the real fixture + helper factory
# ---------------------------------------------------------------------------

def _load_fixture() -> dict:
    import pathlib
    p = pathlib.Path(__file__).parent.parent.parent / "infra" / "fixtures" / "pricing_config_exhibit_b.json"
    return json.loads(p.read_text())


def _cfg(overrides: dict | None = None) -> PricingConfig:
    """Return a PricingConfig built from the real fixture, with optional dict-level overrides."""
    raw = _load_fixture()
    if overrides:
        _deep_update(raw, overrides)
    return load_config(raw)


def _deep_update(base: dict, patch: dict) -> None:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v


# ---------------------------------------------------------------------------
# 1. Fixture sanity — exhibit_version bumped, values present
# ---------------------------------------------------------------------------

def test_fixture_exhibit_version():
    raw = _load_fixture()
    assert raw["exhibit_version"] == "B-2026-07-10-r2", (
        f"exhibit_version must be B-2026-07-10-r2, got {raw['exhibit_version']!r}"
    )


def test_fixture_low_slope_base_costs_populated():
    raw = _load_fixture()
    ls = raw["low_slope"]
    for zone in ("HVHZ", "FBC"):
        for system in (
            "polyglass_sav_sap", "tpo_adhered", "tpo_mech_attached",
            "pb_acrylic_2coat", "pb_premium_acrylic",
            "pb_silicone_1coat", "pb_silicone_2coat", "pb_silicone_3coat",
            "stockmeier_polyurethane_2coat",
        ):
            val = ls["base_cost_lm"][zone].get(system)
            assert val is not None, f"low_slope.base_cost_lm[{zone}][{system}] is null"


def test_fixture_overhead_populated():
    raw = _load_fixture()
    ls = raw["low_slope"]
    for zone in ("HVHZ", "FBC"):
        for oh_key in ("flat_oh", "tpo_oh", "coatings_inhouse_oh"):
            val = ls["overhead"][zone].get(oh_key)
            assert val is not None, f"low_slope.overhead[{zone}][{oh_key}] is null"


def test_fixture_all_in_systems_list_present():
    raw = _load_fixture()
    ains = raw["low_slope"].get("all_in_systems")
    assert isinstance(ains, list) and len(ains) > 0, "low_slope.all_in_systems must be a non-empty list"
    assert "pb_acrylic_2coat" in ains
    assert "pb_silicone_2coat" in ains
    assert "stockmeier_polyurethane_2coat" in ains


def test_fixture_all_in_excludes_base_systems():
    raw = _load_fixture()
    ains = set(raw["low_slope"].get("all_in_systems", []))
    # Base systems (non-all-in) must NOT be in the list
    for s in ("polyglass_sav_sap", "tpo_adhered", "tpo_mech_attached"):
        assert s not in ains, f"{s} must NOT be in all_in_systems"


def test_fixture_wood_deck_oh_adder():
    raw = _load_fixture()
    adder = raw["low_slope"].get("wood_deck_oh_adder")
    assert adder == 50, f"wood_deck_oh_adder must be 50 (Exhibit B §4.2), got {adder!r}"


def test_fixture_deck_adders_populated():
    raw = _load_fixture()
    deck_types = raw["low_slope"]["deck_types"]
    for key in (
        "bur_tpo_concrete_primer",
        "bur_wood_wb3000",
        "bur_wood_sav_flashing",
        "bur_wood_elastobase",
        "tpo_wood_versashield",
        "tpo_wood_densdeck_iso",
    ):
        assert deck_types.get(key) is not None, f"low_slope.deck_types[{key}] is null"


def test_fixture_insulation_tiers_populated():
    raw = _load_fixture()
    tiers = raw["low_slope"]["insulation_tiers"]
    assert len(tiers) >= 3, "insulation_tiers must have at least 3 entries"


def test_fixture_tapered_cost_populated():
    raw = _load_fixture()
    assert raw["low_slope"]["tapered_cost_per_sq"] is not None


def test_fixture_tear_off_populated():
    raw = _load_fixture()
    assert raw["low_slope"]["tear_off_per_layer_per_sq"] is not None


def test_fixture_no_pending_nulls_for_filled_cells():
    """Verify that _pending_ keys co-located with now-filled values are removed."""
    raw = _load_fixture()
    ls = raw["low_slope"]
    stale = [
        k for k in ls
        if k.startswith("_pending_insulation")
        or k.startswith("_pending_tapered")
        or k.startswith("_pending_tear_off")
    ]
    assert not stale, f"Stale _pending_ keys found in low_slope: {stale}"


def test_fixture_pressure_cleaning_populated():
    raw = _load_fixture()
    ls = raw["low_slope"]
    pc = ls.get("pressure_cleaning")
    assert pc is not None, "low_slope.pressure_cleaning block missing"
    assert pc.get("flat") == 30
    assert pc.get("sloped") == 40


def test_fixture_tear_off_extras_populated():
    raw = _load_fixture()
    ls = raw["low_slope"]
    extras = ls.get("tear_off_extras")
    assert extras is not None, "low_slope.tear_off_extras block missing"
    assert extras.get("additional_hauling") == 20
    assert extras.get("labor") == 20
    assert extras.get("oh") == 35


# ---------------------------------------------------------------------------
# 2. PricingConfig accessor — is_all_in
# ---------------------------------------------------------------------------

def test_config_is_all_in_true_for_coating():
    cfg = _cfg()
    assert cfg.is_all_in("pb_acrylic_2coat") is True
    assert cfg.is_all_in("pb_silicone_1coat") is True
    assert cfg.is_all_in("stockmeier_polyurethane_2coat") is True


def test_config_is_all_in_false_for_base_system():
    cfg = _cfg()
    assert cfg.is_all_in("polyglass_sav_sap") is False
    assert cfg.is_all_in("tpo_adhered") is False
    assert cfg.is_all_in("tpo_mech_attached") is False


def test_config_wood_deck_oh_adder():
    cfg = _cfg()
    assert cfg.wood_deck_oh_adder() == 50


# ---------------------------------------------------------------------------
# 3. Engine — all-in system: OH + profit NOT added
# ---------------------------------------------------------------------------

def _make_allIn_input(system: str, sq: float = 20, zone: str = "HVHZ") -> QuoteInput:
    return QuoteInput(
        code_zone=zone,
        roof_type=system,
        num_squares=sq,
        slope_type="low_slope",
        project_kind="commercial",  # commercial band requires sq >= 20
    )


def test_all_in_system_total_equals_price_times_sq():
    """pb_acrylic_2coat at $375/sq all-in: project total for sq-only items = 375 * sq (no OH, no profit added)."""
    cfg = _cfg()
    q = _make_allIn_input("pb_acrylic_2coat", sq=20)
    result = estimate(cfg, q)
    # Find per-sq items: base_cost_lm only (no overhead or profit line items)
    detail = result["line_items_detail"]
    oh_items = [li for li in detail if li["key"] == "overhead"]
    profit_items = [li for li in detail if li["key"] == "profit"]
    assert len(oh_items) == 0, f"all-in system must have no overhead line item, got {oh_items}"
    assert len(profit_items) == 0, f"all-in system must have no profit line item, got {profit_items}"


def test_all_in_system_base_cost_matches_config():
    """Base cost line item for pb_acrylic_2coat must equal 375 * sq."""
    cfg = _cfg()
    q = _make_allIn_input("pb_acrylic_2coat", sq=20)
    result = estimate(cfg, q)
    detail = result["line_items_detail"]
    base_item = next(li for li in detail if li["key"] == "base_cost_lm")
    assert base_item["amount"] == pytest.approx(375 * 20)


def test_all_in_pb_silicone_2coat():
    """pb_silicone_2coat at $515/sq: no OH/profit lines."""
    cfg = _cfg()
    q = _make_allIn_input("pb_silicone_2coat", sq=20)
    result = estimate(cfg, q)
    detail = result["line_items_detail"]
    assert not any(li["key"] == "overhead" for li in detail)
    assert not any(li["key"] == "profit" for li in detail)
    base = next(li for li in detail if li["key"] == "base_cost_lm")
    assert base["amount"] == pytest.approx(515 * 20)


def test_all_in_stockmeier():
    """stockmeier_polyurethane_2coat at $595/sq: no OH/profit."""
    cfg = _cfg()
    q = _make_allIn_input("stockmeier_polyurethane_2coat", sq=20)
    result = estimate(cfg, q)
    detail = result["line_items_detail"]
    assert not any(li["key"] == "overhead" for li in detail)
    assert not any(li["key"] == "profit" for li in detail)
    base = next(li for li in detail if li["key"] == "base_cost_lm")
    assert base["amount"] == pytest.approx(595 * 20)


# ---------------------------------------------------------------------------
# 4. Engine — non-all-in (base) system DOES get OH + profit
# ---------------------------------------------------------------------------

def _make_base_input(system: str, sq: float = 20, zone: str = "HVHZ") -> QuoteInput:
    return QuoteInput(
        code_zone=zone,
        roof_type=system,
        num_squares=sq,
        slope_type="low_slope",
        project_kind="commercial",
    )


def test_non_all_in_system_has_oh_and_profit_lines():
    """polyglass_sav_sap is NOT all-in: overhead and profit must be present."""
    cfg = _cfg()
    q = _make_base_input("polyglass_sav_sap", sq=20)
    result = estimate(cfg, q)
    detail = result["line_items_detail"]
    assert any(li["key"] == "overhead" for li in detail), "expected overhead line item"
    assert any(li["key"] == "profit" for li in detail), "expected profit line item"


def test_tpo_adhered_has_oh_and_profit():
    cfg = _cfg()
    q = _make_base_input("tpo_adhered", sq=20)
    result = estimate(cfg, q)
    detail = result["line_items_detail"]
    assert any(li["key"] == "overhead" for li in detail)
    assert any(li["key"] == "profit" for li in detail)


def test_non_all_in_base_cost_matches_config():
    """polyglass_sav_sap base cost: $475/sq."""
    cfg = _cfg()
    q = _make_base_input("polyglass_sav_sap", sq=20)
    result = estimate(cfg, q)
    detail = result["line_items_detail"]
    base = next(li for li in detail if li["key"] == "base_cost_lm")
    assert base["amount"] == pytest.approx(475 * 20)


# ---------------------------------------------------------------------------
# 5. Engine — wood deck adds $50 OH adder
# ---------------------------------------------------------------------------

def _make_wood_deck_input(system: str, deck: str, sq: float = 20) -> QuoteInput:
    return QuoteInput(
        code_zone="HVHZ",
        roof_type=system,
        num_squares=sq,
        slope_type="low_slope",
        deck_type=deck,
        project_kind="commercial",
    )


def test_wood_deck_adds_50_oh_to_non_all_in():
    """Non-all-in system with bur_wood_wb3000 deck: OH line increases by $50/sq."""
    cfg = _cfg()
    q_concrete = _make_base_input("polyglass_sav_sap", sq=20)
    q_wood = _make_wood_deck_input("polyglass_sav_sap", "bur_wood_wb3000", sq=20)

    r_concrete = estimate(cfg, q_concrete)
    r_wood = estimate(cfg, q_wood)

    oh_concrete = next(li for li in r_concrete["line_items_detail"] if li["key"] == "overhead")
    oh_wood = next(li for li in r_wood["line_items_detail"] if li["key"] == "overhead")

    # Wood OH amount = concrete OH amount + 50 * sq
    assert oh_wood["amount"] == pytest.approx(oh_concrete["amount"] + 50 * 20)


def test_wood_deck_adds_50_oh_per_sq_not_flat():
    """The $50 adder is per-square, verified with different sq count.

    Uses residential < 20 sq to stay in the valid pm_incentive band.
    """
    cfg = _cfg()
    sq = 15
    q_concrete = QuoteInput(
        code_zone="HVHZ", roof_type="polyglass_sav_sap", num_squares=sq,
        slope_type="low_slope", project_kind="residential",
    )
    q_wood = QuoteInput(
        code_zone="HVHZ", roof_type="polyglass_sav_sap", num_squares=sq,
        slope_type="low_slope", deck_type="bur_wood_sav_flashing", project_kind="residential",
    )
    r_c = estimate(cfg, q_concrete)
    r_w = estimate(cfg, q_wood)
    oh_c = next(li for li in r_c["line_items_detail"] if li["key"] == "overhead")
    oh_w = next(li for li in r_w["line_items_detail"] if li["key"] == "overhead")
    assert oh_w["amount"] == pytest.approx(oh_c["amount"] + 50 * sq)


def test_concrete_deck_no_wood_oh_adder():
    """existing_concrete deck must NOT add the $50 wood OH adder."""
    cfg = _cfg()
    q_no_deck = _make_base_input("polyglass_sav_sap", sq=20)
    q_concrete = QuoteInput(
        code_zone="HVHZ", roof_type="polyglass_sav_sap", num_squares=20,
        slope_type="low_slope", deck_type="existing_concrete", project_kind="commercial",
    )
    r1 = estimate(cfg, q_no_deck)
    r2 = estimate(cfg, q_concrete)
    oh1 = next(li for li in r1["line_items_detail"] if li["key"] == "overhead")
    oh2 = next(li for li in r2["line_items_detail"] if li["key"] == "overhead")
    assert oh1["amount"] == pytest.approx(oh2["amount"])


def test_all_in_system_wood_deck_no_oh_line_still():
    """All-in system with wood deck: still no OH line (all-in price includes everything)."""
    cfg = _cfg()
    q = _make_wood_deck_input("pb_acrylic_2coat", "bur_wood_wb3000", sq=20)
    result = estimate(cfg, q)
    detail = result["line_items_detail"]
    assert not any(li["key"] == "overhead" for li in detail)
    assert not any(li["key"] == "profit" for li in detail)


# ---------------------------------------------------------------------------
# 6. Engine — profit sliding scale still applies to non-all-in
# ---------------------------------------------------------------------------

def test_profit_sliding_scale_applies_to_non_all_in():
    """25 sq → profit tier $110/sq for a non-all-in system (tier [20,29) with upper-exclusive boundary)."""
    cfg = _cfg()
    q = _make_base_input("polyglass_sav_sap", sq=25)
    result = estimate(cfg, q)
    detail = result["line_items_detail"]
    profit_item = next(li for li in detail if li["key"] == "profit")
    assert profit_item["per_sq"] == pytest.approx(110)


# ---------------------------------------------------------------------------
# 7. Zone values — HVHZ and FBC both work for a sampling of systems
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("zone", ["HVHZ", "FBC"])
@pytest.mark.parametrize("system", ["polyglass_sav_sap", "tpo_adhered", "pb_acrylic_2coat", "pb_silicone_2coat"])
def test_both_zones_resolve_without_config_error(zone, system):
    cfg = _cfg()
    q = QuoteInput(
        code_zone=zone, roof_type=system, num_squares=20,
        slope_type="low_slope", project_kind="commercial",
    )
    result = estimate(cfg, q)
    assert result["project_total"] > 0


# ---------------------------------------------------------------------------
# 8. FBC matches HVHZ — Exhibit B §4 is a single table for both zones
# ---------------------------------------------------------------------------

def test_fbc_sav_sap_delta_below_hvhz():
    """FBC polyglass_sav_sap is $25 below HVHZ ($450 vs $475) — explicit in Tim's live
    operational sheet. Jon 2026-07-21: the home-office/live sheet is the most current
    pricing and supersedes Exhibit B's single §4 table. Confirm with Tim if his live
    calculator disagrees."""
    raw = _load_fixture()
    hvhz_base = raw["low_slope"]["base_cost_lm"]["HVHZ"]["polyglass_sav_sap"]
    fbc_base = raw["low_slope"]["base_cost_lm"]["FBC"]["polyglass_sav_sap"]
    assert hvhz_base == 475 and fbc_base == 450, (
        f"expected HVHZ=475, FBC=450 (-$25 sheet delta). HVHZ={hvhz_base}, FBC={fbc_base}"
    )


# ---------------------------------------------------------------------------
# 9. Insulation tiers still work (regression)
# ---------------------------------------------------------------------------

def test_insulation_tiers_resolve():
    cfg = _cfg()
    q = QuoteInput(
        code_zone="HVHZ", roof_type="polyglass_sav_sap", num_squares=20,
        slope_type="low_slope", include_insulation=True, project_kind="commercial",
    )
    result = estimate(cfg, q)
    detail = result["line_items_detail"]
    assert any(li["key"] == "insulation" for li in detail)


def test_tapered_insulation_resolves():
    cfg = _cfg()
    q = QuoteInput(
        code_zone="HVHZ", roof_type="polyglass_sav_sap", num_squares=20,
        slope_type="low_slope", include_tapered=True, project_kind="commercial",
    )
    result = estimate(cfg, q)
    detail = result["line_items_detail"]
    assert any(li["key"] == "tapered" for li in detail)


# ---------------------------------------------------------------------------
# 10. Tear-off works
# ---------------------------------------------------------------------------

def test_tear_off_resolves():
    cfg = _cfg()
    q = QuoteInput(
        code_zone="HVHZ", roof_type="polyglass_sav_sap", num_squares=20,
        slope_type="low_slope", layers_to_remove=1, project_kind="commercial",
    )
    result = estimate(cfg, q)
    detail = result["line_items_detail"]
    assert any(li["key"] == "tear_off" for li in detail)


# ---------------------------------------------------------------------------
# 11. OH key mapping — coatings_inhouse_oh branch (pb_* / stockmeier prefix)
#     These are all-in systems so the OH key is never queried by the engine,
#     but the mapper function itself must cover the coatings branch.
# ---------------------------------------------------------------------------

def test_low_slope_oh_key_tpo():
    from core.estimator import _low_slope_oh_key
    assert _low_slope_oh_key("tpo_adhered") == "tpo_oh"
    assert _low_slope_oh_key("tpo_mech_attached") == "tpo_oh"


def test_low_slope_oh_key_coatings():
    from core.estimator import _low_slope_oh_key
    assert _low_slope_oh_key("pb_acrylic_2coat") == "coatings_inhouse_oh"
    assert _low_slope_oh_key("stockmeier_polyurethane_2coat") == "coatings_inhouse_oh"


def test_low_slope_oh_key_flat_fallback():
    from core.estimator import _low_slope_oh_key
    assert _low_slope_oh_key("polyglass_sav_sap") == "flat_oh"
    assert _low_slope_oh_key("bur") == "flat_oh"


# ---------------------------------------------------------------------------
# 12. Low-slope height branches — 6_plus raises, 3_5 adds trash chute,
#     2_stories adds per-sq height line
# ---------------------------------------------------------------------------

def test_low_slope_6plus_raises():
    cfg = _cfg()
    q = QuoteInput(
        code_zone="HVHZ", roof_type="polyglass_sav_sap", num_squares=20,
        slope_type="low_slope", roof_height="6_plus", project_kind="commercial",
    )
    with pytest.raises(QuoteRequiresManualReview):
        estimate(cfg, q)


def test_low_slope_3_5_stories_trash_chute():
    cfg = _cfg()
    q = QuoteInput(
        code_zone="HVHZ", roof_type="polyglass_sav_sap", num_squares=20,
        slope_type="low_slope", roof_height="3_5_stories", project_kind="commercial",
    )
    result = estimate(cfg, q)
    detail = result["line_items_detail"]
    assert any(li["key"] == "trash_chute" for li in detail)
    trash = next(li for li in detail if li["key"] == "trash_chute")
    assert trash["amount"] == 1500


def test_low_slope_2_stories_height_line():
    cfg = _cfg()
    q_1 = QuoteInput(
        code_zone="HVHZ", roof_type="polyglass_sav_sap", num_squares=20,
        slope_type="low_slope", roof_height="1_story", project_kind="commercial",
    )
    q_2 = QuoteInput(
        code_zone="HVHZ", roof_type="polyglass_sav_sap", num_squares=20,
        slope_type="low_slope", roof_height="2_stories", project_kind="commercial",
    )
    r1 = estimate(cfg, q_1)
    r2 = estimate(cfg, q_2)
    detail2 = r2["line_items_detail"]
    assert any(li["key"] == "roof_height" for li in detail2)
    # 2-stories adds $50/sq per the sloped config table
    height_item = next(li for li in detail2 if li["key"] == "roof_height")
    assert height_item["amount"] == pytest.approx(50 * 20)
    assert r2["project_total"] > r1["project_total"]


# ---------------------------------------------------------------------------
# 13. Behavioral: Adhered TPO on a concrete (primer) deck, HVHZ — full quote
#     math against the Exhibit B §4 seeded numbers (task: pending-tim-resolution.md).
# ---------------------------------------------------------------------------

def test_adhered_tpo_concrete_hvhz_quote_math():
    """Adhered TPO, HVHZ, 20 SQ, BUR/TPO concrete-primer deck: no ConfigError, and
    base + overhead + deck line items match the seeded Exhibit B §4 dollar figures."""
    cfg = _cfg()
    sq = 20
    q = QuoteInput(
        code_zone="HVHZ", roof_type="tpo_adhered", num_squares=sq,
        slope_type="low_slope", deck_type="bur_tpo_concrete_primer",
        project_kind="commercial",
    )
    result = estimate(cfg, q)
    detail = result["line_items_detail"]

    base = next(li for li in detail if li["key"] == "base_cost_lm")
    oh = next(li for li in detail if li["key"] == "overhead")
    deck = next(li for li in detail if li["key"] == "deck_type")

    # base_cost_lm: $485/SQ (§4.1 Adhered TPO), not all-in -> OH/profit added separately
    assert base["amount"] == pytest.approx(485 * sq)
    # overhead: tpo_oh $135/SQ (§4.2), concrete deck -> no wood adder
    assert oh["amount"] == pytest.approx(135 * sq)
    # deck: BUR/TPO concrete primer $15/SQ (§4.4)
    assert deck["amount"] == pytest.approx(15 * sq)

    # Plausible per-SQ total: base + overhead + deck line items sum correctly and
    # roll up into a positive project total (project total also includes profit +
    # pm_incentive, so it is >= the sum of just these three).
    assert base["amount"] + oh["amount"] + deck["amount"] == pytest.approx((485 + 135 + 15) * sq)
    assert result["project_total"] >= base["amount"] + oh["amount"] + deck["amount"]
    assert result["project_total"] > 0
