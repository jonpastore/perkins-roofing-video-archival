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
import re
from pathlib import Path

import pytest

from scripts.build_tidal_layer import REACH_MI, VERDICT_MOVING

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
    """Miles from the mapped coastline.

    ⚠️ This WIDENS its search until it finds coastline. The first version looked only at the 3x3
    block of 0.1-degree cells and returned `inf` otherwise, and both callers skipped `inf` — so the
    further inland a runaway reach ran, the LESS likely the pin was to see it. A Dunns-Creek-class
    breach at 25 mi returned `inf` and passed silently, which is the exact failure these tests
    exist to catch. Caught 2026-08-06 by checking the pins fail on a doctored asset.
    """
    kx = 111320.0 * math.cos(math.radians(y))
    cx, cy = int(x / 0.1), int(y / 0.1)
    for span in (1, 2, 4, 8, 16, 32):
        best = float("inf")
        for dx in range(-span, span + 1):
            for dy in range(-span, span + 1):
                for px, py in grid.get((cx + dx, cy + dy), ()):
                    d = math.hypot((px - x) * kx, (py - y) * 110540.0)
                    if d < best:
                        best = d
        if best < float("inf"):
            return best / 1609.34
    return float("inf")   # no coastline anywhere within ~350 km — not Florida


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
        # `inf` means no coastline found even at the widest span — that is MORE inland, not less,
        # so it must fail rather than be skipped.
        if mi > limit:
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
        if g.get("confidence") not in VERDICT_MOVING:
            continue
        c = g["coordinates"]
        if len(c) > 3 and c[0] == c[-1]:
            rings.append(c[0])
    assert not rings, f"{len(rings)} closed rings emitted as verdict-moving: {rings[:3]}"


# --- FDEP Class III-Marine (`mapped`), added 2026-08-06 ------------------------------------------
# The class exists because OSM tags almost no South Florida tidal river and USGS gauges sit miles
# apart, so the water customers live on landed in `inferred` and only raised a caveat. It is also
# the largest verdict-moving class by far, so it needs the same pins the others earned.

#: Generous — the farthest legitimate mapped reach measured 7.8 mi (Indian River above Max Brewer
#: Causeway, a Class II estuary). This catches a RUNAWAY, not 8 miles against 9.
MAPPED_MAX_INLAND_MI = 15.0
CHECKER_JS = ASSETS / "checker.js"


def test_every_mapped_reach_names_a_marine_water_body(asset):
    """`mapped` is exempt from the clip, so like `measured` it must carry its evidence.

    Class `2` is shellfish-harvesting marine, `3M` is Class III-Marine. Anything else here means
    the build promoted a reach on a class that does not say the water is salty.
    """
    bad = [(g.get("wbid") or {}).get("water_class")
           for g in asset["geometries"]
           if g.get("confidence") == "mapped"
           and (g.get("wbid") or {}).get("water_class") not in ("2", "3M")]
    assert not bad, f"{len(bad)} mapped geometries carry no marine FDEP class: {set(bad)}"


def test_no_mapped_reach_runs_far_inland(asset, coast_grid):
    """The Dunns Creek pin, for the FDEP class.

    `mapped` is exempt from REACH_MI on the argument that a marine WBID is bounded by its own
    polygon — the class turns 3F where the water turns fresh — unlike an OSM `tidal=yes` tag, which
    follows the tide 160 mi up the St Johns. If that argument is ever wrong, it shows up here.
    """
    offenders = []
    for g in asset["geometries"]:
        if g.get("confidence") != "mapped":
            continue
        x, y = g["coordinates"][0]
        mi = _inland_mi(x, y, coast_grid)
        if mi > MAPPED_MAX_INLAND_MI:
            offenders.append((round(mi, 1), (g.get("wbid") or {}).get("name")))
    assert not offenders, (
        f"mapped (verdict-moving) geometry more than {MAPPED_MAX_INLAND_MI} mi from the coast: "
        f"{sorted(offenders, reverse=True)[:5]}")


def test_checker_js_moves_verdicts_on_exactly_the_python_classes():
    """The UI's list and the build's list must not drift.

    They already did: `validate_tidal_against_gauges.py` kept its own copy and silently scored
    3,491 `mapped` reaches as if they were absent from the file. A class the build treats as
    authoritative and the UI treats as a caveat is a silent under-warning; the reverse is a false
    VOID.
    """
    js = CHECKER_JS.read_text()
    in_js = set(re.findall(r"g\.confidence === '([a-z]+)'", js))
    assert in_js == set(VERDICT_MOVING) | {"fresh"}, (
        f"checker.js verdict classes {sorted(in_js)} disagree with VERDICT_MOVING "
        f"{sorted(VERDICT_MOVING)} (+fresh, which is filtered out)")


@pytest.mark.parametrize("lat,lon,why", [
    (26.1876, -81.6431, "Golden Gate Estates, Naples — miles behind the weirs"),
    (25.9490, -80.2800, "inland Snake Creek Canal (C-9), behind structure S-29"),
    (26.1224, -80.2960, "Plantation, inland Broward behind the structures"),
])
def test_no_verdict_moving_water_within_a_mile_of_the_inland_pins(asset, lat, lon, why):
    """The Golden Gate pin, in pytest rather than only in a script that needs the network.

    A mile is the strictest provision in zones.json, so verdict-moving water inside a mile of
    these addresses is a warranty voided by fresh water.
    """
    kx = 111320.0 * math.cos(math.radians(lat))
    best, best_g = float("inf"), None
    for g in asset["geometries"]:
        if g.get("confidence") not in VERDICT_MOVING:
            continue
        for x, y in g["coordinates"]:
            d = math.hypot((x - lon) * kx, (y - lat) * 110540.0)
            if d < best:
                best, best_g = d, g
    ft = best * 3.28084
    assert ft > 5280, (
        f"{why}: verdict-moving water {ft:,.0f} ft away "
        f"({(best_g or {}).get('confidence')}, {((best_g or {}).get('wbid') or {}).get('name')})")
