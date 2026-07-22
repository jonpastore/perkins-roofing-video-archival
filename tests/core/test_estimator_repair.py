"""Repair options — time-based pricing (Zoom 2026-07-20 [37:04]/[38:05]/[45:31]).

Simple calculation: labor_cost = days * daily_labor_rate(crew_size); total = labor_cost + material_cost.
Golden numbers use the config-seeded rates ($1185.00/one-man-day, $1435.00/two-man-day),
confirmed by Jon 2026-07-21 (Tim's words).
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
    assert result["project_total"] == pytest.approx(2520.00)


def test_estimate_repair_two_man_crew():
    cfg = _cfg()
    r = RepairInput(roof_type="tile", days=3, crew_size=2, material_cost=0)
    result = estimate_repair(cfg, r)
    assert result["daily_labor_rate"] == 1435.00
    assert result["labor_cost"] == pytest.approx(4305.00)
    assert result["project_total"] == pytest.approx(4305.00)


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
    assert result["project_total"] == result["labor_cost"]
