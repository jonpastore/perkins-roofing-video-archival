"""100% line-coverage tests for core.reframe (Track A2).

Covers:
- crop_filter_9x16: all three ratios, focus_x clamping, centre fallback,
  even-pixel enforcement, error cases.
- speaker_track_windows: smoothing/jitter-cap, None fallback, empty input,
  error cases, exact boundary values.
- SpeakerDetector protocol + MockSpeakerDetector.
- build_reframe_cmd: static centre-crop (empty windows), animated crop
  (non-empty windows), ratio variants, arg-list structure.
- _build_x_expr: exercised via build_reframe_cmd with windows.
"""
from __future__ import annotations

import pytest

import core.reframe as rf  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_crop(s: str) -> tuple[int, int, int, int]:
    """Parse 'crop=W:H:X:Y' → (w, h, x, y)."""
    body = s[len("crop="):]
    w, h, x, y = (int(v) for v in body.split(":"))
    return w, h, x, y


# ---------------------------------------------------------------------------
# crop_filter_9x16 — ratio 9:16 (default)
# ---------------------------------------------------------------------------


class TestCropFilter9x16_Default:
    def test_returns_string(self) -> None:
        assert isinstance(rf.crop_filter_9x16(1920, 1080), str)

    def test_starts_with_crop(self) -> None:
        assert rf.crop_filter_9x16(1920, 1080).startswith("crop=")

    def test_standard_1920x1080_width(self) -> None:
        w, h, x, y = _parse_crop(rf.crop_filter_9x16(1920, 1080))
        # 1080 * 9/16 = 607 (truncated)
        assert w == 607 - (607 % 2)  # 606

    def test_standard_1920x1080_height(self) -> None:
        _, h, _, _ = _parse_crop(rf.crop_filter_9x16(1920, 1080))
        assert h == 1080

    def test_standard_1920x1080_centre_x(self) -> None:
        w, h, x, y = _parse_crop(rf.crop_filter_9x16(1920, 1080))
        assert x == (1920 - w) // 2

    def test_standard_1920x1080_y_zero(self) -> None:
        _, _, _, y = _parse_crop(rf.crop_filter_9x16(1920, 1080))
        assert y == 0

    def test_crop_w_is_even(self) -> None:
        w, _, _, _ = _parse_crop(rf.crop_filter_9x16(1920, 1080))
        assert w % 2 == 0

    def test_crop_h_is_even(self) -> None:
        _, h, _, _ = _parse_crop(rf.crop_filter_9x16(1920, 1080))
        assert h % 2 == 0

    def test_portrait_source_1080x1920(self) -> None:
        # For a portrait source, width becomes the binding constraint.
        w, h, x, y = _parse_crop(rf.crop_filter_9x16(1080, 1920))
        assert w == 1080
        assert h <= 1920
        assert w % 2 == 0
        assert h % 2 == 0

    def test_focus_x_centres_window(self) -> None:
        # focus_x=0.5 should produce the same x as centre-crop.
        w_centre, _, x_centre, _ = _parse_crop(rf.crop_filter_9x16(1920, 1080))
        w_focus, _, x_focus, _ = _parse_crop(rf.crop_filter_9x16(1920, 1080, focus_x=0.5))
        assert w_centre == w_focus
        assert x_focus == x_centre

    def test_focus_x_left_edge_clamped(self) -> None:
        # focus_x=0.0 → x should be 0 (clamped, not negative).
        _, _, x, _ = _parse_crop(rf.crop_filter_9x16(1920, 1080, focus_x=0.0))
        assert x == 0

    def test_focus_x_right_edge_clamped(self) -> None:
        # focus_x=1.0 → x should be src_w - crop_w (clamped at right edge).
        w, _, x, _ = _parse_crop(rf.crop_filter_9x16(1920, 1080, focus_x=1.0))
        assert x == 1920 - w

    def test_focus_x_left_quarter(self) -> None:
        w, _, x, _ = _parse_crop(rf.crop_filter_9x16(1920, 1080, focus_x=0.25))
        # Centre of crop window = x + w//2 ≈ 0.25 * 1920 = 480, clamped to valid range.
        assert x >= 0
        assert x + w <= 1920

    def test_focus_x_right_quarter(self) -> None:
        w, _, x, _ = _parse_crop(rf.crop_filter_9x16(1920, 1080, focus_x=0.75))
        assert x >= 0
        assert x + w <= 1920

    def test_invalid_ratio_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported ratio"):
            rf.crop_filter_9x16(1920, 1080, ratio="16:9")

    def test_zero_width_raises(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            rf.crop_filter_9x16(0, 1080)

    def test_zero_height_raises(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            rf.crop_filter_9x16(1920, 0)

    def test_negative_dimension_raises(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            rf.crop_filter_9x16(-1, 1080)


# ---------------------------------------------------------------------------
# crop_filter_9x16 — ratio 1:1
# ---------------------------------------------------------------------------


class TestCropFilter1x1:
    def test_square_crop_from_wide(self) -> None:
        w, h, x, y = _parse_crop(rf.crop_filter_9x16(1920, 1080, ratio="1:1"))
        assert w == h

    def test_square_crop_equals_height(self) -> None:
        w, h, _, _ = _parse_crop(rf.crop_filter_9x16(1920, 1080, ratio="1:1"))
        # Height is the binding constraint: crop_h = src_h = 1080 (even already).
        assert h == 1080

    def test_square_crop_is_even(self) -> None:
        w, h, _, _ = _parse_crop(rf.crop_filter_9x16(1920, 1080, ratio="1:1"))
        assert w % 2 == 0
        assert h % 2 == 0

    def test_square_crop_centre_x(self) -> None:
        w, _, x, _ = _parse_crop(rf.crop_filter_9x16(1920, 1080, ratio="1:1"))
        assert x == (1920 - w) // 2


# ---------------------------------------------------------------------------
# crop_filter_9x16 — ratio 4:5
# ---------------------------------------------------------------------------


class TestCropFilter4x5:
    def test_4x5_height_greater_than_width(self) -> None:
        w, h, _, _ = _parse_crop(rf.crop_filter_9x16(1920, 1080, ratio="4:5"))
        assert h > w

    def test_4x5_dimensions_even(self) -> None:
        w, h, _, _ = _parse_crop(rf.crop_filter_9x16(1920, 1080, ratio="4:5"))
        assert w % 2 == 0
        assert h % 2 == 0

    def test_4x5_fits_within_source(self) -> None:
        w, h, x, y = _parse_crop(rf.crop_filter_9x16(1920, 1080, ratio="4:5"))
        assert x + w <= 1920
        assert y + h <= 1080


# ---------------------------------------------------------------------------
# crop_filter_9x16 — width-binding constraint (else branch, lines 100-101)
# ---------------------------------------------------------------------------


class TestCropFilterWidthBinding:
    def test_portrait_1x1_width_is_binding(self) -> None:
        # 640×1280 source, 1:1 ratio: cw_from_h = 1280 > 640, so else branch.
        w, h, x, y = _parse_crop(rf.crop_filter_9x16(640, 1280, ratio="1:1"))
        assert w == 640
        assert h <= 1280
        assert w % 2 == 0
        assert h % 2 == 0

    def test_portrait_1x1_fits_within_source(self) -> None:
        w, h, x, y = _parse_crop(rf.crop_filter_9x16(640, 1280, ratio="1:1"))
        assert x + w <= 640
        assert y + h <= 1280


# ---------------------------------------------------------------------------
# MockSpeakerDetector + SpeakerDetector protocol
# ---------------------------------------------------------------------------


class TestMockSpeakerDetector:
    def test_returns_list(self) -> None:
        det = rf.MockSpeakerDetector()
        result = det.detect("video.mp4", [{"start": 0.0, "end": 5.0}])
        assert isinstance(result, list)

    def test_length_matches_segments(self) -> None:
        det = rf.MockSpeakerDetector()
        segs = [{"start": i, "end": i + 1.0, "x": None} for i in range(5)]
        assert len(det.detect("v.mp4", segs)) == 5

    def test_all_values_are_0_5(self) -> None:
        det = rf.MockSpeakerDetector()
        segs = [{"start": 0.0, "end": 1.0}]
        assert det.detect("v.mp4", segs) == [0.5]

    def test_empty_segments(self) -> None:
        det = rf.MockSpeakerDetector()
        assert det.detect("v.mp4", []) == []

    def test_satisfies_protocol(self) -> None:
        det = rf.MockSpeakerDetector()
        assert isinstance(det, rf.SpeakerDetector)


# ---------------------------------------------------------------------------
# speaker_track_windows — basic behaviour
# ---------------------------------------------------------------------------


class TestSpeakerTrackWindowsBasic:
    def test_empty_returns_empty(self) -> None:
        assert rf.speaker_track_windows([]) == []

    def test_single_segment_returns_one_keyframe(self) -> None:
        segs = [{"start": 0.0, "end": 2.0, "x": 0.5}]
        result = rf.speaker_track_windows(segs)
        assert len(result) == 1

    def test_keyframe_has_t_and_x(self) -> None:
        segs = [{"start": 0.0, "end": 2.0, "x": 0.5}]
        kf = rf.speaker_track_windows(segs)[0]
        assert "t" in kf
        assert "x" in kf

    def test_t_is_midpoint(self) -> None:
        segs = [{"start": 0.0, "end": 2.0, "x": 0.5}]
        kf = rf.speaker_track_windows(segs)[0]
        assert kf["t"] == pytest.approx(1.0)

    def test_x_passed_through_when_no_pan(self) -> None:
        segs = [{"start": 0.0, "end": 2.0, "x": 0.7}]
        kf = rf.speaker_track_windows(segs)[0]
        assert kf["x"] == pytest.approx(0.7)

    def test_none_x_falls_back_to_previous(self) -> None:
        segs = [
            {"start": 0.0, "end": 1.0, "x": 0.8},
            {"start": 1.0, "end": 2.0, "x": None},
        ]
        result = rf.speaker_track_windows(segs, smoothing=1.0)
        assert result[1]["x"] == pytest.approx(0.8)

    def test_none_x_first_segment_defaults_to_0_5(self) -> None:
        segs = [{"start": 0.0, "end": 1.0, "x": None}]
        result = rf.speaker_track_windows(segs)
        assert result[0]["x"] == pytest.approx(0.5)

    def test_multiple_segments_correct_length(self) -> None:
        segs = [{"start": i, "end": i + 1.0, "x": 0.5} for i in range(4)]
        assert len(rf.speaker_track_windows(segs)) == 4

    def test_invalid_smoothing_raises(self) -> None:
        with pytest.raises(ValueError, match="smoothing must be"):
            rf.speaker_track_windows([{"start": 0.0, "end": 1.0, "x": 0.5}], smoothing=0)

    def test_negative_smoothing_raises(self) -> None:
        with pytest.raises(ValueError, match="smoothing must be"):
            rf.speaker_track_windows([{"start": 0.0, "end": 1.0, "x": 0.5}], smoothing=-0.1)


# ---------------------------------------------------------------------------
# speaker_track_windows — smoothing / jitter-cap
# ---------------------------------------------------------------------------


class TestSpeakerTrackWindowsSmoothing:
    def test_no_clamp_when_within_limit(self) -> None:
        # smoothing=0.5/s, dt=2s → max_delta=1.0; a move of 0.3 is unclamped.
        segs = [
            {"start": 0.0, "end": 2.0, "x": 0.5},
            {"start": 2.0, "end": 4.0, "x": 0.8},
        ]
        result = rf.speaker_track_windows(segs, smoothing=0.5)
        assert result[1]["x"] == pytest.approx(0.8)

    def test_clamp_large_rightward_jump(self) -> None:
        # smoothing=0.1/s, dt=1s → max_delta=0.1; a jump of 0.5 is clamped.
        segs = [
            {"start": 0.0, "end": 1.0, "x": 0.2},
            {"start": 1.0, "end": 2.0, "x": 0.7},
        ]
        result = rf.speaker_track_windows(segs, smoothing=0.1)
        # max_delta = 0.1 * dt(1s=midpoint diff of 1.0s) = 0.1
        expected_x = pytest.approx(0.2 + 0.1, abs=1e-9)
        assert result[1]["x"] == expected_x

    def test_clamp_large_leftward_jump(self) -> None:
        segs = [
            {"start": 0.0, "end": 1.0, "x": 0.8},
            {"start": 1.0, "end": 2.0, "x": 0.2},
        ]
        result = rf.speaker_track_windows(segs, smoothing=0.1)
        expected_x = pytest.approx(0.8 - 0.1, abs=1e-9)
        assert result[1]["x"] == expected_x

    def test_x_clamped_to_0(self) -> None:
        # Large overshoot to left should not go below 0.
        segs = [{"start": 0.0, "end": 1.0, "x": -0.5}]
        result = rf.speaker_track_windows(segs, smoothing=1.0)
        assert result[0]["x"] >= 0.0

    def test_x_clamped_to_1(self) -> None:
        segs = [{"start": 0.0, "end": 1.0, "x": 1.5}]
        result = rf.speaker_track_windows(segs, smoothing=1.0)
        assert result[0]["x"] <= 1.0

    def test_duplicate_timestamp_keeps_position(self) -> None:
        # Two segments at the same midpoint (dt=0) → position must not change.
        segs = [
            {"start": 0.0, "end": 0.0, "x": 0.3},
            {"start": 0.0, "end": 0.0, "x": 0.9},
        ]
        result = rf.speaker_track_windows(segs, smoothing=1.0)
        assert result[1]["x"] == pytest.approx(result[0]["x"])

    def test_smoothing_accumulates_across_segments(self) -> None:
        # Each step can advance at most smoothing*dt=0.1; three steps from 0.2.
        segs = [
            {"start": 0.0, "end": 1.0, "x": 0.2},
            {"start": 1.0, "end": 2.0, "x": 0.9},
            {"start": 2.0, "end": 3.0, "x": 0.9},
            {"start": 3.0, "end": 4.0, "x": 0.9},
        ]
        result = rf.speaker_track_windows(segs, smoothing=0.1)
        # Each step dt=1s, max_delta=0.1 per step.
        assert result[1]["x"] == pytest.approx(0.3, abs=1e-9)
        assert result[2]["x"] == pytest.approx(0.4, abs=1e-9)
        assert result[3]["x"] == pytest.approx(0.5, abs=1e-9)


# ---------------------------------------------------------------------------
# build_reframe_cmd — static (empty windows)
# ---------------------------------------------------------------------------


class TestBuildReframeCmdStatic:
    def test_returns_list(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", [])
        assert isinstance(cmd, list)

    def test_all_elements_are_strings(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", [])
        assert all(isinstance(s, str) for s in cmd)

    def test_starts_with_ffmpeg(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", [])
        assert cmd[0].endswith("ffmpeg") or cmd[0] == "ffmpeg"

    def test_input_flag_present(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", [])
        assert "-i" in cmd

    def test_input_path_in_cmd(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", [])
        assert "in.mp4" in cmd

    def test_output_path_in_cmd(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", [])
        assert "out.mp4" in cmd

    def test_vf_flag_present(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", [])
        assert "-vf" in cmd

    def test_static_vf_contains_crop(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", [])
        vf = cmd[cmd.index("-vf") + 1]
        assert "crop=" in vf

    def test_static_vf_contains_scale(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", [])
        vf = cmd[cmd.index("-vf") + 1]
        assert "scale=" in vf

    def test_overwrite_flag_present(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", [])
        assert "-y" in cmd

    def test_codec_libx264(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", [])
        assert "libx264" in cmd

    def test_audio_copy(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", [])
        assert "copy" in cmd

    def test_9x16_scale_1080x1920(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", [], ratio="9:16")
        vf = cmd[cmd.index("-vf") + 1]
        assert "scale=1080:1920" in vf

    def test_1x1_scale_1080x1080(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", [], ratio="1:1")
        vf = cmd[cmd.index("-vf") + 1]
        assert "scale=1080:1080" in vf

    def test_4x5_scale_1080x1350(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", [], ratio="4:5")
        vf = cmd[cmd.index("-vf") + 1]
        assert "scale=1080:1350" in vf

    def test_invalid_ratio_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported ratio"):
            rf.build_reframe_cmd("in.mp4", "out.mp4", [], ratio="16:9")


# ---------------------------------------------------------------------------
# build_reframe_cmd — animated (non-empty windows)
# ---------------------------------------------------------------------------


class TestBuildReframeCmdAnimated:
    def _windows(self) -> list[dict]:
        return [
            {"t": 1.0, "x": 0.3},
            {"t": 3.0, "x": 0.7},
        ]

    def test_returns_list(self) -> None:
        assert isinstance(rf.build_reframe_cmd("in.mp4", "out.mp4", self._windows()), list)

    def test_vf_contains_crop(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", self._windows())
        vf = cmd[cmd.index("-vf") + 1]
        assert "crop=" in vf

    def test_vf_contains_if_expression(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", self._windows())
        vf = cmd[cmd.index("-vf") + 1]
        assert "if(" in vf

    def test_vf_contains_lte(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", self._windows())
        vf = cmd[cmd.index("-vf") + 1]
        assert "lte(t," in vf

    def test_vf_contains_scale(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", self._windows())
        vf = cmd[cmd.index("-vf") + 1]
        assert "scale=" in vf

    def test_single_window_no_if(self) -> None:
        # A single keyframe produces a plain integer x, no if() needed.
        windows = [{"t": 1.0, "x": 0.5}]
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", windows)
        vf = cmd[cmd.index("-vf") + 1]
        # "if(" only needed for >1 keyframe.
        assert "if(" not in vf

    def test_exact_flag_present(self) -> None:
        cmd = rf.build_reframe_cmd("in.mp4", "out.mp4", self._windows())
        vf = cmd[cmd.index("-vf") + 1]
        assert "exact=1" in vf
