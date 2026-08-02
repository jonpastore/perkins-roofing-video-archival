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
    dominant_roof_type,
    price_project,
    project_snapshot,
    total_squares,
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


# ---------------------------------------------------------------------------
# The project snapshot: how a nine-building bid survives as ONE proposal
# ---------------------------------------------------------------------------

def test_dominant_roof_type_is_by_area_not_order():
    """Listed first != biggest. A tile job must not call itself metal."""
    buildings = [
        Building(name="Bus Stop", quote=QuoteInput(
            code_zone="FBC", slope_type="sloped", roof_type="standing_seam_metal",
            num_squares=3)),
        Building(name="Clubhouse", quote=QuoteInput(
            code_zone="FBC", slope_type="sloped", roof_type="13_tile", num_squares=40)),
    ]
    assert dominant_roof_type(buildings) == "13_tile"


def test_dominant_roof_type_sums_across_buildings_of_the_same_type():
    """Three small tile roofs outweigh one bigger metal one — the sum decides, not the max."""
    buildings = [
        Building(name="M", quote=QuoteInput(code_zone="FBC", slope_type="sloped",
                                            roof_type="standing_seam_metal", num_squares=20)),
        Building(name="T1", quote=QuoteInput(code_zone="FBC", slope_type="sloped",
                                             roof_type="13_tile", num_squares=8)),
        Building(name="T2", quote=QuoteInput(code_zone="FBC", slope_type="sloped",
                                             roof_type="13_tile", num_squares=8)),
        Building(name="T3", quote=QuoteInput(code_zone="FBC", slope_type="sloped",
                                             roof_type="13_tile", num_squares=8)),
    ]
    assert dominant_roof_type(buildings) == "13_tile"


def test_dominant_roof_type_is_stable_on_a_tie():
    """Equal area must not depend on dict ordering — the same bid twice is the same answer."""
    buildings = [
        Building(name="A", quote=QuoteInput(code_zone="FBC", slope_type="sloped",
                                            roof_type="standing_seam_metal", num_squares=10)),
        Building(name="B", quote=QuoteInput(code_zone="FBC", slope_type="sloped",
                                            roof_type="13_tile", num_squares=10)),
    ]
    assert dominant_roof_type(buildings) == dominant_roof_type(list(reversed(buildings)))


def test_project_snapshot_keeps_every_required_key_a_scalar():
    """core/proposal.py must need NO change: the project keys are additive."""
    from core.proposal import _REQUIRED_SNAPSHOT_KEYS

    buildings = [_b("Clubhouse", 30), _b("Bus Stop", 3)]
    roll_up = price_project(_cfg_v2(), buildings)
    base = {
        "pricing_config_hash": "abc123", "sent_at_iso": "2026-08-01T00:00:00Z",
        "roof_type": "13_tile", "num_squares": 30, "tiers": {}, "deposit_policy": {},
        "floors": {"min_profit_pct": 0.13, "min_profit_plus_oh_pct": 0.33},
        "estimator_version": "v2",
    }
    snap = project_snapshot(roll_up, buildings, base)

    for key in _REQUIRED_SNAPSHOT_KEYS:
        assert key in snap, key
    assert isinstance(snap["roof_type"], str)
    assert snap["num_squares"] == 33
    assert snap["project_totals"]["building_count"] == 2
    assert len(snap["buildings"]) == 2


def test_project_snapshot_carries_the_site_fees_into_project_items():
    """project_fixed is site money. If the snapshot drops it the proposal under-states the bid."""
    buildings = [_b("Clubhouse", 30), _b("Bus Stop", 3)]
    roll_up = price_project(_cfg_v2(), buildings)
    snap = project_snapshot(roll_up, buildings, {})

    keys = {i["key"] for i in snap["project_items"]}
    assert "delivery_plywood_vents" in keys
    assert snap["project_totals"]["project_total"] == roll_up["project_total"]


def test_project_snapshot_does_not_mutate_the_base():
    """The caller's single-building snapshot must survive being used as a base."""
    buildings = [_b("Clubhouse", 30)]
    roll_up = price_project(_cfg_v2(), buildings)
    base = {"roof_type": "standing_seam_metal", "num_squares": 1}
    project_snapshot(roll_up, buildings, base)
    assert base == {"roof_type": "standing_seam_metal", "num_squares": 1}


# ---------------------------------------------------------------------------
# Mixed sloped+flat roofs — 36% of Perkins roofs, and Evergrene's Clubhouse
# ---------------------------------------------------------------------------

def _mixed(name: str, sloped: float, flat: float, flat_type: str = "tpo") -> Building:
    return Building(name=name, quote=QuoteInput(
        code_zone="FBC", slope_type="sloped", roof_type="13_tile", num_squares=sloped,
        flat_squares=flat, flat_roof_type=flat_type,
        project_kind="commercial", existing_roof="tile"))


