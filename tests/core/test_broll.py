"""100% line-coverage tests for core.broll (Track A7).

Covers:
  _derive_keyword    — all roofing keyword rules + fallback
  broll_cues         — max_cues, min_gap spacing, empty transcript, validation
  plan_broll         — exact keyword match, fallback asset, no-asset (None),
                       overlay_spec shape, window_duration validation
"""
from __future__ import annotations

import pytest

from core.broll import _derive_keyword, broll_cues, plan_broll
from core.clip_fx import OverlaySpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seg(start: float, end: float, text: str = "") -> dict:
    return {"start": start, "end": end, "text": text}


def _asset(keyword: str, url: str = "https://example.com/clip.mp4") -> dict:
    return {"url": url, "keyword": keyword, "id": "1", "thumb": ""}


# ---------------------------------------------------------------------------
# _derive_keyword — roofing keyword rules
# ---------------------------------------------------------------------------


class TestDeriveKeyword:
    def test_hvhz(self):
        assert _derive_keyword("This is an HVHZ zone") == "hvhz roofing"

    def test_25_rule_hyphen(self):
        assert _derive_keyword("The 25-rule applies here") == "25 percent rule roof"

    def test_25_rule_space(self):
        assert _derive_keyword("25 rule compliance") == "25 percent rule roof"

    def test_wind_mitigation(self):
        assert _derive_keyword("wind mitigation inspection") == "wind mitigation inspection"

    def test_wind_mit_abbrev(self):
        assert _derive_keyword("wind mit discount") == "wind mitigation inspection"

    def test_citizens_insurance(self):
        assert _derive_keyword("Citizens Insurance renewal") == "citizens insurance florida"

    def test_storm_damage(self):
        assert _derive_keyword("storm damage assessment") == "storm damage roof repair"

    def test_storm_repair(self):
        assert _derive_keyword("storm repair estimate") == "storm damage roof repair"

    def test_flashing(self):
        assert _derive_keyword("check the flashing") == "roof flashing detail"

    def test_gutter(self):
        assert _derive_keyword("replace gutters today") == "roof gutters installation"

    def test_shingle(self):
        assert _derive_keyword("asphalt shingle replacement") == "asphalt shingle roofing"

    def test_metal_roof(self):
        assert _derive_keyword("metal roof panels") == "metal roof installation"

    def test_tile_roof(self):
        assert _derive_keyword("tile roof florida") == "tile roof florida"

    def test_leak(self):
        assert _derive_keyword("roof leaking badly") == "roof leak repair"

    def test_leaks(self):
        assert _derive_keyword("multiple leaks found") == "roof leak repair"

    def test_inspect(self):
        assert _derive_keyword("roof inspection tomorrow") == "roof inspection"

    def test_inspector(self):
        assert _derive_keyword("call an inspector") == "roof inspection"

    def test_install(self):
        assert _derive_keyword("installation begins Monday") == "roofing installation"

    def test_repair(self):
        assert _derive_keyword("repair the damaged area") == "roof repair"

    def test_ventilation(self):
        assert _derive_keyword("ventilation improves lifespan") == "roof ventilation"

    def test_decking(self):
        assert _derive_keyword("decking replacement needed") == "roof decking"

    def test_insurance_generic(self):
        assert _derive_keyword("insurance claim filed") == "homeowner insurance roof"

    def test_roofing_generic(self):
        assert _derive_keyword("roofing contractor called") == "roofing contractor florida"

    def test_fallback_no_match(self):
        assert _derive_keyword("completely unrelated topic") == "roofing contractor florida"

    def test_empty_string(self):
        assert _derive_keyword("") == "roofing contractor florida"

    def test_case_insensitive_metal(self):
        assert _derive_keyword("METAL ROOF installed") == "metal roof installation"


# ---------------------------------------------------------------------------
# broll_cues — validation
# ---------------------------------------------------------------------------


