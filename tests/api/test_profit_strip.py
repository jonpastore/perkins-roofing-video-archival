"""Profit is stripped on read unless the caller holds estimating_manage."""
from api.routes.estimator import _public_estimate, _without_profit


def _payload():
    return {
        "project_total": 43075.0,
        "profit_dollars": 9000.0,
        "profit_pct": 0.21,
        "margin": {"profit_dollars": 9000.0, "oh_dollars": 4000.0},
        "commission": 4500.0,
        "estimated_commission": 4500.0,
        "profit_guidance": {"effective_floor": 2500.0},
        "line_items": {"base_cost_lm": 20000.0, "profit": 9000.0},
        "line_items_detail": [
            {"key": "base_cost_lm", "amount": 20000.0},
            {"key": "profit", "amount": 9000.0},
        ],
        "calc_audience": "internal",
        "calc_lines": [{"label": "Profit", "amount": 9000.0}],
        "calc_lines_internal": [{"label": "Profit", "amount": 9000.0}],
        "estimate_result": {"profit_dollars": 9000.0, "project_total": 43075.0},
    }


def test_without_profit_drops_every_profit_surface():
    out = _without_profit(_payload())
    assert out["project_total"] == 43075.0
    assert "profit_dollars" not in out
    assert "profit_pct" not in out
    assert "margin" not in out
    assert "commission" not in out
    assert "estimated_commission" not in out
    assert "profit_guidance" not in out
    assert "calc_lines_internal" not in out
    assert "calc_lines" not in out
    assert "profit" not in out["line_items"]
    assert all(li["key"] != "profit" for li in out["line_items_detail"])
    assert "profit_dollars" not in out["estimate_result"]
    assert out["estimate_result"]["project_total"] == 43075.0


def test_manager_keeps_profit_sales_does_not():
    payload = _payload()
    kept = _public_estimate(payload, {"role": "admin"})
    assert kept["profit_dollars"] == 9000.0
    stripped = _public_estimate(payload, {"role": "sales"})
    assert "profit_dollars" not in stripped
    assert stripped["project_total"] == 43075.0
