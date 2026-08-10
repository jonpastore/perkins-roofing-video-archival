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
import shutil
import subprocess
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
        # EVERY vertex, not coordinates[0]. A reach is only split at barriers, not at length —
        # the Golden Gate incident was a 24-mile way — so sampling one endpoint means a runaway
        # whose OSM way happens to START at the coast is invisible to the pin written to catch it.
        # `inf` means no coastline found even at the widest span — that is MORE inland, not less,
        # so it must fail rather than be skipped.
        mi = max(_inland_mi(x, y, coast_grid) for x, y in g["coordinates"])
        if mi > limit:
            offenders.append((round(mi, 1), g["coordinates"][0]))
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
#:
#: ⚠️ NOT a validated bound — it is "twice the biggest number we saw, once", measured against an
#: UNSIGNED distance to the coastline that cannot tell 13 mi up a river from 13 mi out to sea.
#: `test_no_mapped_geometry_lies_outside_a_marine_polygon` is the REAL gate and strictly subsumes
#: this one: with every vertex inside a marine polygon, distance from the coast is bounded by
#: FDEP's own geometry. Do not relax the polygon test on the grounds that "the inland pin covers
#: it" — the dependency runs the other way.
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
        mi = max(_inland_mi(x, y, coast_grid) for x, y in g["coordinates"])   # see the note above
        if mi > MAPPED_MAX_INLAND_MI:
            offenders.append((round(mi, 1), (g.get("wbid") or {}).get("name")))
    assert not offenders, (
        f"mapped (verdict-moving) geometry more than {MAPPED_MAX_INLAND_MI} mi from the coast: "
        f"{sorted(offenders, reverse=True)[:5]}")


def _extract_fn(js: str, name: str) -> str:
    """Slice `function <name>(...) {...}` out of checker.js by brace matching."""
    i = js.index(f"function {name}(")
    j = js.index("{", i)
    depth = 0
    for k in range(j, len(js)):
        if js[k] == "{":
            depth += 1
        elif js[k] == "}":
            depth -= 1
            if depth == 0:
                return js[i:k + 1]
    raise AssertionError(f"unbalanced braces extracting {name}")


def test_checker_js_moves_verdicts_on_exactly_the_python_classes(tmp_path):
    """EXECUTE checker.js's own flatten() and assert which bucket each class lands in.

    The previous version of this test regexed for `g.confidence === '<literal>'` and compared the
    literal set to VERDICT_MOVING. That is a spelling check, not a behavioural one: inserting
    `if (g.confidence === 'mapped') { bucket = out.inferred; }` removes mapped from the
    verdict-moving bucket while leaving the literal set identical, and the old test passed on it —
    verified. It was also brittle the other way, since indexOf/!==/double quotes/minification would
    fail it with no behavioural change at all.

    So run the real function. Every class in VERDICT_MOVING must land in `tagged` (the bucket
    nearestSaltwater measures against), `inferred` must not, and `fresh` must be dropped entirely.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    js = (ASSETS / "checker.js").read_text()
    classes = list(VERDICT_MOVING) + ["inferred", "fresh"]
    geoms = [{"type": "LineString", "confidence": c,
              "coordinates": [[-80.1, 26.1], [-80.2, 26.2]]} for c in classes]
    harness = tmp_path / "harness.js"
    harness.write_text(
        _extract_fn(js, "flatten")
        + "\nconst classes = " + json.dumps(classes) + ";\n"
        + "const doc = {type:'GeometryCollection', geometries: " + json.dumps(geoms) + "};\n"
        + """