class TestBrollCuesValidation:
    def test_max_cues_zero_raises(self):
        with pytest.raises(ValueError, match="max_cues"):
            broll_cues([], max_cues=0)

    def test_max_cues_negative_raises(self):
        with pytest.raises(ValueError, match="max_cues"):
            broll_cues([], max_cues=-1)

    def test_min_gap_negative_raises(self):
        with pytest.raises(ValueError, match="min_gap"):
            broll_cues([], min_gap=-1.0)


# ---------------------------------------------------------------------------
# broll_cues — empty transcript
# ---------------------------------------------------------------------------


class TestBrollCuesEmpty:
    def test_empty_returns_empty(self):
        assert broll_cues([]) == []

    def test_empty_with_custom_params(self):
        assert broll_cues([], max_cues=3, min_gap=5.0) == []


# ---------------------------------------------------------------------------
# broll_cues — cue selection
# ---------------------------------------------------------------------------


class TestBrollCuesSelection:
    def test_single_segment_produces_one_cue(self):
        segs = [_seg(0.0, 10.0, "metal roof installation")]
        cues = broll_cues(segs)
        assert len(cues) == 1

    def test_cue_time_is_midpoint(self):
        segs = [_seg(0.0, 10.0, "roofing")]
        cues = broll_cues(segs)
        assert cues[0]["time"] == pytest.approx(5.0)

    def test_cue_carries_segment_bounds(self):
        segs = [_seg(2.0, 8.0, "roofing")]
        cues = broll_cues(segs)
        assert cues[0]["segment_start"] == pytest.approx(2.0)
        assert cues[0]["segment_end"] == pytest.approx(8.0)

    def test_max_cues_respected(self):
        segs = [_seg(float(i * 20), float(i * 20 + 10), "roofing") for i in range(10)]
        cues = broll_cues(segs, max_cues=3, min_gap=0.0)
        assert len(cues) == 3

    def test_min_gap_skips_close_segments(self):
        # segments at 0-2, 3-5, 20-22 — first and third pass min_gap=15
        segs = [
            _seg(0.0, 2.0, "roofing"),
            _seg(3.0, 5.0, "shingles"),
            _seg(20.0, 22.0, "metal roof"),
        ]
        cues = broll_cues(segs, max_cues=5, min_gap=15.0)
        assert len(cues) == 2
        assert cues[0]["time"] == pytest.approx(1.0)
        assert cues[1]["time"] == pytest.approx(21.0)

    def test_min_gap_zero_accepts_all(self):
        segs = [_seg(float(i), float(i + 1), "roofing") for i in range(5)]
        cues = broll_cues(segs, max_cues=10, min_gap=0.0)
        assert len(cues) == 5

    def test_keyword_in_cue(self):
        segs = [_seg(0.0, 10.0, "storm damage repair needed")]
        cues = broll_cues(segs)
        assert cues[0]["keyword"] == "storm damage roof repair"

    def test_missing_text_uses_fallback(self):
        segs = [{"start": 0.0, "end": 10.0}]  # no "text" key
        cues = broll_cues(segs)
        assert cues[0]["keyword"] == "roofing contractor florida"

    def test_missing_start_end_defaults(self):
        segs = [{"text": "roofing work"}]  # no start/end
        cues = broll_cues(segs)
        assert cues[0]["time"] == pytest.approx(0.0)

    def test_stops_after_max_cues_exactly(self):
        segs = [_seg(float(i * 30), float(i * 30 + 10), "roofing") for i in range(6)]
        cues = broll_cues(segs, max_cues=4, min_gap=0.0)
        assert len(cues) == 4

    def test_min_gap_exact_boundary(self):
        # midpoints at 5.0 and 13.0 — gap = 8.0, min_gap = 8.0 → second is skipped
        segs = [
            _seg(0.0, 10.0, "roofing"),
            _seg(8.0, 18.0, "shingles"),
        ]
        cues = broll_cues(segs, max_cues=5, min_gap=8.0)
        # gap between 5.0 and 13.0 is exactly 8.0 — less than 8.0 is False, so second accepted
        # 13.0 - 5.0 = 8.0, and 8.0 < 8.0 is False → second segment IS included
        assert len(cues) == 2

    def test_min_gap_just_below_skips(self):
        # midpoints at 5.0 and 12.0 — gap = 7.0 < min_gap=8.0 → second skipped
        segs = [
            _seg(0.0, 10.0, "roofing"),
            _seg(7.0, 17.0, "shingles"),
        ]
        cues = broll_cues(segs, max_cues=5, min_gap=8.0)
        assert len(cues) == 1


