"""core/squares.py — pure roof-measurement helpers for the Solar API integration.

All functions are stateless and side-effect-free so they hit 100% coverage.
No I/O, no HTTP, no DB.  The route layer calls the Solar API and passes the
raw JSON here for normalisation.

Conversion: 1 m² = 10.7639 ft².  1 square = 100 ft².
Squares = sum(segment.areaMeters2) × 10.7639 / 100.
"""
from __future__ import annotations

from datetime import date
from typing import Any

_M2_TO_SQFT = 10.7639
_SQFT_PER_SQUARE = 100.0
_STALENESS_YEARS = 3


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def _azimuth_to_compass(degrees: float) -> str:
    """Convert a bearing in degrees [0, 360) to an 8-point compass label."""
    dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = round(degrees / 45.0) % 8
    return dirs[idx]


def _area_to_squares(area_m2: float) -> float:
    """Convert square metres (true 3-D roof area) to roofing squares, rounded to 1 dp."""
    return round(area_m2 * _M2_TO_SQFT / _SQFT_PER_SQUARE, 1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def segments_to_squares(segments: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate Solar API roof-segment data into measurement summary.

    Each segment dict must contain:
        - stats.areaMeters2   (float)  — true 3-D roof surface area
        - pitchDegrees        (float)  — pitch angle in degrees
        - azimuthDegrees      (float)  — compass bearing of the downslope

    Returns a dict with:
        total_squares         (float)  — sum of all segment squares, 1 dp
        per_segment           (list)   — per-segment breakdown
        predominant_pitch     (float | None) — area-weighted mean pitch, 1 dp
    """
    if not segments:
        return {
            "total_squares": 0.0,
            "per_segment": [],
            "predominant_pitch": None,
        }

    per_segment = []
    total_area_m2 = 0.0
    weighted_pitch_sum = 0.0

    for seg in segments:
        stats = seg.get("stats") or {}
        area_m2 = float(stats.get("areaMeters2") or 0.0)
        pitch = float(seg.get("pitchDegrees") or 0.0)
        azimuth = float(seg.get("azimuthDegrees") or 0.0)
        area_sqft = round(area_m2 * _M2_TO_SQFT, 1)
        squares = _area_to_squares(area_m2)

        per_segment.append({
            "pitch_degrees": round(pitch, 1),
            "azimuth_degrees": round(azimuth, 1),
            "azimuth_compass": _azimuth_to_compass(azimuth),
            "area_m2": round(area_m2, 2),
            "area_sqft": area_sqft,
            "squares": squares,
        })

        total_area_m2 += area_m2
        weighted_pitch_sum += pitch * area_m2

    total_squares = _area_to_squares(total_area_m2)

    if total_area_m2 > 0:
        predominant_pitch = round(weighted_pitch_sum / total_area_m2, 1)
    else:
        predominant_pitch = None

    return {
        "total_squares": total_squares,
        "per_segment": per_segment,
        "predominant_pitch": predominant_pitch,
    }


def staleness_warning(imagery_date: str | None, quality: str | None, now: date) -> bool:
    """Return True when the Solar imagery warrants a field-validation recommendation.

    Rules (Jon 2026-07-10):
        - quality is not 'HIGH' → warn
        - imagery older than 3 years from `now` → warn
        - imagery_date is None / unparseable → warn (conservative)
    """
    if quality != "HIGH":
        return True

    if not imagery_date:
        return True

    try:
        parts = imagery_date.split("-")
        img = date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return True

    age_years = (now - img).days / 365.25
    return age_years > _STALENESS_YEARS


def parse_building_insights(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Google Solar buildingInsights response into a stable internal dict.

    Defensive: missing keys produce None rather than KeyError.  The caller
    (route layer) decides how to surface missing data.

    Returns:
        imagery_date      str | None   — YYYY-MM-DD
        imagery_quality   str | None   — 'HIGH' | 'MEDIUM' | 'LOW' | None
        roof_segments     list         — raw solarPotential.roofSegmentStats list (may be [])
        center_lat        float | None
        center_lng        float | None
        ground_area_m2    float | None — groundAreaMeters2 of the whole roof
        source_building   str | None   — name field (Google's building identifier)
    """
    solar = raw.get("solarPotential") or {}
    imagery_date_raw = solar.get("imageryDate") or {}

    # imageryDate is {"year": int, "month": int, "day": int}
    year = imagery_date_raw.get("year")
    month = imagery_date_raw.get("month")
    day = imagery_date_raw.get("day")
    if year and month and day:
        imagery_date = f"{year:04d}-{month:02d}-{day:02d}"
    else:
        imagery_date = None

    imagery_quality = solar.get("imageryQuality") or None

    segments = solar.get("roofSegmentStats") or []

    center = raw.get("center") or {}
    center_lat = center.get("latitude")
    center_lng = center.get("longitude")

    # groundAreaMeters2 may be in the top-level solar potential or per the whole roof
    ground_area_m2 = solar.get("wholeRoofStats", {}).get("groundAreaMeters2") or None

    source_building = raw.get("name") or None

    return {
        "imagery_date": imagery_date,
        "imagery_quality": imagery_quality,
        "roof_segments": segments,
        "center_lat": float(center_lat) if center_lat is not None else None,
        "center_lng": float(center_lng) if center_lng is not None else None,
        "ground_area_m2": float(ground_area_m2) if ground_area_m2 is not None else None,
        "source_building": source_building,
    }
