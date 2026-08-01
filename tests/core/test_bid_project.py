"""Multi-building bids: what is site-scoped, and what stops being charged nine times.

#430/#449. Tim's Evergrene bid prices 9 structures at one address as ONE deal. `estimate()` is a
pure function of ONE roof, so every site-scoped quantity was silently reinterpreted as roof-scoped
and multiplied by nine — $3,000 of delivery/bonus/permit against a 3-square bus stop, and its own
$2,500 profit floor on top.

These tests pin the seams. The end-to-end number lives in scripts/validate_against_evergrene.py,
which scores the roll-up against Tim's actual bid (+2.3% on total, +1.4% on profit).
"""
from __future__ import annotations

import pytest

from core.bid_project import (
    DEFAULT_ONCE_PER_PROJECT,
    Building,
    ProjectItem,
    price_project,
)
from core.estimator import QuoteInput, estimate
from tests.core.test_estimator_v2 import _cfg_v2


def _b(name: str, sq: float, days: float | None = None) -> Building:
    return Building(name=name, days=days, quote=QuoteInput(
        code_zone="FBC", slope_type="sloped", roof_type="13_tile", num_squares=sq,
        project_kind="commercial", existing_roof="tile"))


# ---------------------------------------------------------------------------
# The defect: once-per-site money charged once per building
# ---------------------------------------------------------------------------

def test_site_fees_are_charged_once_not_once_per_building():
    cfg = _cfg_v2()
    r = price_project(cfg, [_b("Clubhouse", 206), _b("Bus Stop", 3), _b("Gazebo", 4)])

    keys = [f["key"] for f in r["project_fixed"]]
    assert "delivery_plywood_vents" in keys
    assert "permit_processing" in keys
    for row in r["buildings"]:
        got = {li["key"] for li in row["line_items_detail"]}
        assert "delivery_plywood_vents" not in got, f"{row['name']} still paid the site delivery"
        assert "permit_processing" not in got, f"{row['name']} still pulled its own permit"


def test_a_three_square_outbuilding_stops_carrying_the_whole_site():
    """Bus Stop was $8,805 against Tim's $4,763 — $3,000 of it site fees, $1,900 the floor."""
    cfg = _cfg_v2()
    solo = estimate(cfg, _b("Bus Stop", 3).quote)["project_total"]
    r = price_project(cfg, [_b("Clubhouse", 206), _b("Bus Stop", 3)])
    in_project = next(x for x in r["buildings"] if x["name"] == "Bus Stop")["total"]

    assert in_project < solo, "a building inside a project must not cost more than standing alone"
    assert in_project < solo * 0.6, (
        f"expected the bus stop to shed the site's fees and floor; {solo:,.0f} -> {in_project:,.0f}")


def test_the_dumpster_ceil_runs_once_over_summed_squares():
    """tile_dumpster_count is a ceil(). Nine calls round up nine times: 14 loads for a 10-load site.

    This is the subtlest of the four — it is not a flat fee, so "charge it once" is wrong too.
    It has to be recomputed over the summed squares.
    """
    cfg = _cfg_v2()
    parts = [_b("A", 31), _b("B", 31), _b("C", 31)]          # 93 sq total
    r = price_project(cfg, parts)

    project_loads = next(f for f in r["project_fixed"] if f["key"] == "tile_dumpster")
    per_building = sum(
        next(li["amount"] for li in estimate(cfg, p.quote)["line_items_detail"]
             if li["key"] == "tile_dumpster")
        for p in parts)
    assert project_loads["amount"] < per_building, (
        "summing per-building dumpsters must over-count against one ceil over the site")


# ---------------------------------------------------------------------------
# The profit floor
# ---------------------------------------------------------------------------

def test_no_building_pays_its_own_floor_inside_a_project():
    cfg = _cfg_v2()
    r = price_project(cfg, [_b("Clubhouse", 206), _b("Bus Stop", 3), _b("Gazebo", 4)])
    for row in r["buildings"]:
        assert not any(w.startswith("min_margin_applied") for w in row["warnings"]), (
            f"{row['name']} applied a per-building floor inside a project")


def test_the_building_card_still_says_what_it_would_have_been_floored_to():
    """Suppressing the floor must not suppress the GUIDANCE — sales still needs to see it."""
    cfg = _cfg_v2()
    r = price_project(cfg, [_b("Clubhouse", 206), _b("Bus Stop", 3)])
    bus = next(x for x in r["buildings"] if x["name"] == "Bus Stop")
    assert bus["would_be_floored_to"] is not None


def test_a_thin_project_still_gets_one_floor():
    cfg = _cfg_v2()
    r = price_project(cfg, [_b("Shed", 1)])
    assert r["floor"]["applied"] > 0
    assert any(i["key"] == "project_profit_floor" for i in r["project_items"])
    assert any(w.startswith("project_profit_floor_applied") for w in r["warnings"])


