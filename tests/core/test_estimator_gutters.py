"""Gutters line items — 6"/7" aluminum + copper $/LF, downspouts, high-reach add.

Rates live in config["gutters"] (optional key; pending-Tim nulls). A quote that
uses a null rate raises ConfigError; quotes that don't touch gutters are
unaffected by a missing/null gutters config (backward compat).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.estimator import QuoteInput, estimate
from core.pricing_config import ConfigError, load_config

_GUTTERS = {
    "price_per_lf": {"6_inch": 12.0, "7_inch": 15.0},
    "copper_price_per_lf": {"6_inch": 55.0, "7_inch": 65.0},
    "downspout_per_lf": 10.0,
    "copper_downspout_per_lf": 48.0,
    "high_reach_add": 850.0,
}


def _cfg(gutters=_GUTTERS):
    src = Path(__file__).parent.parent.parent / "infra" / "fixtures" / "pricing_config_exhibit_b.json"
    raw = json.loads(src.read_text())
    if gutters is not None:
        raw["gutters"] = gutters
    else:
        raw.pop("gutters", None)
    return load_config(raw)


def _quote(**kw) -> QuoteInput:
    return QuoteInput(code_zone="FBC", roof_type="dimensional_shingle", num_squares=20, **kw)


def _item(result, key):
    return next((i for i in result["line_items_detail"] if i.get("key") == key), None)


def test_aluminum_6in_gutters_priced_per_lf():
    r = estimate(_cfg(), _quote(gutter_lf=100))
    it = _item(r, "gutters")
    assert it is not None
    assert it["amount"] == 100 * 12.0
    assert '6"' in it["label"]


def test_copper_7in_gutters_downspouts_and_high_reach():
    r = estimate(_cfg(), _quote(
        gutter_lf=80, gutter_size="7_inch", gutter_material="copper",
        downspout_lf=40, gutter_high_reach=True,
    ))
    assert _item(r, "gutters")["amount"] == 80 * 65.0
    assert "Copper" in _item(r, "gutters")["label"]
    assert _item(r, "downspouts")["amount"] == 40 * 48.0
    assert _item(r, "gutter_high_reach")["amount"] == 850.0


def test_null_rate_exercised_raises_configerror():
    cfg = _cfg({**_GUTTERS, "price_per_lf": {"6_inch": None, "7_inch": None}})
    with pytest.raises(ConfigError, match="pending"):
        estimate(cfg, _quote(gutter_lf=50))


def test_no_gutter_inputs_ignores_missing_config():
    r = estimate(_cfg(gutters=None), _quote())
    assert _item(r, "gutters") is None
    assert _item(r, "downspouts") is None