def test_total_squares_counts_the_flat_section():
    """A roof with both sections is ONE job and the estimator prices both.

    Counting only num_squares reported a 20+15 Clubhouse as 20 squares against a total that
    priced 35 — an implied $/sq 75% high, and that figure reaches a customer via the snapshot.
    """
    assert total_squares([_mixed("Clubhouse", 20, 15)]) == 35
    assert total_squares([_mixed("A", 20, 15), _mixed("B", 10, 0)]) == 45


def test_total_squares_tolerates_a_missing_flat_section():
    """flat_squares defaults to 0 but may arrive as None from a stored snapshot."""
    b = _b("Sloped only", 30)
    assert total_squares([b]) == 30


def test_dominant_roof_type_counts_the_flat_system_under_its_own_type():
    """A bid that is mostly TPO by area must not call itself tile."""
    # 5 sloped tile + 40 flat TPO -> TPO dominates.
    assert dominant_roof_type([_mixed("Warehouse", 5, 40, "tpo")]) == "tpo"
    # 30 sloped tile + 5 flat TPO -> tile dominates.
    assert dominant_roof_type([_mixed("Clubhouse", 30, 5, "tpo")]) == "13_tile"


def test_project_snapshot_num_squares_matches_what_was_priced():
    buildings = [_mixed("Clubhouse", 20, 15)]
    roll_up = price_project(_cfg_v2(), [_b("Clubhouse", 20)])  # priced separately; shape only
    snap = project_snapshot(roll_up, buildings, {})
    assert snap["num_squares"] == 35


# ---------------------------------------------------------------------------
# The week basis is meaningless without days — and used to price ONE week silently
# ---------------------------------------------------------------------------

def _per_sq(name: str, days: float | None = None) -> Building:
    """A per_sq-overhead building: profit_guidance is ABSENT, so days are unknown."""
    return Building(name=name, days=days, quote=QuoteInput(
        code_zone="FBC", slope_type="sloped", roof_type="13_tile", num_squares=30,
        project_kind="commercial", existing_roof="tile", overhead_mode="per_sq"))


def test_week_basis_without_days_refuses_instead_of_pricing_one_week():
    """Nine structures on an 18-week site were quoting ONE week's $2,500, with no warning."""
    import pytest

    with pytest.raises(ValueError, match="needs on-site days"):
        price_project(_cfg_v2(), [_per_sq(f"B{i}") for i in range(9)], floor_basis="week")


def test_week_basis_with_explicit_days_counts_the_whole_site():
    """Tim's sheet carries a day column per building — that is the supported input."""
    r = price_project(_cfg_v2(), [_per_sq(f"B{i}", days=10) for i in range(9)],
                      floor_basis="week")
    assert r["floor"]["on_site_days"] == 90
    assert r["floor"]["on_site_weeks"] == 18
    assert r["floor"]["target"] == 18 * 2500


def test_project_basis_says_so_when_it_cannot_cost_the_449_divergence():
    """The divergence warning exists so #449's spec gap is visible rather than buried.

    With no days it silently compared against ONE week's floor, understating the gap.
    """
    r = price_project(_cfg_v2(), [_per_sq(f"B{i}") for i in range(9)], floor_basis="project")
    assert any("project_floor_basis_undisclosed" in w for w in r["warnings"])
    assert not any("project_floor_basis_divergence" in w for w in r["warnings"])


def test_unknown_once_per_project_key_is_refused():
    """An unrecognised key is ignored on BOTH sides — not suppressed per building, not re-added.

    `stories_3_5_delivery_chute` is the plausible wrong guess: this module's own docstring names
    it two lines below the default set. Silently, it reverted tile_dumpster to nine ceil()s.
    """
    import pytest

    with pytest.raises(ValueError, match="cannot suppress"):
        price_project(_cfg_v2(), [_b("Clubhouse", 30)],
                      once_per_project=frozenset({"delivery_plywood_vents",
                                                  "stories_3_5_delivery_chute"}))


def test_commercial_permit_adder_is_per_commercial_permit_not_per_permit():
    """One commercial structure among nine used to put the adder on ALL nine permits."""
    def _kind(name, kind):
        return Building(name=name, quote=QuoteInput(
            code_zone="FBC", slope_type="sloped", roof_type="13_tile", num_squares=10,
            project_kind=kind, existing_roof="tile"))

    cfg = _cfg_v2()
    buildings = [_kind("Commercial", "commercial")] + [
        _kind(f"Res{i}", "residential") for i in range(8)]
    r = price_project(cfg, buildings, permit_count=9)
    permit = next(f for f in r["project_fixed"] if f["key"] == "permit_processing")

    base = float(cfg.raw["permit_processing"])
    add = float(cfg.raw["permit_commercial_add"])
    assert permit["amount"] == round(base * 9 + add * 1, 2)
    assert "commercial adder on 1" in permit["basis"]


