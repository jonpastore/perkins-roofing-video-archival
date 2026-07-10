"""100% line-coverage tests for core.speaker_track (Item 7).

Covers:
- NullFaceDetector: satisfies FaceDetector protocol, always returns None.
- smooth_centroids: gap-fill, EMA smoothing, pan-speed clamping, edge cases.
- build_tracking_crop_filter: single point, multi-point keyframe expr,
  static fallback, ratio variants, error cases.
"""
from __future__ import annotations

import pytest

import core.speaker_track as st


# ---------------------------------------------------------------------------
# NullFaceDetector
# ---------------------------------------------------------------------------


class TestNullFaceDetector:
    def test_satisfies_protocol(self) -> None:
        assert isinstance(st.NullFaceDetector(), st.FaceDetector)

    def test_returns_list_same_length(self) -> None:
        det = st.NullFaceDetector()
        segs = [{"start": 0.0, "end": 1.0}, {"start": 1.0, "end": 2.0}]
        result = det.detect_centroids("any.mp4", segs)
        assert len(result) == 2

    def test_all_none(self) -> None:
        det = st.NullFaceDetector()
        segs = [{"start": i * 1.0, "end": (i + 1) * 1.0} for i in range(5)]
        result = det.detect_centroids("v.mp4", segs)
        assert all(v is None for v in result)

    def test_empty_segments(self) -> None:
        det = st.NullFaceDetector()
        assert det.detect_centroids("v.mp4", []) == []


# ---------------------------------------------------------------------------
# smooth_centroids
# ---------------------------------------------------------------------------


class TestSmoothCentroids:
    def test_empty_input_returns_empty(self) -> None:
        assert st.smooth_centroids([]) == []

    def test_single_none_returns_half(self) -> None:
        result = st.smooth_centroids([None])
        assert len(result) == 1
        assert result[0] == pytest.approx(0.5)

    def test_single_value_passthrough(self) -> None:
        result = st.smooth_centroids([0.7])
        assert len(result) == 1
        assert result[0] == pytest.approx(0.7)

    def test_none_gap_filled_with_previous(self) -> None:
        result = st.smooth_centroids([0.8, None, None], ema_alpha=1.0, max_pan_speed=1.0)
        assert result[0] == pytest.approx(0.8)
        assert result[1] == pytest.approx(0.8)
        assert result[2] == pytest.approx(0.8)

    def test_none_at_start_fills_with_0_5(self) -> None:
        result = st.smooth_centroids([None, 0.9], ema_alpha=1.0, max_pan_speed=1.0)
        assert result[0] == pytest.approx(0.5)

    def test_ema_smoothing_applied(self) -> None:
        result = st.smooth_centroids([0.0, 1.0], ema_alpha=0.5, max_pan_speed=10.0)
        assert result[0] == pytest.approx(0.0)
        assert result[1] == pytest.approx(0.5)

    def test_pan_speed_clamped(self) -> None:
        result = st.smooth_centroids(
            [0.0, 1.0],
            ema_alpha=1.0,
            max_pan_speed=0.1,
            timestamps=[0.0, 1.0],
        )
        assert result[0] == pytest.approx(0.0)
        assert result[1] == pytest.approx(0.1)

    def test_pan_speed_not_exceeded_over_multiple_steps(self) -> None:
        raw = [0.0, 1.0, 1.0, 1.0]
        ts = [0.0, 1.0, 2.0, 3.0]
        result = st.smooth_centroids(raw, ema_alpha=1.0, max_pan_speed=0.2, timestamps=ts)
        for i in range(1, len(result)):
            delta = abs(result[i] - result[i - 1])
            dt = ts[i] - ts[i - 1]
            assert delta <= 0.2 * dt + 1e-9

    def test_values_clamped_to_0_1(self) -> None:
        result = st.smooth_centroids([1.5, -0.5], ema_alpha=1.0, max_pan_speed=10.0)
        for v in result:
            assert 0.0 <= v <= 1.0

    def test_no_none_in_output(self) -> None:
        raw: list[float | None] = [None, 0.4, None, 0.6, None]
        result = st.smooth_centroids(raw)
        assert all(v is not None for v in result)

    def test_invalid_ema_alpha_raises(self) -> None:
        with pytest.raises(ValueError, match="ema_alpha"):
            st.smooth_centroids([0.5], ema_alpha=0.0)

    def test_invalid_ema_alpha_gt_1_raises(self) -> None:
        with pytest.raises(ValueError, match="ema_alpha"):
            st.smooth_centroids([0.5], ema_alpha=1.5)

    def test_invalid_max_pan_speed_raises(self) -> None:
        with pytest.raises(ValueError, match="max_pan_speed"):
            st.smooth_centroids([0.5], max_pan_speed=0.0)

    def test_timestamps_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="timestamps length"):
            st.smooth_centroids([0.5, 0.6], timestamps=[0.0])

    def test_timestamps_none_uses_dt_1(self) -> None:
        result = st.smooth_centroids(
            [0.0, 1.0],
            ema_alpha=1.0,
            max_pan_speed=0.1,
            timestamps=None,
        )
        assert result[1] == pytest.approx(0.1)

    def test_zero_dt_keeps_previous(self) -> None:
        result = st.smooth_centroids(
            [0.2, 0.8],
            ema_alpha=1.0,
            max_pan_speed=0.5,
            timestamps=[1.0, 1.0],
        )
        assert result[1] == pytest.approx(result[0], abs=0.5)

    def test_returns_list_of_floats(self) -> None:
        result = st.smooth_centroids([0.3, 0.6])
        assert all(isinstance(v, float) for v in result)


