"""Repair/maintenance options — time-based pricing (Zoom 2026-07-20 [37:04]/[38:05]/[45:31]).

cost = labor_cost + material_cost, where labor_cost = days * daily_labor_rate(crew_size).
Golden numbers use the config-seeded rates ($1185.00/one-man-day, $1435.00/two-man-day),
confirmed by Jon 2026-07-21 (Tim's words).

Jarvis #434 (Tim, 2026-07-27 call): the engine used to stop at cost with zero profit —
"That's the cost, though. That's without profit, right?" It now adds a percent-profit term
(same mechanism/naming as the replacement path's percent_profit_pct) plus two floors, always
applied even when percent_profit_pct is omitted:
    profit = max(percent_profit_pct * cost, repair.min_profit_dollars)          # $250 fixture default
    project_total = max(cost + profit, repair.min_service_call_dollars)         # $500 fixture default
This is a real behavior change: every existing zero-percent caller now gets repriced upward by
at least $250 (profit floor) and possibly more (service-call floor) — see
test_estimate_repair_zero_pct_still_gets_profit_floor below.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.estimator import RepairInput, estimate_repair
from core.pricing_config import ConfigError, load_config


def _raw_config() -> dict:
    src = Path(__file__).parent.parent.parent / "infra" / "fixtures" / "pricing_config_exhibit_b.json"
    return json.loads(src.read_text())


def _cfg():
    return load_config(_raw_config())


# ---------------------------------------------------------------------------
# RepairInput validation
# ---------------------------------------------------------------------------

def test_repair_input_rejects_nonpositive_days():
    with pytest.raises(ValueError, match="days must be positive"):
        RepairInput(roof_type="shingle", days=0)


def test_repair_input_rejects_bad_crew_size():
    with pytest.raises(ValueError, match="crew_size must be 1 or 2"):
        RepairInput(roof_type="shingle", days=1, crew_size=3)


def test_repair_input_rejects_negative_material_cost():
    with pytest.raises(ValueError, match="material_cost must be"):
        RepairInput(roof_type="shingle", days=1, material_cost=-5)


def test_repair_input_rejects_negative_percent_profit_pct():
    with pytest.raises(ValueError, match="percent_profit_pct must be"):
        RepairInput(roof_type="shingle", days=1, percent_profit_pct=-0.1)


# ---------------------------------------------------------------------------
# estimate_repair — one-man / two-man day rate, per roof type
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("roof_type", ["shingle", "tile", "metal", "flat"])
def test_estimate_repair_one_man_per_roof_type(roof_type):
    cfg = _cfg()
    r = RepairInput(roof_type=roof_type, days=2, crew_size=1, material_cost=150)
    result = estimate_repair(cfg, r)
    assert result["roof_type"] == roof_type
    assert result["crew_size"] == 1
    assert result["daily_labor_rate"] == 1185.00
    assert result["labor_cost"] == pytest.approx(2370.00)
    assert result["material_cost"] == 150.0
    assert result["repair_cost"] == pytest.approx(2520.00)
    # No percent_profit_pct given -> the $250 minimum-profit floor fires.
    assert result["profit_dollars"] == pytest.approx(250.00)
    assert result["project_total"] == pytest.approx(2770.00)
    assert any(w.startswith("repair_min_profit_applied") for w in result["warnings"])


def test_estimate_repair_two_man_crew():
    cfg = _cfg()
    r = RepairInput(roof_type="tile", days=3, crew_size=2, material_cost=0)
    result = estimate_repair(cfg, r)
    assert result["daily_labor_rate"] == 1435.00
    assert result["labor_cost"] == pytest.approx(4305.00)
    assert result["repair_cost"] == pytest.approx(4305.00)
    assert result["profit_dollars"] == pytest.approx(250.00)
    assert result["project_total"] == pytest.approx(4555.00)


def test_estimate_repair_unknown_roof_type_raises_config_error():
    cfg = _cfg()
    r = RepairInput(roof_type="not_a_category", days=1)
    with pytest.raises(ConfigError, match="repair.roof_types"):
        estimate_repair(cfg, r)


def test_estimate_repair_missing_daily_rate_raises_config_error():
    raw = _raw_config()
    raw["repair"]["daily_labor_rate"]["one_man"] = None
    cfg = load_config(raw)
    r = RepairInput(roof_type="shingle", days=1, crew_size=1)
    with pytest.raises(ConfigError, match="repair.daily_labor_rate.one_man"):
        estimate_repair(cfg, r)


def test_estimate_repair_no_material_cost_defaults_zero():
    cfg = _cfg()
    r = RepairInput(roof_type="metal", days=1)
    result = estimate_repair(cfg, r)
    assert result["material_cost"] == 0.0
    assert result["repair_cost"] == result["labor_cost"]
    assert result["project_total"] == pytest.approx(result["repair_cost"] + result["profit_dollars"])


# ---------------------------------------------------------------------------
# Jarvis #434 — profit percentage + $250 min-profit / $500 min-service-call floors
# ---------------------------------------------------------------------------

def test_estimate_repair_tims_exact_scenario_shingle_one_day_one_man_500_material():
    """Tim, 2026-07-27 call: "Can you do one for fun, just a shingle, one day, one guy,
    $500?" ... "Does that look right, $1,685?" — "Yes." — "That's the cost, though. That's
    without profit, right?" $1,685 is exactly labor_cost(1185) + material_cost(500); the
    fixed no longer stops there — it now adds the $250 minimum profit on top.
    """
    cfg = _cfg()
    r = RepairInput(roof_type="shingle", days=1, crew_size=1, material_cost=500)
    result = estimate_repair(cfg, r)
    assert result["repair_cost"] == pytest.approx(1685.00)
    assert result["profit_dollars"] == pytest.approx(250.00)
    assert result["project_total"] == pytest.approx(1935.00)
    assert result["project_total"] != pytest.approx(1685.00)


def test_estimate_repair_percent_profit_above_floor_uses_percent():
    """A percentage large enough to clear the $250 floor prices off the percentage, not the
    floor — the normal case once an operator sets the slider."""
    cfg = _cfg()
    r = RepairInput(roof_type="shingle", days=2, crew_size=1, material_cost=0, percent_profit_pct=0.20)
    result = estimate_repair(cfg, r)
    assert result["repair_cost"] == pytest.approx(2370.00)
    assert result["profit_dollars"] == pytest.approx(474.00)  # 0.20 * 2370, > $250 floor
    assert result["project_total"] == pytest.approx(2844.00)
    assert result["warnings"] == []


def test_estimate_repair_percent_profit_under_250_floor_fires():
    """A percentage that lands under $250 gets raised to the $250 minimum profit."""
    cfg = _cfg()
    r = RepairInput(roof_type="shingle", days=1, crew_size=1, material_cost=0, percent_profit_pct=0.05)
    result = estimate_repair(cfg, r)
    assert result["repair_cost"] == pytest.approx(1185.00)
    pct_profit = 0.05 * 1185.00
    assert pct_profit < 250.00
    assert result["profit_dollars"] == pytest.approx(250.00)
    assert result["project_total"] == pytest.approx(1435.00)
    assert any(w.startswith("repair_min_profit_applied") for w in result["warnings"])
    assert not any(w.startswith("repair_min_service_call_applied") for w in result["warnings"])


def test_estimate_repair_small_fractional_day_job_hits_both_floors():
    """A small fractional-day job hits BOTH floors: the $250 minimum profit (no percent
    given) and, because the job is so small, the $500 minimum service call on top of that —
    and both are reported distinctly in warnings."""
    cfg = _cfg()
    r = RepairInput(roof_type="shingle", days=0.2, crew_size=1, material_cost=0)
    result = estimate_repair(cfg, r)
    assert result["repair_cost"] == pytest.approx(237.00)          # 0.2 * 1185
    assert result["profit_dollars"] == pytest.approx(250.00)       # min-profit floor
    assert result["repair_cost"] + result["profit_dollars"] == pytest.approx(487.00)
    assert result["project_total"] == pytest.approx(500.00)        # min-service-call floor
    warnings = result["warnings"]
    assert any(w.startswith("repair_min_profit_applied") for w in warnings)
    assert any(w.startswith("repair_min_service_call_applied") for w in warnings)
    assert len(warnings) == 2


def test_estimate_repair_zero_pct_still_gets_profit_floor():
    """BEHAVIOR CHANGE (Jarvis #434): a caller that never sets percent_profit_pct — every
    caller that predates this change — no longer gets a pure-cost quote. The $250 minimum
    profit is mandatory, not opt-in, per Tim's "minimum profit on a repair" question. Any
    caller relying on the old cost-only project_total will see prices increase by at least
    $250 (and possibly up to the $500 service-call floor on very small jobs)."""
    cfg = _cfg()
    r = RepairInput(roof_type="flat", days=1, crew_size=1, material_cost=0)
    result = estimate_repair(cfg, r)
    assert result["percent_profit_pct"] == 0.0
    assert result["profit_dollars"] == pytest.approx(250.00)
    assert result["project_total"] > result["repair_cost"]


def test_pricing_config_repair_floor_accessors_read_fixture():
    cfg = _cfg()
    assert cfg.repair_min_profit_dollars() == 250.0
    assert cfg.repair_min_service_call_dollars() == 500.0
