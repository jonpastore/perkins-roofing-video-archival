"""Gutters (Tim's style-based price list, email 2026-07-17) + existing_roof demo semantics.

Style per-LF price includes matching downspouts; 2-story is a per-LF uplift; elbows,
leaf guards, leaderheads, removal are separate; jobs under the small-job threshold get
a per-LF surcharge. Missing rates raise ConfigError only when a quote uses them.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.estimator import QuoteInput, estimate
from core.pricing_config import ConfigError, load_config

_GUTTERS = {
    "styles": {
        "k6_alum": {"label": '6" Alum K-Style', "per_lf": 11.55, "two_story_per_lf": 12.95, "elbow_each": 7},
        "k7_alum": {"label": '7" Alum K-Style', "per_lf": 16.80, "two_story_per_lf": 18.20, "elbow_each": 9},
        "k6_copper": {"label": '6" Copper K-Style', "per_lf": 50.0},
    },
    "removal_per_lf": 3.85,
    "downspout_per_lf": 10.50,
    "leaf_guard_std_per_lf": 9.80,
    "leaf_guard_upgraded_per_lf": 14.00,
    "leaderhead_res_each": 98,
    "leaderhead_comm_each": 168,
    "small_job_add_per_lf": 2.00,
    "small_job_threshold_lf": 100,
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


def test_k6_alum_150lf_includes_downspouts_in_rate():
    r = estimate(_cfg(), _quote(gutter_style="k6_alum", gutter_lf=150))
    assert _item(r, "gutters")["amount"] == pytest.approx(150 * 11.55)


def test_two_story_rate_and_elbows_and_leaf_guard():
    r = estimate(_cfg(), _quote(
        gutter_style="k7_alum", gutter_lf=384, gutter_two_story=True,
        gutter_elbows=8, leaf_guard="upgraded",
    ))
    assert _item(r, "gutters")["amount"] == pytest.approx(384 * 18.20)
    assert "2-story" in _item(r, "gutters")["label"]
    assert _item(r, "gutter_elbows")["amount"] == 8 * 9
    assert _item(r, "leaf_guard")["amount"] == pytest.approx(384 * 14.00)


def test_small_job_surcharge_under_threshold():
    r = estimate(_cfg(), _quote(gutter_style="k6_alum", gutter_lf=80))
    assert _item(r, "gutters")["amount"] == pytest.approx(80 * (11.55 + 2.00))


def test_downspout_itemized_separately():
    # 4x5 downspout is its own line at downspout_per_lf, NOT bundled into the gutter rate.
    r = estimate(_cfg(), _quote(gutter_style="k6_alum", gutter_lf=150, downspout_lf=90))
    assert _item(r, "gutters")["amount"] == pytest.approx(150 * 11.55)   # gutter rate unchanged
    assert _item(r, "downspout")["amount"] == pytest.approx(90 * 10.50)
    assert "4x5" in _item(r, "downspout")["label"]


def test_downspout_without_rate_raises_configerror():
    g = {**_GUTTERS}
    g.pop("downspout_per_lf")
    with pytest.raises(ConfigError, match="downspout_per_lf"):
        estimate(_cfg(gutters=g), _quote(downspout_lf=50))


def test_removal_and_leaderheads():
    r = estimate(_cfg(), _quote(gutter_removal_lf=200, leaderheads_res=2, leaderheads_comm=1))
    assert _item(r, "gutter_removal")["amount"] == pytest.approx(200 * 3.85)
    assert _item(r, "leaderheads_res")["amount"] == 2 * 98
    assert _item(r, "leaderheads_comm")["amount"] == 168


def test_unconfigured_style_raises_configerror():
    with pytest.raises(ConfigError, match="not configured"):
        estimate(_cfg(), _quote(gutter_style="box6_comm", gutter_lf=50))


def test_no_gutter_inputs_ignores_missing_config():
    r = estimate(_cfg(gutters=None), _quote())
    assert _item(r, "gutters") is None


# ---------------------------------------------------------------------------
# existing_roof — demo priced by what's torn OFF (Zoom [13:03-14:46])
# ---------------------------------------------------------------------------

def test_tile_teardown_to_shingle_charges_tile_demo_and_dumpster():
    r = estimate(_cfg(), _quote(existing_roof="tile"))
    assert _item(r, "tile_demo") is not None          # keyed by EXISTING roof
    assert _item(r, "tile_dumpster") is not None      # tearing off tile → dump loads
    assert _item(r, "metal_demo") is None


def test_new_construction_has_no_demo_items():
    r = estimate(_cfg(), _quote(existing_roof="none"))
    assert _item(r, "tile_demo") is None
    assert _item(r, "metal_demo") is None


def test_legacy_demo_bool_keys_off_new_roof_type():
    r = estimate(_cfg(), QuoteInput(code_zone="FBC", roof_type="13_tile", num_squares=20, demo=True))
    assert _item(r, "tile_demo") is not None
