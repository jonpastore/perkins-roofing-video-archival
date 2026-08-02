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


# ---------------------------------------------------------------------------
# Stockmeier 12-square minimum (#417 G2/G3) — config that existed and was never read
# ---------------------------------------------------------------------------
# Live sheet M29: "STOCKMEIER (POLYURETHANE) - min. 12 SQ job (less than 12 SQ is $390 M per SQ
# and T&M)". stockmeier_min_sq and stockmeier_under_min_material_per_sq have been in the config
# since the low-slope wave — including in all three ACTIVE prod configs, verified 2026-08-02 —
# and no code read either. The fixture's own _note_stockmeier_floor said it was "now enforced as
# a warning", which is the thing these tests exist to keep true.

def _stockmeier_quote(sq: float, zone: str = "HVHZ") -> QuoteInput:
    return QuoteInput(
        code_zone=zone,
        roof_type="stockmeier_polyurethane_2coat",
        num_squares=sq,
        slope_type="low_slope",
        project_kind="commercial",
    )


def test_stockmeier_under_minimum_warns():
    r = estimate(_cfg(), _stockmeier_quote(8))
    warns = " ".join(r.get("warnings", []))
    assert "stockmeier_below_minimum" in warns, r.get("warnings")


def test_stockmeier_warning_names_the_basis_change_not_just_the_size():
    """Below 12 squares the BASIS changes to T&M. A warning that only says "small job" would
    let someone send a per-square quote believing the number was merely conservative."""
    r = estimate(_cfg(), _stockmeier_quote(8))
    warn = next(w for w in r["warnings"] if w.startswith("stockmeier_below_minimum"))
    assert "TIME AND MATERIALS" in warn
    assert "390" in warn  # his material figure, reported


def test_stockmeier_at_and_above_minimum_is_silent():
    for sq in (12, 30):
        r = estimate(_cfg(), _stockmeier_quote(sq))
        assert not any(w.startswith("stockmeier_below_minimum") for w in r.get("warnings", [])), sq


def test_stockmeier_floor_disabled_when_unconfigured():
    """0/absent disables the check rather than inventing a floor — a config predating the key
    must not start emitting a minimum nobody set."""
    cfg = _cfg({"low_slope": {"stockmeier_min_sq": 0}})
    r = estimate(cfg, _stockmeier_quote(8))
    assert not any(w.startswith("stockmeier_below_minimum") for w in r.get("warnings", []))


def test_other_low_slope_systems_do_not_trip_the_stockmeier_floor():
    q = QuoteInput(code_zone="HVHZ", roof_type="pb_silicone_2coat", num_squares=8,
                   slope_type="low_slope", project_kind="commercial")
    r = estimate(_cfg(), q)
    assert not any(w.startswith("stockmeier_below_minimum") for w in r.get("warnings", []))


# ---------------------------------------------------------------------------
# Pressure cleaning (#417 G9) — priced config that nothing could reach
# ---------------------------------------------------------------------------
# Sheet O1/O2: $30/sq flat, $40/sq sloped. Correct in config (and in all three ACTIVE prod
# configs) since the low-slope wave, and `grep -rn pressure_clean core/ api/ web/src` returned
# NOTHING — so a maintenance or clean-only job could not be quoted at all.

def _pc_quote(slope_type, sq=20, **kw):
    return QuoteInput(
        code_zone="HVHZ",
        roof_type="polyglass_sav_sap" if slope_type == "low_slope" else "13_tile",
        num_squares=sq, slope_type=slope_type, project_kind="commercial", **kw)


def _line(result, key):
    return next((li for li in result["line_items_detail"] if li["key"] == key), None)


def test_pressure_cleaning_absent_unless_requested():
    assert _line(estimate(_cfg(), _pc_quote("low_slope")), "pressure_cleaning") is None


def test_pressure_cleaning_flat_rate_on_a_low_slope_roof():
    r = estimate(_cfg(), _pc_quote("low_slope", include_pressure_cleaning=True))
    li = _line(r, "pressure_cleaning")
    assert li is not None and li["per_sq"] == 30 and li["amount"] == 30 * 20


