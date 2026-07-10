"""tests/core/test_squares.py — 100% branch coverage of core/squares.py.

All tests are pure (no I/O, no DB, no HTTP).
"""
from datetime import date

import pytest

from core.squares import (
    _azimuth_to_compass,
    _area_to_squares,
    segments_to_squares,
    staleness_warning,
    parse_building_insights,
)


# ---------------------------------------------------------------------------
# _azimuth_to_compass
# ---------------------------------------------------------------------------

class TestAzimuthToCompass:
    def test_north(self):
        assert _azimuth_to_compass(0.0) == "N"

    def test_northeast(self):
        assert _azimuth_to_compass(45.0) == "NE"

    def test_east(self):
        assert _azimuth_to_compass(90.0) == "E"

    def test_southeast(self):
        assert _azimuth_to_compass(135.0) == "SE"

    def test_south(self):
        assert _azimuth_to_compass(180.0) == "S"

    def test_southwest(self):
        assert _azimuth_to_compass(225.0) == "SW"

    def test_west(self):
        assert _azimuth_to_compass(270.0) == "W"

    def test_northwest(self):
        assert _azimuth_to_compass(315.0) == "NW"

    def test_near_north_wraps(self):
        # 350° rounds to N (index 0 mod 8 = 0)
        assert _azimuth_to_compass(350.0) == "N"

    def test_midpoint_22_5_rounds_to_n(self):
        # round(22.5 / 45) = round(0.5) = 0 (banker's rounding) → "N"
        assert _azimuth_to_compass(22.5) == "N"


# ---------------------------------------------------------------------------
# _area_to_squares
# ---------------------------------------------------------------------------

class TestAreaToSquares:
    def test_zero(self):
        assert _area_to_squares(0.0) == 0.0

    def test_known_value(self):
        # 100 m2 × 10.7639 / 100 = 10.7639 → rounds to 10.8
        assert _area_to_squares(100.0) == 10.8

    def test_small_area(self):
        result = _area_to_squares(10.0)
        assert result == round(10.0 * 10.7639 / 100, 1)


# ---------------------------------------------------------------------------
# segments_to_squares
# ---------------------------------------------------------------------------

def _seg(area_m2=10.0, pitch=20.0, azimuth=180.0):
    return {
        "stats": {"areaMeters2": area_m2},
        "pitchDegrees": pitch,
        "azimuthDegrees": azimuth,
    }


class TestSegmentsToSquares:
    def test_empty_segments(self):
        result = segments_to_squares([])
        assert result["total_squares"] == 0.0
        assert result["per_segment"] == []
        assert result["predominant_pitch"] is None

    def test_single_segment(self):
        segs = [_seg(area_m2=100.0, pitch=18.0, azimuth=90.0)]
        result = segments_to_squares(segs)
        assert result["total_squares"] == 10.8
        assert len(result["per_segment"]) == 1
        seg = result["per_segment"][0]
        assert seg["pitch_degrees"] == 18.0
        assert seg["azimuth_degrees"] == 90.0
        assert seg["azimuth_compass"] == "E"
        assert seg["area_m2"] == 100.0
        assert seg["area_sqft"] == round(100.0 * 10.7639, 1)
        assert seg["squares"] == 10.8
        assert result["predominant_pitch"] == 18.0

    def test_multiple_segments_sums(self):
        segs = [_seg(area_m2=100.0, pitch=18.0), _seg(area_m2=50.0, pitch=30.0)]
        result = segments_to_squares(segs)
        expected_total = round((100.0 + 50.0) * 10.7639 / 100, 1)
        assert result["total_squares"] == expected_total
        assert len(result["per_segment"]) == 2

    def test_predominant_pitch_area_weighted(self):
        # Two segments: 100 m2 at 20°, 100 m2 at 40° → mean 30°
        segs = [_seg(area_m2=100.0, pitch=20.0), _seg(area_m2=100.0, pitch=40.0)]
        result = segments_to_squares(segs)
        assert result["predominant_pitch"] == 30.0

    def test_missing_stats_key_defaults_to_zero(self):
        seg = {"pitchDegrees": 15.0, "azimuthDegrees": 0.0}
        result = segments_to_squares([seg])
        assert result["total_squares"] == 0.0
        assert result["per_segment"][0]["area_m2"] == 0.0

    def test_null_pitch_defaults_to_zero(self):
        seg = {"stats": {"areaMeters2": 50.0}, "pitchDegrees": None, "azimuthDegrees": 45.0}
        result = segments_to_squares([seg])
        assert result["per_segment"][0]["pitch_degrees"] == 0.0

    def test_null_azimuth_defaults_to_zero(self):
        seg = {"stats": {"areaMeters2": 50.0}, "pitchDegrees": 20.0, "azimuthDegrees": None}
        result = segments_to_squares([seg])
        assert result["per_segment"][0]["azimuth_degrees"] == 0.0
        assert result["per_segment"][0]["azimuth_compass"] == "N"

    def test_total_area_zero_gives_none_pitch(self):
        seg = {"stats": {"areaMeters2": 0.0}, "pitchDegrees": 20.0, "azimuthDegrees": 90.0}
        result = segments_to_squares([seg])
        assert result["predominant_pitch"] is None

    def test_miami_example_7_segments(self):
        # Jon's real test: 7 segments summing ~217.9 m² → ~23.4 squares
        segs = [_seg(area_m2=v) for v in [40.0, 35.0, 30.0, 28.0, 32.0, 27.0, 25.9]]
        result = segments_to_squares(segs)
        total_m2 = 40 + 35 + 30 + 28 + 32 + 27 + 25.9
        expected = round(total_m2 * 10.7639 / 100, 1)
        assert result["total_squares"] == expected
        assert len(result["per_segment"]) == 7