# ---------------------------------------------------------------------------
# plan_broll — validation
# ---------------------------------------------------------------------------


class TestPlanBrollValidation:
    def test_window_duration_zero_raises(self):
        with pytest.raises(ValueError, match="window_duration"):
            plan_broll([], [], window_duration=0.0)

    def test_window_duration_negative_raises(self):
        with pytest.raises(ValueError, match="window_duration"):
            plan_broll([], [], window_duration=-1.0)


# ---------------------------------------------------------------------------
# plan_broll — empty inputs
# ---------------------------------------------------------------------------


class TestPlanBrollEmpty:
    def test_empty_cues_returns_empty(self):
        assert plan_broll([], []) == []

    def test_empty_cues_with_assets(self):
        assets = [_asset("roofing")]
        assert plan_broll([], assets) == []


# ---------------------------------------------------------------------------
# plan_broll — asset mapping
# ---------------------------------------------------------------------------


class TestPlanBrollAssetMapping:
    def test_exact_keyword_match(self):
        cues = [{"time": 5.0, "keyword": "metal roof installation",
                 "segment_start": 0.0, "segment_end": 10.0}]
        assets = [
            _asset("metal roof installation", "https://example.com/metal.mp4"),
            _asset("shingle roofing", "https://example.com/shingle.mp4"),
        ]
        plan = plan_broll(cues, assets)
        assert plan[0]["asset"]["url"] == "https://example.com/metal.mp4"

    def test_partial_keyword_match_cue_in_asset(self):
        # cue keyword is substring of asset keyword
        cues = [{"time": 5.0, "keyword": "metal roof",
                 "segment_start": 0.0, "segment_end": 10.0}]
        assets = [_asset("metal roof installation", "https://example.com/metal.mp4")]
        plan = plan_broll(cues, assets)
        assert plan[0]["asset"] is not None
        assert plan[0]["asset"]["url"] == "https://example.com/metal.mp4"

    def test_partial_keyword_match_asset_in_cue(self):
        # asset keyword is substring of cue keyword
        cues = [{"time": 5.0, "keyword": "metal roof installation florida",
                 "segment_start": 0.0, "segment_end": 10.0}]
        assets = [_asset("metal roof", "https://example.com/metal.mp4")]
        plan = plan_broll(cues, assets)
        assert plan[0]["asset"] is not None

    def test_no_match_falls_back_to_first_asset(self):
        cues = [{"time": 5.0, "keyword": "unrelated topic",
                 "segment_start": 0.0, "segment_end": 10.0}]
        assets = [_asset("roofing contractor florida", "https://example.com/fallback.mp4")]
        plan = plan_broll(cues, assets)
        assert plan[0]["asset"]["url"] == "https://example.com/fallback.mp4"

    def test_no_asset_returns_none(self):
        cues = [{"time": 5.0, "keyword": "metal roof installation",
                 "segment_start": 0.0, "segment_end": 10.0}]
        plan = plan_broll(cues, [])
        assert plan[0]["asset"] is None
        assert plan[0]["overlay_spec"] is None

    def test_overlay_spec_shape_when_asset_available(self):
        cues = [{"time": 10.0, "keyword": "roofing",
                 "segment_start": 5.0, "segment_end": 15.0}]
        assets = [_asset("roofing contractor florida")]
        plan = plan_broll(cues, assets, window_duration=4.0)
        spec = plan[0]["overlay_spec"]
        assert isinstance(spec, OverlaySpec)
        assert spec.start == pytest.approx(10.0)
        assert spec.end == pytest.approx(14.0)
        assert spec.x == "0"
        assert spec.y == "0"

    def test_overlay_start_end_in_plan(self):
        cues = [{"time": 20.0, "keyword": "roofing",
                 "segment_start": 15.0, "segment_end": 25.0}]
        assets = [_asset("roofing")]
        plan = plan_broll(cues, assets, window_duration=5.0)
        assert plan[0]["overlay_start"] == pytest.approx(20.0)
        assert plan[0]["overlay_end"] == pytest.approx(25.0)

    def test_plan_preserves_time_and_keyword(self):
        cues = [{"time": 7.5, "keyword": "hvhz roofing",
                 "segment_start": 2.0, "segment_end": 13.0}]
        assets = [_asset("hvhz roofing")]
        plan = plan_broll(cues, assets)
        assert plan[0]["time"] == pytest.approx(7.5)
        assert plan[0]["keyword"] == "hvhz roofing"

    def test_multiple_cues_produce_multiple_plan_entries(self):
        cues = [
            {"time": 5.0, "keyword": "metal roof installation",
             "segment_start": 0.0, "segment_end": 10.0},
            {"time": 20.0, "keyword": "storm damage roof repair",
             "segment_start": 15.0, "segment_end": 25.0},
        ]
        assets = [
            _asset("metal roof installation"),
            _asset("storm damage roof repair"),
        ]
        plan = plan_broll(cues, assets)
        assert len(plan) == 2

    def test_overlay_spec_image_path_from_asset_url(self):
        url = "https://cdn.pexels.com/video.mp4"
        cues = [{"time": 3.0, "keyword": "roofing",
                 "segment_start": 0.0, "segment_end": 6.0}]
        assets = [{"url": url, "keyword": "roofing", "id": "42", "thumb": ""}]
        plan = plan_broll(cues, assets)
        assert plan[0]["overlay_spec"].image_path == url

    def test_cue_missing_time_defaults_zero(self):
        cues = [{"keyword": "roofing", "segment_start": 0.0, "segment_end": 5.0}]
        assets = [_asset("roofing")]
        plan = plan_broll(cues, assets)
        assert plan[0]["time"] == pytest.approx(0.0)

    def test_window_duration_custom(self):
        cues = [{"time": 10.0, "keyword": "roofing",
                 "segment_start": 5.0, "segment_end": 15.0}]
        assets = [_asset("roofing")]
        plan = plan_broll(cues, assets, window_duration=7.0)
        assert plan[0]["overlay_end"] == pytest.approx(17.0)