def test_pressure_cleaning_sloped_rate_on_a_sloped_roof():
    """The rate follows the ROOF, not the config block. O2 is the sloped rate and lives under
    low_slope purely because that is the sheet block it was transcribed from — reading it as
    'flat roofs only' would under-charge every sloped clean by $10/sq."""
    r = estimate(_cfg(), _pc_quote("sloped", include_pressure_cleaning=True))
    li = _line(r, "pressure_cleaning")
    assert li is not None and li["per_sq"] == 40


def test_pressure_cleaning_silent_when_unconfigured():
    """A config predating the key must not start emitting a $0 line. Built by deleting the key
    rather than via _cfg overrides — _deep_update MERGES dicts, so passing {} leaves the real
    rates in place and the test would pass without proving anything."""
    raw = _load_fixture()
    del raw["low_slope"]["pressure_cleaning"]
    r = estimate(load_config(raw), _pc_quote("low_slope", include_pressure_cleaning=True))
    assert _line(r, "pressure_cleaning") is None


# ---------------------------------------------------------------------------
# Cover board OH adder (#417 G7) + polyglass warranty upgrades (#417 G8)
# ---------------------------------------------------------------------------
# ⚠️ Unlike Stockmeier/pressure-cleaning above, these keys are NEW — the three ACTIVE prod
# configs do not carry them (checked 2026-08-02). The engine is correct ahead of the data, so
# these tests pin the unconfigured behaviour as hard as the configured behaviour: a config
# without the keys must price exactly as it did before, and must never quote an upgrade it
# cannot price.

def _deck_quote(deck_type, sq=20):
    return QuoteInput(code_zone="HVHZ", roof_type="tpo_adhered", num_squares=sq,
                      slope_type="low_slope", project_kind="commercial", deck_type=deck_type)


def test_cover_board_adds_forty_to_overhead():
    plain = _line(estimate(_cfg(), _deck_quote("bur_tpo_concrete_primer")), "overhead")
    board = _line(estimate(_cfg(), _deck_quote("tpo_wood_densdeck_iso")), "overhead")
    # densdeck is also a WOOD deck, so it carries the $50 wood adder too — "an ADDITIONAL $40".
    assert board["per_sq"] - plain["per_sq"] == 90


def test_cover_board_adder_is_overhead_only_not_material():
    """The board's material is already inside the deck-type rate. If this adder also moved the
    deck line, the board would be charged twice."""
    r = estimate(_cfg(), _deck_quote("tpo_wood_densdeck_iso"))
    assert _line(r, "deck_type")["amount"] == 120 * 20  # unchanged deck rate


def test_cover_board_silent_when_unconfigured():
    raw = _load_fixture()
    del raw["low_slope"]["cover_board_oh_adder"]
    del raw["low_slope"]["cover_board_deck_types"]
    with_key = _line(estimate(_cfg(), _deck_quote("tpo_wood_densdeck_iso")), "overhead")
    without = _line(estimate(load_config(raw), _deck_quote("tpo_wood_densdeck_iso")), "overhead")
    assert without["per_sq"] == with_key["per_sq"] - 40


def _poly_quote(upgrade=None, zone="HVHZ", sq=20):
    return QuoteInput(code_zone=zone, roof_type="polyglass_sav_sap", num_squares=sq,
                      slope_type="low_slope", project_kind="commercial",
                      warranty_upgrade=upgrade)


def test_warranty_upgrade_absent_by_default():
    assert _line(estimate(_cfg(), _poly_quote()), "warranty_upgrade") is None


@pytest.mark.parametrize("key,adder", [
    ("polyfresko_20yr", 80), ("sav_plus_2ply", 65),
    ("sav_plus_3ply_25yr", 175), ("polyfresko_sav_plus_30yr", 315)])
def test_warranty_upgrade_prices_as_an_adder(key, adder):
    r = estimate(_cfg(), _poly_quote(key))
    assert _line(r, "warranty_upgrade")["per_sq"] == adder