# ---------------------------------------------------------------------------
# staleness_warning
# ---------------------------------------------------------------------------

class TestStalenessWarning:
    def test_high_quality_fresh_no_warning(self):
        today = date(2026, 7, 10)
        assert staleness_warning("2024-07-10", "HIGH", today) is False

    def test_quality_not_high_warns(self):
        today = date(2026, 7, 10)
        assert staleness_warning("2025-01-01", "MEDIUM", today) is True

    def test_quality_low_warns(self):
        today = date(2026, 7, 10)
        assert staleness_warning("2025-01-01", "LOW", today) is True

    def test_quality_none_warns(self):
        today = date(2026, 7, 10)
        assert staleness_warning("2025-01-01", None, today) is True

    def test_older_than_3_years_warns(self):
        today = date(2026, 7, 10)
        assert staleness_warning("2023-07-09", "HIGH", today) is True

    def test_exactly_3_years_is_borderline(self):
        # 2023-07-10 to 2026-07-10 = 1096 days / 365.25 = 3.0014... > 3 → warns
        today = date(2026, 7, 10)
        assert staleness_warning("2023-07-10", "HIGH", today) is True

    def test_just_under_3_years_no_warn(self):
        # 2023-07-11 to 2026-07-10 = 1095 days / 365.25 = 2.997... < 3 → no warn
        today = date(2026, 7, 10)
        assert staleness_warning("2023-07-11", "HIGH", today) is False

    def test_none_date_warns(self):
        today = date(2026, 7, 10)
        assert staleness_warning(None, "HIGH", today) is True

    def test_empty_string_date_warns(self):
        today = date(2026, 7, 10)
        assert staleness_warning("", "HIGH", today) is True

    def test_malformed_date_warns(self):
        today = date(2026, 7, 10)
        assert staleness_warning("not-a-date", "HIGH", today) is True

    def test_partial_date_warns(self):
        today = date(2026, 7, 10)
        assert staleness_warning("2025-01", "HIGH", today) is True


# ---------------------------------------------------------------------------
# parse_building_insights
# ---------------------------------------------------------------------------

_SAMPLE_RAW = {
    "name": "buildings/ChIJabc123",
    "center": {"latitude": 25.7617, "longitude": -80.1918},
    "solarPotential": {
        "imageryDate": {"year": 2024, "month": 3, "day": 15},
        "imageryQuality": "HIGH",
        "wholeRoofStats": {"groundAreaMeters2": 180.5},
        "roofSegmentStats": [
            {
                "stats": {"areaMeters2": 90.0},
                "pitchDegrees": 18.0,
                "azimuthDegrees": 180.0,
            }
        ],
    },
}


class TestParseBuildingInsights:
    def test_full_response(self):
        result = parse_building_insights(_SAMPLE_RAW)
        assert result["imagery_date"] == "2024-03-15"
        assert result["imagery_quality"] == "HIGH"
        assert len(result["roof_segments"]) == 1
        assert result["center_lat"] == pytest.approx(25.7617)
        assert result["center_lng"] == pytest.approx(-80.1918)
        assert result["ground_area_m2"] == pytest.approx(180.5)
        assert result["source_building"] == "buildings/ChIJabc123"

    def test_missing_solar_potential(self):
        result = parse_building_insights({})
        assert result["imagery_date"] is None
        assert result["imagery_quality"] is None
        assert result["roof_segments"] == []
        assert result["center_lat"] is None
        assert result["center_lng"] is None
        assert result["ground_area_m2"] is None
        assert result["source_building"] is None

    def test_missing_imagery_date_fields(self):
        raw = {
            "solarPotential": {
                "imageryDate": {},
                "imageryQuality": "MEDIUM",
                "roofSegmentStats": [],
            }
        }
        result = parse_building_insights(raw)
        assert result["imagery_date"] is None

    def test_partial_imagery_date_year_only(self):
        raw = {
            "solarPotential": {
                "imageryDate": {"year": 2024},
                "imageryQuality": "HIGH",
                "roofSegmentStats": [],
            }
        }
        result = parse_building_insights(raw)
        assert result["imagery_date"] is None

    def test_missing_name_gives_none(self):
        raw = {**_SAMPLE_RAW}
        raw = {k: v for k, v in raw.items() if k != "name"}
        result = parse_building_insights(raw)
        assert result["source_building"] is None

    def test_missing_center_gives_none(self):
        raw = {
            "solarPotential": {
                "imageryDate": {"year": 2024, "month": 1, "day": 1},
                "imageryQuality": "HIGH",
                "roofSegmentStats": [],
            }
        }
        result = parse_building_insights(raw)
        assert result["center_lat"] is None
        assert result["center_lng"] is None

    def test_missing_whole_roof_stats_gives_none(self):
        raw = {
            "solarPotential": {
                "imageryDate": {"year": 2024, "month": 1, "day": 1},
                "imageryQuality": "HIGH",
                "roofSegmentStats": [],
            }
        }
        result = parse_building_insights(raw)
        assert result["ground_area_m2"] is None

    def test_empty_segments_list(self):
        raw = {**_SAMPLE_RAW, "solarPotential": {**_SAMPLE_RAW["solarPotential"], "roofSegmentStats": []}}
        result = parse_building_insights(raw)
        assert result["roof_segments"] == []

    def test_null_solar_potential_key(self):
        result = parse_building_insights({"solarPotential": None})
        assert result["imagery_date"] is None
        assert result["imagery_quality"] is None
        assert result["roof_segments"] == []

    def test_center_lat_lng_as_floats(self):
        result = parse_building_insights(_SAMPLE_RAW)
        assert isinstance(result["center_lat"], float)
        assert isinstance(result["center_lng"], float)