# ---------------------------------------------------------------------------
# Integration: broll_cues → plan_broll round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_end_to_end(self):
        segs = [
            _seg(0.0, 12.0, "HVHZ zone requires special roofing"),
            _seg(30.0, 42.0, "metal roof installation process"),
            _seg(60.0, 72.0, "storm damage repair estimate"),
        ]
        cues = broll_cues(segs, max_cues=3, min_gap=10.0)
        assert len(cues) == 3

        assets = [
            _asset("hvhz roofing", "https://example.com/hvhz.mp4"),
            _asset("metal roof installation", "https://example.com/metal.mp4"),
            _asset("storm damage roof repair", "https://example.com/storm.mp4"),
        ]
        plan = plan_broll(cues, assets, window_duration=4.0)
        assert len(plan) == 3
        for entry in plan:
            assert entry["overlay_spec"] is not None
            assert isinstance(entry["overlay_spec"], OverlaySpec)
            assert entry["overlay_end"] - entry["overlay_start"] == pytest.approx(4.0)

    def test_end_to_end_no_assets(self):
        segs = [_seg(0.0, 10.0, "roofing work today")]
        cues = broll_cues(segs, max_cues=2)
        plan = plan_broll(cues, [])
        assert plan[0]["asset"] is None
        assert plan[0]["overlay_spec"] is None