def test_permit_count_defaults_to_one_per_building():
    """Tim, 2026-08-02: one permit per building/structure. Verified against his own books —
    73 of the 333 Knowify projects carrying a permit line bill more than one.

    The default used to be 1, i.e. one permit for a nine-structure site, which is the case his
    books show is the outlier."""
    cfg = _cfg_v2()
    r = price_project(cfg, [_b("Clubhouse", 30), _b("Gate A", 10), _b("Gate B", 10)])
    permit = next(f for f in r["project_fixed"] if f["key"] == "permit_processing")
    # _b() builds commercial structures, so each of the three permits carries the adder too.
    per_permit = float(cfg.raw["permit_processing"]) + float(cfg.raw["permit_commercial_add"])

    assert r["permit_count"] == 3
    assert permit["amount"] == round(per_permit * 3, 2)
    assert "one per building" in permit["basis"]


def test_an_explicit_permit_count_still_wins():
    """A county that issued ONE permit for the whole site is said out loud, not defaulted to."""
    cfg = _cfg_v2()
    r = price_project(cfg, [_b("Clubhouse", 30), _b("Gate A", 10)], permit_count=1)
    permit = next(f for f in r["project_fixed"] if f["key"] == "permit_processing")

    assert r["permit_count"] == 1
    assert permit["amount"] == round(float(cfg.raw["permit_processing"])
                                     + float(cfg.raw["permit_commercial_add"]), 2)
    assert "not the 2-building default" in permit["basis"]


def test_permit_count_below_one_is_refused():
    """0 permits prices the fee away silently; a bid always pulls at least one."""
    with pytest.raises(ValueError, match="permit_count must be at least 1"):
        price_project(_cfg_v2(), [_b("Clubhouse", 30)], permit_count=0)


def test_building_address_is_carried_through_the_roll_up():
    """It moves no money — it has to reach the proposal render, and nothing else."""
    cfg = _cfg_v2()
    shared = price_project(cfg, [_b("Clubhouse", 30), _b("Gate A", 10)])
    with_addr = price_project(cfg, [
        Building(name="Clubhouse", quote=_b("Clubhouse", 30).quote),
        Building(name="Gate A", quote=_b("Gate A", 10).quote, address="1 Hood Rd"),
    ])
    assert [b["address"] for b in with_addr["buildings"]] == [None, "1 Hood Rd"]
    assert with_addr["project_total"] == shared["project_total"]


def test_a_single_site_permit_is_commercial_if_any_scope_is():
    """permit_count=1 means one permit for the site; commercial scope makes it a commercial one."""
    def _kind(name, kind):
        return Building(name=name, quote=QuoteInput(
            code_zone="FBC", slope_type="sloped", roof_type="13_tile", num_squares=10,
            project_kind=kind, existing_roof="tile"))

    cfg = _cfg_v2()
    r = price_project(cfg, [_kind("Commercial", "commercial"), _kind("Res", "residential")],
                      permit_count=1)
    permit = next(f for f in r["project_fixed"] if f["key"] == "permit_processing")
    assert permit["amount"] == round(float(cfg.raw["permit_processing"])
                                     + float(cfg.raw["permit_commercial_add"]), 2)


def test_duplicate_structure_names_refused_at_core():
    """The API layer rejects too, but the guard belongs here — price_project is the pure entry."""
    import pytest

    with pytest.raises(ValueError, match="duplicate structure name"):
        price_project(_cfg_v2(), [_b("Main", 10), _b("Main", 12)])


def test_building_allocation_refused_at_core():
    import pytest

    with pytest.raises(ValueError, match="not implemented"):
        price_project(_cfg_v2(), [_b("Clubhouse", 30)], project_items=[
            ProjectItem(key="addons", label="Sloped add-ons", cost=42050,
                        allocation="building:Clubhouse")])


def test_duplicate_project_item_keys_refused_at_core():
    import pytest

    with pytest.raises(ValueError, match="duplicate project_item key"):
        price_project(_cfg_v2(), [_b("Clubhouse", 30)], project_items=[
            ProjectItem(key="gc", label="A", cost=100),
            ProjectItem(key="gc", label="B", cost=200)])