def test_warranty_upgrade_totals_reconcile_with_the_old_prose_note():
    """The config note recorded these as TOTALS off the HVHZ base of 475 (555/650/790). Stored as
    adders they must reproduce exactly those totals — that is what proves the re-encoding lossless."""
    for key, total in (("polyfresko_20yr", 555), ("sav_plus_3ply_25yr", 650),
                       ("polyfresko_sav_plus_30yr", 790)):
        r = estimate(_cfg(), _poly_quote(key))
        assert _line(r, "base_cost_lm")["per_sq"] + _line(r, "warranty_upgrade")["per_sq"] == total


def test_warranty_upgrade_applies_to_fbc_off_its_own_base():
    """Storing totals instead of adders is what made these HVHZ-only. FBC must get the same
    upgrade against the FBC base."""
    r = estimate(_cfg(), _poly_quote("sav_plus_3ply_25yr", zone="FBC"))
    assert _line(r, "warranty_upgrade")["per_sq"] == 175


def test_unknown_warranty_upgrade_raises_rather_than_quoting_the_base():
    from core.estimator import ConfigError
    with pytest.raises(ConfigError):
        estimate(_cfg(), _poly_quote("gold_plated_50yr"))


def test_warranty_upgrade_on_a_config_without_the_key_raises():
    """Prod's configs do not carry this key yet. Asking for an upgrade there must fail loudly,
    not silently return the base warranty at the base price."""
    from core.estimator import ConfigError
    raw = _load_fixture()
    del raw["low_slope"]["polyglass_warranty_upgrades"]
    with pytest.raises(ConfigError):
        estimate(load_config(raw), _poly_quote("polyfresko_20yr"))


# ---------------------------------------------------------------------------
# Trash-chute sections (G6), silicone add-ons (G13), detail items (G10),
# stucco-metal contradiction (G11)
# ---------------------------------------------------------------------------

def _chute_quote(stories=None, height="3_5_stories"):
    return QuoteInput(code_zone="HVHZ", roof_type="tpo_adhered", num_squares=20,
                      slope_type="low_slope", project_kind="commercial",
                      roof_height=height, stories=stories)


def test_trash_chute_sections_billed_per_storey():
    r = estimate(_cfg(), _chute_quote(stories=5))
    assert _line(r, "trash_chute")["amount"] == 1500          # flat part unchanged
    assert _line(r, "trash_chute_sections")["amount"] == 3 * 100 * 5


def test_trash_chute_without_a_storey_count_uses_the_band_floor_and_warns():
    """roof_height is a BAND. Billing its floor means an unknown under-bills rather than
    over-bills, and the warning says by how much so nobody has to work it out."""
    r = estimate(_cfg(), _chute_quote())
    assert _line(r, "trash_chute_sections")["amount"] == 3 * 100 * 3
    warn = next(w for w in r["warnings"] if w.startswith("trash_chute_storeys_assumed"))
    assert "under-billed by $600" in warn


def test_trash_chute_sections_absent_below_the_band():
    r = estimate(_cfg(), _chute_quote(height="2_stories"))
    assert _line(r, "trash_chute_sections") is None


def test_trash_chute_sections_silent_when_unconfigured():
    raw = _load_fixture()
    del raw["low_slope"]["trash_chute_sections_per_story"]
    r = estimate(load_config(raw), _chute_quote(stories=5))
    assert _line(r, "trash_chute_sections") is None
    assert _line(r, "trash_chute")["amount"] == 1500


@pytest.mark.parametrize("key,rate", [
    ("granules", 50), ("traffic_coat_1coat", 225), ("tpo_primer", 25)])
def test_silicone_addons_price_per_square(key, rate):
    q = QuoteInput(code_zone="HVHZ", roof_type="pb_silicone_2coat", num_squares=20,
                   slope_type="low_slope", project_kind="commercial", silicone_addons=[key])
    r = estimate(_cfg(), q)
    assert _line(r, f"silicone_addon_{key}")["amount"] == rate * 20


def test_extra_coat_is_not_a_flat_addon():
    """An extra coat is per-COAT and carries materials, so it must not sit in the flat
    per-square add-on map alongside granules and traffic coat."""
    assert not any(k.startswith("extra_coat") for k in _cfg().silicone_addons())