def test_the_weekly_basis_is_available_and_reported_even_when_unused():
    """#449 specifies per-site-per-WEEK. On Evergrene that is $42,500 against Tim's own $30,363.

    The number is always reported so the divergence is visible rather than buried in a default.
    """
    cfg = _cfg_v2()
    r = price_project(cfg, [_b("Clubhouse", 206, days=55), _b("Bus Stop", 3, days=2)])
    assert r["floor"]["weekly_basis_would_be"] > 0
    assert r["floor"]["on_site_weeks"] >= 1

    weekly = price_project(cfg, [_b("Clubhouse", 206, days=55), _b("Bus Stop", 3, days=2)],
                           floor_basis="week")
    assert weekly["floor"]["basis"] == "week"
    assert weekly["project_total"] >= r["project_total"], "the weekly basis cannot price lower"


def test_building_basis_restores_the_old_behaviour():
    """Kept so the change is reversible per project without a deploy."""
    cfg = _cfg_v2()
    r = price_project(cfg, [_b("Bus Stop", 3), _b("Gazebo", 4)], floor_basis="building")
    assert r["project_fixed"] == [], "legacy basis must leave the fees on the buildings"
    assert any(any(w.startswith("min_margin_applied") for w in b["warnings"])
               for b in r["buildings"])


# ---------------------------------------------------------------------------
# Project items
# ---------------------------------------------------------------------------

def test_general_conditions_carries_its_markup():
    """Tim's GC is (22,800 + 9,000) x 1.15 = 36,570."""
    cfg = _cfg_v2()
    gc = ProjectItem("general_conditions", "General Conditions", 31800.0, 1.15)
    assert gc.amount == 36570.0

    r = price_project(cfg, [_b("Clubhouse", 206)], project_items=[gc])
    assert any(i["amount"] == 36570.0 for i in r["project_items"])


def test_markup_on_a_project_block_counts_as_profit():
    """It is margin the same way a roof's markup is; excluding it would understate the bid."""
    cfg = _cfg_v2()
    bare = price_project(cfg, [_b("Clubhouse", 206)])
    with_gc = price_project(cfg, [_b("Clubhouse", 206)],
                            project_items=[ProjectItem("gc", "GC", 31800.0, 1.15)])
    assert round(with_gc["profit"] - bare["profit"], 2) == round(36570.0 - 31800.0, 2)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def test_an_empty_project_is_an_error_not_a_zero():
    with pytest.raises(ValueError, match="at least one building"):
        price_project(_cfg_v2(), [])


def test_an_unknown_floor_basis_is_rejected():
    with pytest.raises(ValueError, match="floor_basis"):
        price_project(_cfg_v2(), [_b("A", 10)], floor_basis="per_fortnight")


def test_the_callers_quote_input_is_not_mutated():
    """price_project sets flags on COPIES — a caller reusing its QuoteInput must be unaffected."""
    cfg = _cfg_v2()
    b = _b("Clubhouse", 206)
    price_project(cfg, [b])
    assert b.quote.profit_floor_scope == "job"
    assert b.quote.suppress_fixed_keys == frozenset()


def test_a_single_building_quote_is_untouched_by_any_of_this():
    """The whole backward-compatibility story: defaults must reproduce today's number exactly."""
    cfg = _cfg_v2()
    q = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="13_tile",
                   num_squares=30.0, project_kind="residential", existing_roof="tile")
    assert q.profit_floor_scope == "job"
    assert q.suppress_fixed_keys == frozenset()
    r = estimate(cfg, q)
    keys = {li["key"] for li in r["line_items_detail"]}
    assert {"delivery_plywood_vents", "new_bonus_values", "permit_processing"} <= keys


def test_the_default_once_per_project_set_excludes_the_chute():
    """A delivery chute is rented for the tall STRUCTURE, not for the site."""
    assert "stories_3_5_delivery_chute" not in DEFAULT_ONCE_PER_PROJECT
    assert "tile_dumpster" in DEFAULT_ONCE_PER_PROJECT


def test_a_config_with_the_floor_disabled_applies_none():
    """enforce_profit_floor=false must mean no floor at project level either — not a silent one."""
    import copy

    from core.pricing_config import load_config
    raw = copy.deepcopy(_cfg_v2().raw)
    raw["enforce_profit_floor"] = False
    r = price_project(load_config(raw), [_b("Shed", 1)])

    assert r["floor"]["applied"] == 0.0
    assert r["floor"]["note"] == "floor not enforced by this config"
    assert not any(i["key"] == "project_profit_floor" for i in r["project_items"])