def test_per_building_squares_counts_both_sections():
    """The roll-up's per-building `squares` must agree with total_squares().

    Reporting the sloped side only made one screen show 35 sq and 20 sq for the same building.
    Uses the exhibit_b fixture because _cfg_v2 leaves every low-slope base price null, so a mixed
    roof cannot actually be priced against it.
    """
    import json
    from pathlib import Path

    from core.pricing_config import load_config

    raw = json.loads((Path(__file__).parent.parent.parent / "infra" / "fixtures"
                      / "pricing_config_exhibit_b.json").read_text())
    buildings = [_mixed("Clubhouse", 20, 15, "tpo_adhered")]
    r = price_project(load_config(raw), buildings)
    assert r["buildings"][0]["squares"] == 35
    assert sum(b["squares"] for b in r["buildings"]) == total_squares(buildings)


# ---------------------------------------------------------------------------
# Commission on a multi-building bid (#452)
# ---------------------------------------------------------------------------
# A single-roof quote has reported `estimated_commission` all along. A project reported NOTHING —
# so on exactly the bid shape #430/#449 was built for, the salesperson saw a blank where their own
# payout goes. Found by the critic in the 2026-08-02 R2.

def test_project_reports_a_commission_at_all():
    r = price_project(_cfg_v2(), [_b("A", 30), _b("B", 20)])
    assert r["commission"] > 0
    assert r["commission_base"] > 0


def test_commission_on_the_profit_basis_is_a_share_of_the_rolled_up_profit():
    cfg = _cfg_v2()
    r = price_project(cfg, [_b("A", 30), _b("B", 20)])
    assert r["commission_basis"] == "profit"
    assert r["commission_base"] == r["profit"]
    assert r["commission"] == pytest.approx(r["profit"] * r["commission_rate"])


def test_commission_on_the_job_basis_is_a_share_of_gross():
    cfg = _cfg_v2()
    b = _b("A", 30)
    from dataclasses import replace
    b = Building(name=b.name, days=b.days, quote=replace(b.quote, commission_basis="job"))
    r = price_project(cfg, [b, _b("B", 20)])
    assert r["commission_basis"] == "job"
    assert r["commission_base"] == r["project_total"]
    assert r["commission"] == pytest.approx(r["project_total"] * r["commission_rate"])


def test_commission_is_computed_after_the_floor_not_before():
    """The floor MOVES the profit line, and on the profit basis commission is a percentage of that
    line. Paying on the pre-floor number would pay the salesperson on a figure the customer was
    never charged — the same ordering the single-roof path uses."""
    cfg = _cfg_v2()
    r = price_project(cfg, [_b("Tiny", 3)])          # small enough to be floored
    assert r["floor"], "expected this bid to be floored"
    assert r["commission"] == pytest.approx(r["profit"] * r["commission_rate"])


def test_operator_override_wins_over_the_config_rate():
    from dataclasses import replace
    b = _b("A", 30)
    b = Building(name=b.name, days=b.days,
                 quote=replace(b.quote, commission_rate_override=0.075))   # Josh's split
    r = price_project(_cfg_v2(), [b, _b("B", 20)])
    assert r["commission_rate"] == 0.075


def test_project_block_margin_is_reported_and_flagged_not_silently_commissioned():
    """#451 is unresolved: nobody has said whether markup on general conditions pays the
    salesperson. It sits inside the profit base, so the roll-up states the amount and what the
    payout would be without it, rather than resolving it either way."""
    cfg = _cfg_v2()
    gc = ProjectItem(key="gc", label="General Conditions", cost=30000.0, markup=1.15,
                     allocation="project")
    r = price_project(cfg, [_b("A", 30)], project_items=[gc])
    assert r["project_items_margin"] == pytest.approx(30000 * 0.15)
    warn = next(w for w in r["warnings"]
                if w.startswith("commission_base_includes_project_blocks"))
    assert "#451" in warn
    # The warning must carry BOTH payouts, or it is a question without its price.
    excl = (r["profit"] - r["project_items_margin"]) * r["commission_rate"]
    assert f"${excl:,.2f}" in warn


def test_no_project_block_warning_when_there_are_no_blocks():
    r = price_project(_cfg_v2(), [_b("A", 30)])
    assert not any(w.startswith("commission_base_includes_project_blocks")
                   for w in r["warnings"])


def test_snapshot_carries_the_commission_through():
    """A roll-up that computes commission and then drops it on the way out is the same blank by
    a longer route — the snapshot is what the salesperson's screen reads."""
    cfg = _cfg_v2()
    buildings = [_b("A", 30), _b("B", 20)]
    r = price_project(cfg, buildings)
    snap = project_snapshot(r, buildings, {"roof_type": "13_tile", "num_squares": 1})
    assert snap["project_totals"]["commission"] == r["commission"]
    assert snap["project_totals"]["commission_basis"] == r["commission_basis"]