def _coat_quote(coats, material=None, sq=20):
    return QuoteInput(code_zone="HVHZ", roof_type="pb_silicone_2coat", num_squares=sq,
                      slope_type="low_slope", project_kind="commercial",
                      extra_coats=coats, extra_coat_material_per_sq=material)


def test_extra_coats_bill_lop_plus_materials_per_coat():
    """L27: "$100 per extra coat (L, OH & P) + M", M = materials (Jon, 2026-08-02)."""
    r = estimate(_cfg(), _coat_quote(2, material=30))
    li = _line(r, "silicone_extra_coats")
    assert li["per_sq"] == 130                     # 100 L/OH/P + 30 material
    assert li["amount"] == 130 * 20 * 2            # x squares x coats


def test_extra_coats_without_materials_raises_rather_than_billing_labour_alone():
    """The material half is genuinely variable — Tim's own build-ups run $195/$220/$300 for
    1/2/3 coats, so there is no constant to default to. Billing only L/OH/P would look like a
    complete price and under-charge every time."""
    from core.estimator import ConfigError
    with pytest.raises(ConfigError):
        estimate(_cfg(), _coat_quote(1))


def test_no_extra_coat_line_when_none_requested():
    assert _line(estimate(_cfg(), _coat_quote(0)), "silicone_extra_coats") is None


def test_unknown_silicone_addon_raises():
    from core.estimator import ConfigError
    q = QuoteInput(code_zone="HVHZ", roof_type="pb_silicone_2coat", num_squares=20,
                   slope_type="low_slope", project_kind="commercial",
                   silicone_addons=["gold_flakes"])
    with pytest.raises(ConfigError):
        estimate(_cfg(), q)


def test_detail_items_price_in_the_sheets_own_units():
    q = QuoteInput(code_zone="HVHZ", roof_type="tpo_adhered", num_squares=20,
                   slope_type="low_slope", project_kind="commercial",
                   detail_items={"penetration_flashing": 4, "scupper_drain_detail": 2,
                                 "flashing_valley_metal_oh_per_lf": 100})
    r = estimate(_cfg(), q)
    assert _line(r, "detail_penetration_flashing")["amount"] == 70 * 4
    assert _line(r, "detail_scupper_drain_detail")["amount"] == 350 * 2
    assert _line(r, "detail_flashing_valley_metal_oh_per_lf")["amount"] == 230


def test_detail_items_absent_by_default_and_zero_quantities_skipped():
    r = estimate(_cfg(), QuoteInput(code_zone="HVHZ", roof_type="tpo_adhered", num_squares=20,
                                    slope_type="low_slope", project_kind="commercial",
                                    detail_items={"penetration_flashing": 0}))
    assert _line(r, "detail_penetration_flashing") is None


def test_unknown_detail_item_raises_naming_the_branch_config():
    from core.estimator import ConfigError
    with pytest.raises(ConfigError):
        estimate(_cfg(), QuoteInput(code_zone="HVHZ", roof_type="tpo_adhered", num_squares=20,
                                    slope_type="low_slope", project_kind="commercial",
                                    detail_items={"gutter_helmet": 3}))


def test_stucco_metal_warns_about_the_ten_times_contradiction():
    """We bill $9/LF live in all three prod configs. If Tim's TPO block ("$9 per 10 LF") is the
    right reading, every stucco line is 10x over. The warning must carry BOTH totals so the
    exposure is legible without opening the sheet."""
    q = QuoteInput(code_zone="HVHZ", roof_type="13_tile", num_squares=20,
                   project_kind="residential", stucco_metal_lf=200)
    r = estimate(_cfg(), q)
    warn = next(w for w in r["warnings"] if w.startswith("stucco_metal_basis_contradiction"))
    assert "$1,800.00" in warn and "$180.00" in warn


def test_no_stucco_warning_when_none_quoted():
    q = QuoteInput(code_zone="HVHZ", roof_type="13_tile", num_squares=20,
                   project_kind="residential")
    r = estimate(_cfg(), q)
    assert not any(w.startswith("stucco_metal_basis_contradiction") for w in r.get("warnings", []))