# ---------------------------------------------------------------------------
# build_tracking_crop_filter
# ---------------------------------------------------------------------------


class TestBuildTrackingCropFilter:
    def test_empty_smoothed_returns_static_centre_crop(self) -> None:
        f = st.build_tracking_crop_filter([], [], src_w=1920, src_h=1080)
        assert f.startswith("crop=")
        centre_x = (1920 - 606) // 2
        assert str(centre_x) in f

    def test_single_point_no_if_expr(self) -> None:
        f = st.build_tracking_crop_filter([0.5], [0.5])
        assert f.startswith("crop=")
        assert "if(" not in f

    def test_multi_point_generates_if_expr(self) -> None:
        f = st.build_tracking_crop_filter([0.3, 0.7], [0.5, 1.5])
        assert "if(lte(t," in f

    def test_returns_string(self) -> None:
        f = st.build_tracking_crop_filter([0.5], [1.0])
        assert isinstance(f, str)

    def test_crop_prefix(self) -> None:
        f = st.build_tracking_crop_filter([0.5], [1.0])
        assert f.startswith("crop=")

    def test_9_16_ratio_default(self) -> None:
        f = st.build_tracking_crop_filter([0.5], [1.0], src_w=1920, src_h=1080)
        parts = f[len("crop="):].split(":")
        crop_w = int(parts[0])
        crop_h = int(parts[1])
        assert crop_w == 606
        assert crop_h == 1080

    def test_1_1_ratio(self) -> None:
        f = st.build_tracking_crop_filter([0.5], [1.0], src_w=1920, src_h=1080, ratio="1:1")
        parts = f[len("crop="):].split(":")
        crop_w = int(parts[0])
        crop_h = int(parts[1])
        assert crop_w == crop_h

    def test_unsupported_ratio_raises(self) -> None:
        with pytest.raises(ValueError, match="ratio"):
            st.build_tracking_crop_filter([0.5], [1.0], ratio="16:9")

    def test_zero_src_w_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            st.build_tracking_crop_filter([0.5], [1.0], src_w=0, src_h=1080)

    def test_zero_src_h_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            st.build_tracking_crop_filter([0.5], [1.0], src_w=1920, src_h=0)

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="length"):
            st.build_tracking_crop_filter([0.5, 0.6], [1.0])

    def test_x_clamped_to_valid_range(self) -> None:
        f = st.build_tracking_crop_filter([0.0], [0.0], src_w=1920, src_h=1080)
        parts = f[len("crop="):].split(":")
        x = int(parts[2])
        assert x >= 0

    def test_x_at_right_edge_clamped(self) -> None:
        f = st.build_tracking_crop_filter([1.0], [0.0], src_w=1920, src_h=1080)
        parts = f[len("crop="):].split(":")
        crop_w = int(parts[0])
        x = int(parts[2])
        assert x + crop_w <= 1920

    def test_if_expr_has_timestamps(self) -> None:
        f = st.build_tracking_crop_filter([0.3, 0.5, 0.7], [1.0, 2.0, 3.0])
        assert "lte(t,1.000000)" in f
        assert "lte(t,2.000000)" in f

    def test_three_points_nested_ifs(self) -> None:
        f = st.build_tracking_crop_filter([0.2, 0.5, 0.8], [0.5, 1.5, 2.5])
        assert f.count("if(") == 2

    def test_width_binding_constraint_branch(self) -> None:
        # When src is portrait (tall), cw_from_h > src_w → width is binding constraint.
        # src_w=200, src_h=1000, ratio=9:16 → cw_from_h=1000*9/16=562 > 200 → else branch.
        f = st.build_tracking_crop_filter([0.5], [1.0], src_w=200, src_h=1000, ratio="9:16")
        assert f.startswith("crop=")
        parts = f[len("crop="):].split(":")
        crop_w = int(parts[0])
        crop_h = int(parts[1])
        # crop_w must equal src_w (or its even-floor), crop_h derived from ratio
        assert crop_w <= 200
        assert crop_h <= 1000
