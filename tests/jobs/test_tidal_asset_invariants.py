"""Invariants the SHIPPED tidal asset must hold, because a breach is a false VOID.

`tagged` and `measured` both move a warranty verdict in checker.js. `inferred` only raises a
caveat. So the dangerous failure is verdict-moving geometry appearing where the water is not
actually salt — which has now happened twice:

  1. The first build labelled any coastline-touching way `tagged` for its whole length, carrying
     "confirmed salt water" 20 miles inland and telling Golden Gate Estates its warranty was void.
  2. 2026-07-31: exempting `tagged` from the REACH_MI clip emitted Dunns Creek — which drains
     FRESHWATER Crescent Lake — as verdict-moving geometry 25 mi inland. OSM `tidal=yes` describes
     water LEVEL, not salinity, and the St Johns' tidal signal runs ~160 mi inland.

Both were caught by review rather than by a test, so these pin the built artifact directly.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from scripts.build_tidal_layer import REACH_MI

ASSETS = Path(__file__).resolve().parent.parent.parent / "wp-plugin/perkins-metal-warranty/assets"
# The coastal band is a rasterised dilation on ~0.01-degree cells, so "within REACH_MI" is coarse:
# the furthest legitimate tagged reach measured 4.9 mi against a 3.0 mi clip. This tolerance is set
# to catch a RUNAWAY (Dunns Creek was 25 mi), not to police 5 miles against 6 — a tight bound here
# would flake on raster rounding and get muted, which is worse than a loose bound that holds.
RASTER_SLOP_MI = 5.0


def _coast_points() -> list[tuple[float, float]]:
    d = json.loads((ASSETS / "coastline.geojson").read_text())
    geoms = d["geometries"] if d.get("type") == "GeometryCollection" else [
        f["geometry"] for f in d["features"]]
    pts: list[tuple[float, float]] = []
    for g in geoms:
        parts = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        for part in parts:
            pts.extend((float(x), float(y)) for x, y in part)
    return pts


@pytest.fixture(scope="module")
def asset():
    return json.loads((ASSETS / "tidal.geojson").read_text())


@pytest.fixture(scope="module")
def coast_grid():
    grid: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for x, y in _coast_points():
        grid.setdefault((int(x / 0.1), int(y / 0.1)), []).append((x, y))
    return grid


def _inland_mi(x: float, y: float, grid) -> float:
    kx = 111320.0 * math.cos(math.radians(y))
    best = float("inf")
    cx, cy = int(x / 0.1), int(y / 0.1)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for px, py in grid.get((cx + dx, cy + dy), ()):
                d = math.hypot((px - x) * kx, (py - y) * 110540.0)
                if d < best:
                    best = d
    return best / 1609.34


def test_no_tagged_reach_runs_far_inland(asset, coast_grid):
    """`tagged` must stay clipped. Only a GAUGE can tell tidal-level from salt.

    This is the Dunns Creek pin. An OSM tidal=yes tag 25 miles inland is a statement about the
    tide reaching there, not about the water being salty, and it must never void a warranty.
    """
    limit = REACH_MI + RASTER_SLOP_MI
    offenders = []
    for g in asset["geometries"]:
        if g.get("confidence") != "tagged":
            continue
        x, y = g["coordinates"][0]
        mi = _inland_mi(x, y, coast_grid)
        if mi > limit and mi != float("inf"):
            offenders.append((round(mi, 1), x, y))
    assert not offenders, (
        f"tagged (verdict-moving) geometry more than {limit} mi from the coast: "
        f"{sorted(offenders, reverse=True)[:5]}"
    )


def test_every_measured_reach_cites_a_station(asset):
    """`measured` is the only class exempt from the clip, so it must carry its evidence."""
    naked = [g for g in asset["geometries"]
             if g.get("confidence") == "measured"
             and not (g.get("measurement") or {}).get("station")]
    assert not naked, f"{len(naked)} measured geometries carry no station citation"


def test_measured_reaches_carry_a_dateable_reading(asset):
    """A citation a homeowner reads as current must be dateable — see _reading_expired."""
    undated = [(g.get("measurement") or {}).get("station")
               for g in asset["geometries"]
               if g.get("confidence") == "measured"
               and not (g.get("measurement") or {}).get("measured_at")]
    assert not undated, f"measured geometries with no timestamp: {set(undated)}"


def test_no_closed_rings_are_emitted_as_verdict_moving_geometry(asset):
    """A lake outline is not a channel. 78 tagged ways were water POLYGONS; flooding them through
    the channel BFS is meaningless and put Crescent Lake's ring into the verdict-moving set."""
    rings = []
    for g in asset["geometries"]:
        if g.get("confidence") not in ("tagged", "measured"):
            continue
        c = g["coordinates"]
        if len(c) > 3 and c[0] == c[-1]:
            rings.append(c[0])
    assert not rings, f"{len(rings)} closed rings emitted as verdict-moving: {rings[:3]}"