const out = {};
for (const c of classes) {
  const one = {type:'GeometryCollection', geometries: doc.geometries.filter(g => g.confidence === c)};
  const r = flatten(one, 'inferred');
  out[c] = r.tagged.length ? 'verdict-moving' : (r.inferred.length ? 'caveat' : 'dropped');
}
console.log(JSON.stringify(out));
""")
    res = subprocess.run([node, str(harness)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, f"node failed: {res.stderr[:400]}"
    got = json.loads(res.stdout)
    expected = {c: "verdict-moving" for c in VERDICT_MOVING}
    expected["inferred"] = "caveat"
    expected["fresh"] = "dropped"
    assert got == expected, f"checker.js buckets {got}, expected {expected}"


def _nearest_verdict_moving(asset, lat, lon):
    """Feet to the nearest verdict-moving water, measured to the SEGMENT as checker.js does.

    ⚠️ Not to the nearest VERTEX. `_simplify` drops collinear points at an 8 m tolerance, so a
    straight canal ships as two vertices however long it runs, and a house beside its midpoint can
    sit a mile from either endpoint. Measured 2026-08-07: the Loxahatchee at Tequesta reads 1,351 ft
    to the segment and 3,066 ft to the nearest vertex. Vertex distance is not a conservative
    approximation — it is wrong in the unsafe direction for the inland pins, which is where this
    was found.
    """
    best, best_g = float("inf"), None
    kx, ky = 111320.0 * math.cos(math.radians(lat)), 110540.0
    for g in asset["geometries"]:
        if g.get("confidence") not in VERDICT_MOVING:
            continue
        c = g["coordinates"]
        for i in range(len(c) - 1):
            ax, ay = c[i]
            bx, by = c[i + 1]
            px, py = (lon - ax) * kx, (lat - ay) * ky
            vx, vy = (bx - ax) * kx, (by - ay) * ky
            l2 = vx * vx + vy * vy
            t = max(0.0, min(1.0, (px * vx + py * vy) / l2)) if l2 else 0.0
            d = math.hypot(px - t * vx, py - t * vy)
            if d < best:
                best, best_g = d, g
    return best * 3.28084, best_g


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
    ft, best_g = _nearest_verdict_moving(asset, lat, lon)
    assert ft > 5280, (
        f"{why}: verdict-moving water {ft:,.0f} ft away "
        f"({(best_g or {}).get('confidence')}, {((best_g or {}).get('wbid') or {}).get('name')})")


@pytest.mark.parametrize("lat,lon,max_ft,why", [
    (26.8560414, -80.0764616, 500,
     "188 Lone Pine Dr, Palm Beach Gardens — Tim's client: dock, boat, rusted-through steel "
     "chimney cap. OSM draws her canal as untagged water polygons; NHD has it at 117 ft"),
    (26.1046644, -80.1703294, 1800, "1350 SW 21st Ter, Fort Lauderdale — New River south fork"),
    (25.7863480, -80.2228480, 900, "1701 NW N River Dr, Miami — Miami River"),
    (26.9708673, -80.0875254, 1500, "18989 SE Federal Hwy, Tequesta — Loxahatchee River"),
])
def test_verdict_moving_water_reaches_the_waterfront_pins(asset, lat, lon, max_ft, why):
    """The mirror of the inland pins, and the gate the layer went a month without.

    Every test above this one bounds the FALSE VOID — verdict-moving water where the water is
    fresh. Nothing bounded the FALSE CLEAR: a house on salt water the layer cannot see reads
    "warranty-safe", and that failure is silent. A homeowner wrongly told VOID complains; one
    wrongly told their steel roof is fine just buys it from the roofer who said yes.

    188 Lone Pine Drive is the case that proved it. It read 3,079 ft and cleared all three steels
    for a client with a boat tied up 117 ft from her house, while every inland pin stayed green,
    because reach geometry came only from OSM `waterway=*` lines and OSM draws that canal as
    untagged `natural=water` polygons. Coordinates are geocoded, never typed from memory.
    """
    ft, best_g = _nearest_verdict_moving(asset, lat, lon)
    assert ft <= max_ft, (
        f"{why}: nearest verdict-moving water is {ft:,.0f} ft away, over the {max_ft:,} ft limit — "
        f"this address reads WARRANTY-SAFE on salt water "
        f"(nearest: {(best_g or {}).get('confidence')}, "
        f"{((best_g or {}).get('wbid') or {}).get('name')})")


def test_no_mapped_geometry_lies_outside_a_marine_polygon(asset):
    """The HIGH-1 pin: `mapped` must not extend past the polygon that authorises it.

    Acceptance is a 60% majority over VERTICES, but vertex density is not length — Pablo Creek
    passed at 186/240 vertices while 5,763 m of its 10,877 m ran outside every marine polygon.
    Labelling the whole reach and then exempting it from REACH_MI shipped 16.5 mi of verdict-moving
    geometry into water FDEP itself classifies 3F, in polygons named "(FRESHWATER SEGMENT)":
    Pablo Creek, South Fork St Lucie, Billy Creek in Fort Myers, Deep Creek. A homeowner on the
    fresh segment read a hard VOID with the state register as the disproof.

    Skips rather than fails when the WBID cache is absent, because the cache is not in git — but
    the build now exits on a missing cache, so a shipped asset cannot have been built without it.
    """
    from scripts.build_tidal_layer import WBID_CACHE, _wbid_at, _wbid_index

    if not WBID_CACHE.exists():
        pytest.skip(f"no FDEP WBID cache at {WBID_CACHE}")
    grid, polys = _wbid_index()
    outside = []
    for g in asset["geometries"]:
        if g.get("confidence") != "mapped":
            continue
        for x, y in g["coordinates"]:
            if _wbid_at(x, y, grid, polys) is None:
                outside.append(((g.get("wbid") or {}).get("name"), x, y))
                break
    assert not outside, (
        f"{len(outside)} mapped geometries have vertices outside every marine WBID: {outside[:5]}")


def test_the_asset_actually_contains_mapped_geometry(asset):
    """MEDIUM-2: every other `mapped` invariant filters on confidence == 'mapped', so all of them
    pass vacuously on a layer built without the FDEP cache. Without this, a fresh clone silently
    rebuilds the pre-feature asset and reports green."""
    n = sum(1 for g in asset["geometries"] if g.get("confidence") == "mapped")
    assert n > 1000, f"only {n} mapped geometries — was the asset built without the FDEP cache?"
