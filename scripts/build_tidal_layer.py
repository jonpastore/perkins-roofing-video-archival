#!/usr/bin/env python3
"""Build the tidal/brackish water layer for the metal-roof warranty tool.

Tim, 2026-07-19: "the river my house is on in FTL definitely is brackish, which carries salt
water." The tool measured distance to OSM `natural=coastline` only, so an address on a tidal canal
five miles inland read as "5.6 mi to salt water" — while the warranties in zones.json are written
against "seacoast, salt or BRACKISH water" out to a mile.

THE PHYSICAL RULE. A South Florida canal is tidal seaward of a salinity control structure and
fresh landward of it. So salt-carrying = connected to tidewater without crossing a structure. That
is what this script computes, at BUILD time; the plugin ships the result as a static asset and
makes no runtime API call.

    seeds       ways tagged tidal=yes / salt=yes, plus any waterway whose geometry touches the
                coastline (within COAST_SNAP_M of a coastline vertex)
    split       every way is CUT at its barrier nodes first — a canal with a weir in the middle is
                fresh on one side, and a way is not an atomic unit
    spread      breadth-first through shared OSM node ids across waterway=canal|river|stream|drain
                |ditch
    barriers    stop at lock_gate / weir / dam / floodgate / sluice_gate / tidal_gate / check_dam,
                whether tagged on a node in the way, drawn as a crossing way, or merely sitting
                within BARRIER_SNAP_M of the channel (most are drawn offset and share no node)

Output `assets/tidal.geojson` — a GeometryCollection of LineStrings, each carrying a `confidence`:

    tagged      OSM tags THIS reach tidal=yes / salt=yes. Authoritative; may move a verdict.
    mapped      FDEP classifies the water body this reach sits in Class III-Marine or Class II,
                AND the fill reached it. Authoritative; may move a verdict; carries the name.
    inferred    everything else the fill reached, INCLUDING reaches that merely open onto the
                coastline. Touching salt water at one end says nothing about the other end.

OSM tags almost no South Florida tidal river (Miami River 0 of 4 ways, New River 0 of 33) and USGS
gauges sit miles apart, so before `mapped` existed the water people actually live on landed in
`inferred` and only ever raised a caveat. Tim, 2026-08-06, on a customer with a dock and a boat and
a rusted-through steel chimney cap: "other roofers came and told her she can install a steel roof.
She 100% can not. I need this tool to work correctly to show her this." Her canal is 590 ft away,
FDEP Class III-Marine, and the tool was clearing steel off a 2.5-mile open-water measurement.

That distinction is load-bearing. The first build labelled any coastline-touching way "tagged" for
its whole length, so a 43-mile canal carried "confirmed salt water" 20 miles inland and told Golden
Gate Estates, Naples that its warranty was void — from fresh water. A false "void" tells a
homeowner their warranty is dead when it is not, so only an explicit OSM tag earns that weight.

Geometry within REACH_MI of the coastline is kept. ONLY `measured` reaches — those anchored to a
real gauge reading, and bounded by PROPAGATE_MI along the channel — are exempt from that clip,
because the clip measures distance to the COASTLINE while the 1-mile provision measures
ADDRESS-to-water. Different quantities, and conflating them hid brackish water homeowners live
beside: the tidal St Johns at Shands Bridge reads 4,300 uS/cm 24 mi from the ocean.

⚠️ `tagged` is NOT exempt, and that is deliberate. OSM `tidal=yes` describes WATER LEVEL, not
salinity — the St Johns' tidal signal runs ~160 mi inland — so exempting it emitted freshwater
Dunns Creek, which drains Crescent Lake, as verdict-moving geometry 25 mi inland. Only a gauge
distinguishes tidal-level from salt.

Usage:
    .venv/bin/python scripts/build_tidal_layer.py --fetch     # pull from Overpass into a cache
    .venv/bin/python scripts/build_tidal_layer.py             # build the asset from the cache
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "wp-plugin/perkins-metal-warranty/assets"
CACHE = Path.home() / "perkins-corpus/osm/florida-waterways.json"
OVERPASS = "https://overpass-api.de/api/interpreter"

# All of Florida: Keys to the Georgia line, Perdido Bay to the Atlantic. Was South Florida only
# (24.40,-82.60,27.70,-79.90); statewide adds Tampa, Jacksonville and the Panhandle — 55,671
# waterways against 21,914 and 174 salinity gauges against 64. Keep this in step with the same
# constant in fetch_salinity_readings.py and validate_tidal_against_gauges.py.
BBOX = "24.30,-87.80,31.10,-79.80"

#: The classes checker.js lets MOVE A WARRANTY VERDICT. One definition, imported by the validator,
#: the pin script and the tests — adding `mapped` in three places and forgetting the fourth is how
#: 3,491 reaches got scored as if they were not in the file at all.
VERDICT_MOVING = ("measured", "tagged", "mapped")
WATERWAY_KINDS = "canal|river|stream|drain|ditch"
BARRIER_KINDS = "lock_gate|weir|dam|floodgate|sluice_gate|tidal_gate|check_dam"

# FDEP's Waterbody IDs. Florida law CLASSIFIES every named water body, and `3M` (Class III-Marine)
# / `2` (Class II shellfish) IS the state saying that water is marine. That is the surface-water
# authority the layer never had: OSM tags almost no South Florida tidal river, and USGS gauges are
# 7+ miles apart, so the water people actually live on lands in `inferred` and only raises a caveat.
#
# ⚠️ WBID polygons are BASIN polygons — they cover dry land. A point-in-polygon test on the ADDRESS
# is therefore meaningless (a dry inland lot inside an estuarine basin returns 3M) and would ship
# exactly the false VOID this module exists to prevent. Only REACH GEOMETRY may be classified: a
# reach is in water by construction, so the basin's class describes the water it is in.
WBID_CACHE = Path.home() / "perkins-corpus/osm/fdep-wbid-marine.json"
WBID_URL = ("https://ca.dep.state.fl.us/arcgis/rest/services/OpenData/WBIDS/MapServer/0/query")
WBID_WHERE = "CLASS IN ('2','3M')"
WBID_PAGE = 1000
WBID_INSIDE_FRAC = 0.6   # most of the reach must lie in the marine basin, not just clip its edge

SALINITY_CACHE = Path.home() / "perkins-corpus/osm/salinity-readings.json"
GAUGE_SNAP_M = 250.0     # a gauge further than this from mapped water is not on a reach we know
MAX_READING_AGE_DAYS = 30.0  # older than this is history, not a measurement — see _reading_expired
PROPAGATE_MI = 2.0       # how far a reading is evidence ALONG the channel, barriers aside
FRESH_MAX_US_CM = 1500.0 # ~250 mg/L chloride — the same line SFWMD's isochlor draws
#: Beyond the coastal band, conductance below this is treated as mineral content rather than
#: marine intrusion, so it raises a caveat instead of voiding a warranty. 2x the fresh line.
INLAND_SALT_MIN_US_CM = 3000.0

COAST_SNAP_M = 60.0      # a waterway mouth this close to the coastline counts as touching it
BARRIER_SNAP_M = 25.0    # structures are often drawn offset from the canal, sharing no node
REACH_MI = 3.0           # clips INFERRED reaches only; evidenced water is never clipped
SIMPLIFY_M = 8.0         # vertex thinning; 1-mile thresholds do not need metre precision

QUERY = f"""
[out:json][timeout:600];
(
  way["waterway"~"^({WATERWAY_KINDS})$"]({BBOX});
  way["natural"="water"]["tidal"="yes"]({BBOX});
  way["natural"="water"]["salt"="yes"]({BBOX});
  way["waterway"~"^({BARRIER_KINDS})$"]({BBOX});
  node["waterway"~"^({BARRIER_KINDS})$"]({BBOX});
);
out body;
>;
out skel qt;
"""


def fetch() -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    print(f"POST {OVERPASS}  (bbox {BBOX}) — this takes a few minutes", flush=True)
    # Overpass answers 406 to a bare body — it wants the query form-encoded under `data`.
    body = urllib.parse.urlencode({"data": QUERY}).encode()
    req = urllib.request.Request(
        OVERPASS, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "perkins-warranty-tool/1.0 (build-time layer generator)"})
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                raw = r.read()
            break
        except (urllib.error.URLError, TimeoutError) as e:  # Overpass rate-limits aggressively
            if attempt == 3:
                sys.exit(f"Overpass failed after {attempt} attempts: {e}")
            wait = 30 * attempt
            print(f"  attempt {attempt} failed ({e}); retrying in {wait}s", flush=True)
            time.sleep(wait)
    CACHE.write_bytes(raw)
    print(f"cached {len(raw) / 1e6:.1f} MB -> {CACHE}", flush=True)


def fetch_wbid() -> None:
    """Cache FDEP's marine-classified water bodies. ~1,358 polygons, changes on a multi-year cycle.

    ⚠️ The host 403s a default urllib/curl user agent. Send a browser UA or you will conclude the
    service is down — the same trap `docs/BRACKISH_DATA_SOURCES.md` records for SFWMD.
    """
    WBID_CACHE.parent.mkdir(parents=True, exist_ok=True)
    feats: list[dict] = []
    offset = 0
    while True:
        q = urllib.parse.urlencode({
            "where": WBID_WHERE, "outFields": "WBID,WATERBODY_NAME,WATER_TYPE,CLASS",
            "outSR": "4326", "returnGeometry": "true", "f": "geojson",
            "resultOffset": offset, "resultRecordCount": WBID_PAGE})
        req = urllib.request.Request(
            f"{WBID_URL}?{q}",
            headers={"User-Agent": "Mozilla/5.0 (perkins-warranty-tool build)"})
        with urllib.request.urlopen(req, timeout=180) as r:
            page = json.loads(r.read())
        got = page.get("features") or []
        feats.extend(got)
        print(f"  WBID page at offset {offset}: {len(got)}", flush=True)
        if len(got) < WBID_PAGE:
            break
        offset += WBID_PAGE
    if not feats:
        sys.exit("FDEP returned no WBID polygons — refusing to cache an empty marine layer")
    WBID_CACHE.write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                     separators=(",", ":")))
    print(f"cached {len(feats)} marine WBIDs -> {WBID_CACHE} "
          f"({WBID_CACHE.stat().st_size / 1e6:.1f} MB)", flush=True)


def _ring_contains(ring: list, x: float, y: float) -> bool:
    """Ray casting. Rings come from ArcGIS as [[lon,lat], ...] and may or may not be closed."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _wbid_index(cell: float = 0.05) -> tuple[dict, list]:
    """Bucket each marine polygon's bbox cells so a point test is local, not 1,358 ray casts."""
    if not WBID_CACHE.exists():
        print(f"no FDEP WBID cache at {WBID_CACHE} — skipping marine classification "
              f"(run with --fetch)", flush=True)
        return {}, []
    polys: list[tuple[list, dict]] = []
    for f in json.loads(WBID_CACHE.read_text())["features"]:
        g = f.get("geometry") or {}
        if g.get("type") == "Polygon":
            parts = [g["coordinates"]]
        elif g.get("type") == "MultiPolygon":
            parts = g["coordinates"]
        else:
            continue
        for part in parts:
            polys.append((part, f.get("properties") or {}))
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (part, _) in enumerate(polys):
        xs = [p[0] for p in part[0]]
        ys = [p[1] for p in part[0]]
        for cx in range(int(min(xs) / cell), int(max(xs) / cell) + 1):
            for cy in range(int(min(ys) / cell), int(max(ys) / cell) + 1):
                grid[(cx, cy)].append(i)
    print(f"FDEP WBID: {len(polys)} marine polygons ({WBID_WHERE})", flush=True)
    return grid, polys


def _wbid_at(lon: float, lat: float, grid: dict, polys: list, cell: float = 0.05) -> dict | None:
    for i in grid.get((int(lon / cell), int(lat / cell)), ()):
        part, props = polys[i]
        if not _ring_contains(part[0], lon, lat):
            continue
        if any(_ring_contains(hole, lon, lat) for hole in part[1:]):
            continue    # a hole is not the water body
        return props
    return None


def _classify_wbid(ways, by_id, nodes, confidence: dict) -> dict:
    """Which `inferred` reaches lie inside a marine-classified water body.

    Only `inferred` is considered, and that conjunction is the safety argument: the reach is
    ALREADY known to connect to tidewater without crossing a control structure, and FDEP
    INDEPENDENTLY classifies the water body it sits in as marine. Either signal alone is weak —
    connectivity because OSM's barrier coverage is incomplete, the class because the polygon covers
    dry land too — but they fail in unrelated ways, so agreeing is evidence.

    Verified against the cases that matter (2026-08-06): Tim's client's canal in Palm Beach Gardens
    reads ICWW ABOVE ROYAL PALM BRIDGE / ESTUARY / 3M, his own New River reads ESTUARY / 3M, while
    Golden Gate Estates, Wellington and Jupiter Farms — the three known false-VOID traps — all read
    STREAM / 3F and are untouched.
    """
    grid, polys = _wbid_index()
    if not polys:
        return {}
    out: dict[str, dict] = {}
    rings = 0
    for wid, conf in confidence.items():
        if conf != "inferred":
            continue
        # A CLOSED ring is a water POLYGON — a pond or lagoon outline — not a channel, and the
        # whole outline would be emitted as verdict-moving geometry. The tagged seed already
        # excludes rings for this reason; the fill can still REACH one, and before this the marine
        # class promoted 19 of them. Left `inferred`, so they still raise the caveat.
        w_nodes = by_id[wid]["nodes"]
        if len(w_nodes) > 2 and w_nodes[0] == w_nodes[-1]:
            rings += 1
            continue
        pts = [nodes[n] for n in w_nodes if n in nodes]
        if not pts:
            continue
        hits = [_wbid_at(x, y, grid, polys) for x, y in pts]
        marine = [h for h in hits if h]
        if len(marine) < WBID_INSIDE_FRAC * len(hits):
            continue
        # Name the water body the majority of the reach sits in, so the citation is specific.
        top = max({m.get("WBID"): m for m in marine}.values(),
                  key=lambda m: sum(1 for h in marine if h.get("WBID") == m.get("WBID")))
        out[wid] = {"wbid": top.get("WBID"), "name": top.get("WATERBODY_NAME"),
                    "water_class": top.get("CLASS"), "water_type": top.get("WATER_TYPE")}
    print(f"FDEP WBID: {len(out)} inferred reaches sit in marine water bodies -> mapped "
          f"({rings} closed rings left inferred — a pond outline is not a channel)", flush=True)
    return out


def _reading_expired(latest_at: str | None, now: datetime | None = None) -> bool:
    """True if a gauge reading is too old to be evidence about the water today.

    An UNPARSEABLE or missing timestamp counts as expired. That is the safe direction: the cost of
    dropping a good reading is a reach labelled `inferred` (a caveat), while the cost of keeping a
    bad one is a homeowner told their warranty is VOID on a measurement nobody can date.
    """
    if not latest_at:
        return True
    try:
        ts = datetime.fromisoformat(latest_at)
    except (TypeError, ValueError):
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ref = now or datetime.now(timezone.utc)
    return (ref - ts).total_seconds() > MAX_READING_AGE_DAYS * 86400


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    kx = 111320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lon2 - lon1) * kx, (lat2 - lat1) * 110540.0)


def _coast_index(cell: float = 0.01) -> tuple[dict, list]:
    """Grid-bucket every coastline vertex so 'touches the coast' is a local lookup, not O(n)."""
    coast = json.loads((ASSETS / "coastline.geojson").read_text())
    geoms = coast["geometries"] if coast.get("type") == "GeometryCollection" else [
        f["geometry"] for f in coast["features"]]
    pts: list[tuple[float, float]] = []
    for g in geoms:
        parts = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        for part in parts:
            pts.extend((float(x), float(y)) for x, y in part)
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (x, y) in enumerate(pts):
        grid[(int(x / cell), int(y / cell))].append(i)
    return grid, pts


def _near_coast(lon: float, lat: float, grid: dict, pts: list, radius_m: float,
                cell: float = 0.01) -> bool:
    span = int(radius_m / (cell * 92000.0)) + 1     # cell width in metres at this latitude
    cx, cy = int(lon / cell), int(lat / cell)
    for dx in range(-span, span + 1):
        for dy in range(-span, span + 1):
            for i in grid.get((cx + dx, cy + dy), ()):
                px, py = pts[i]
                if _haversine_m(lat, lon, py, px) <= radius_m:
                    return True
    return False


def _simplify(coords: list, tol_m: float) -> list:
    """Drop vertices closer than tol_m to the previous kept one. Endpoints always survive."""
    if len(coords) < 3:
        return coords
    out = [coords[0]]
    for x, y in coords[1:-1]:
        px, py = out[-1]
        if _haversine_m(py, px, y, x) >= tol_m:
            out.append((x, y))
    out.append(coords[-1])
    return out


def _reach_cells(grid: dict, reach_m: float, cell: float = 0.01) -> set:
    """Coarse raster of cells within reach_m of the coast, so clipping is an O(1) lookup.

    Dilating the coastline's own cells is ~100x cheaper than testing every waterway vertex
    against every nearby coastline point, and cell granularity (~1 km) is far finer than the
    3-mile clip needs.
    """
    span = int(reach_m / (cell * 92000.0)) + 1
    out = set()
    for cx, cy in grid:
        for dx in range(-span, span + 1):
            for dy in range(-span, span + 1):
                out.add((cx + dx, cy + dy))
    return out


def _propagate_gauges(ways, by_id, by_node, nodes, barriers) -> dict:
    """Attach each salinity reading to the reaches it is actually evidence about.

    A gauge measures the water it stands in. That is strong evidence for its own reach and the
    connected water either side of it, and progressively weaker further away — the two Loxahatchee
    gauges read 52,500 uS/cm at the US-1 mouth and 709 uS/cm at mile 9.1, on the same river. So a
    reading spreads along CHANNEL distance, stops dead at a control structure, and gives up at
    PROPAGATE_MI. Where two gauges reach the same water, the nearer one wins.
    """
    # Prefer the cache the hourly sweep publishes (jobs/salinity_sweep.py) so a rebuild uses
    # current readings without anyone remembering to refresh first; fall back to the local file
    # when GCS is unreachable or unconfigured, which is the normal case on a laptop.
    raw = None
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    if project:
        try:
            # Running a script inside scripts/ puts THAT directory on sys.path, not the repo root,
            # so the package needs adding before it can be imported.
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            from adapters.storage import download_file, object_exists
            key = "warranty-tool/salinity-readings.json"
            if object_exists(f"{project}-media", key):
                with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                    download_file(f"{project}-media", key, tmp.name)
                raw = Path(tmp.name).read_text()
                os.unlink(tmp.name)
                print("salinity readings: using the published GCS cache", flush=True)
        except Exception as e:                       # noqa: BLE001 — local build must still work
            print(f"salinity readings: GCS unavailable ({e}); using the local cache", flush=True)
    if raw is None:
        if not SALINITY_CACHE.exists():
            print(f"no salinity cache at {SALINITY_CACHE} — skipping gauge anchoring", flush=True)
            return {}
        raw = SALINITY_CACHE.read_text()
    gauges = json.loads(raw)["gauges"]

    # index reach vertices so snapping is local
    vgrid: dict[tuple[int, int], list[tuple[str, int]]] = defaultdict(list)
    for w in ways:
        for nid in w["nodes"]:
            p_ = nodes.get(nid)
            if p_:
                vgrid[(int(p_[0] / 0.01), int(p_[1] / 0.01))].append((w["id"], nid))

    cap_m = PROPAGATE_MI * 1609.34
    best: dict[str, dict] = {}
    snapped = offshore = expired = marginal_inland = 0
    # Which cells sit inside the coastal band — used to decide whether a MARGINAL reading is
    # plausibly marine or is just an inland mineral spring. See the note at the salt test.
    _coast_grid, _ = _coast_index()
    in_reach_coast = _reach_cells(_coast_grid, REACH_MI * 1609.34)
    for g in gauges.values():
        if g.get("lat") is None:
            continue
        # A reading is evidence about water TODAY, not about water in 2011.
        #
        # USGS `siteStatus=active` returns stations that are nominally active but whose last
        # instantaneous value can be years old, and the latest-value endpoint serves it without
        # complaint. Measured 2026-07-31: 65 of 171 gauges had not reported in over 30 days and
        # 33 of those were classified salt/brackish — including MCCORMICK CREEK AT MOUTH NEAR KEY
        # LARGO at 42,300 uS/cm from a reading 5,415 DAYS old. Every one of them was moving
        # verdicts while the UI cited "measured at ... uS/cm", which reads as current.
        #
        # The cache `_note` has always claimed a reading older than the window "degrades from
        # 'measured' to 'mapped'". Nothing implemented it. This does: an expired gauge simply is
        # not a measurement, so its reaches revert to whatever we would have believed without it
        # (`tagged` or `inferred`) instead of carrying a false citation.
        if _reading_expired(g.get("latest_at")):
            expired += 1
            continue
        glat, glon = float(g["lat"]), float(g["lon"])
        cx, cy = int(glon / 0.01), int(glat / 0.01)
        near = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for wid, nid in vgrid.get((cx + dx, cy + dy), ()):
                    px, py = nodes[nid]
                    d = _haversine_m(glat, glon, py, px)
                    if d <= GAUGE_SNAP_M and (near is None or d < near[0]):
                        near = (d, wid, nid)
        if near is None:
            offshore += 1
            continue
        snapped += 1
        seed_d, seed_way, seed_node = near
        # Specific conductance measures DISSOLVED MINERALS, not chloride. The 1,500 uS/cm line is
        # borrowed from SFWMD's 250 mg/L isochlor, which is a South Florida COASTAL AQUIFER
        # standard. Far inland the same number stops meaning "marine intrusion": Blue Spring at
        # Orange City is a first-magnitude FRESHWATER artesian spring — the manatee refuge — and
        # reads 1,620, clearing the threshold by 8% on aquifer mineral content 35 mi from the sea.
        # Warm Mineral Springs reads 28,600 and is named for the reason it does.
        #
        # So beyond the coastal band a MARGINAL reading is not allowed to void a warranty; it
        # falls back to `inferred`, which still raises the caveat. A decisive reading (Alafia
        # 21,600, Spring Creek 47,300, St Johns at Shands 4,300) still counts, because those are
        # genuinely brackish and the tool exists to catch them.
        #
        # ponytail: crude proxy — inland margin, not ion chemistry. The real fix is a
        # chloride-specific parameter (USGS 00940) instead of conductance; do that if a spring
        # ever produces a wrong answer a customer notices.
        us_cm = float(g["median_us_cm"])
        salt = us_cm >= FRESH_MAX_US_CM
        if salt and us_cm < INLAND_SALT_MIN_US_CM:
            gx, gy = int(glon / 0.01), int(glat / 0.01)
            if (gx, gy) not in in_reach_coast:
                salt = False
                marginal_inland += 1
        # BFS over reaches, carrying channel distance from the gauge
        queue = deque([(seed_way, seed_d)])
        seen = {seed_way: seed_d}
        while queue:
            wid, dist = queue.popleft()
            cur = best.get(wid)
            if cur is None or dist < cur["distance_m"]:
                best[wid] = {"salt": salt, "us_cm": g["median_us_cm"], "station": g["id"],
                             "station_name": g["name"], "measured_at": g.get("latest_at"),
                             "windowed": bool(g.get("windowed")), "distance_m": round(dist)}
            w = by_id[wid]
            coords = [nodes[n] for n in w["nodes"] if n in nodes]
            span = sum(_haversine_m(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0])
                       for i in range(len(coords) - 1))
            onward = dist + span
            if onward > cap_m:
                continue
            for nid in w["nodes"]:
                if nid in barriers:
                    continue
                for nxt in by_node.get(nid, ()):
                    if nxt not in seen or onward < seen[nxt]:
                        seen[nxt] = onward
                        queue.append((nxt, onward))
    salt_n = sum(1 for v in best.values() if v["salt"])
    if expired:
        print(f"gauges: {expired} IGNORED — last reading older than {MAX_READING_AGE_DAYS:.0f}d "
              f"(a stale reading is history, not evidence about the water today)", flush=True)
    if marginal_inland:
        print(f"gauges: {marginal_inland} marginal inland readings held to a CAVEAT "
              f"(<{INLAND_SALT_MIN_US_CM:.0f} uS/cm beyond the coastal band — mineral springs read "
              f"salt on conductance)", flush=True)
    print(f"gauges: {snapped} snapped to a reach, {offshore} not on mapped water; "
          f"{len(best)} reaches carry a measurement ({salt_n} salt, {len(best) - salt_n} fresh)",
          flush=True)
    return best


def build() -> None:
    if not CACHE.exists():
        sys.exit(f"no cache at {CACHE} — run with --fetch first")
    data = json.loads(CACHE.read_text())
    elements = data["elements"]
    barrier_kinds = set(BARRIER_KINDS.split("|"))

    nodes = {e["id"]: (e["lon"], e["lat"]) for e in elements if e["type"] == "node" and "lat" in e}
    barrier_nodes = {e["id"] for e in elements
                     if e["type"] == "node" and (e.get("tags") or {}).get("waterway") in
                     barrier_kinds}
    raw_ways = []
    barrier_way_nodes: set[int] = set()
    barrier_pts: list[tuple[float, float]] = []
    for e in elements:
        if e["type"] != "way":
            continue
        tags = e.get("tags") or {}
        if tags.get("waterway") in barrier_kinds:
            barrier_way_nodes.update(e.get("nodes") or ())
            barrier_pts.extend(nodes[n] for n in (e.get("nodes") or ()) if n in nodes)
            continue
        raw_ways.append({"id": e["id"], "nodes": e.get("nodes") or [], "tags": tags})
    barriers = barrier_nodes | barrier_way_nodes
    barrier_pts.extend(nodes[n] for n in barrier_nodes if n in nodes)

    # Most structures are drawn as a dam way or an unsnapped node OFFSET from the canal, sharing no
    # node with it, so a node-id-only cut sails straight past them. Snap every barrier position to
    # waterway vertices within BARRIER_SNAP_M and cut there too.
    vgrid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for w in raw_ways:
        for nid in w["nodes"]:
            p = nodes.get(nid)
            if p:
                vgrid[(int(p[0] / 0.002), int(p[1] / 0.002))].append(nid)
    snapped = 0
    for bx, by in barrier_pts:
        cx, cy = int(bx / 0.002), int(by / 0.002)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for nid in vgrid.get((cx + dx, cy + dy), ()):
                    p = nodes[nid]
                    if nid not in barriers and _haversine_m(by, bx, p[1], p[0]) <= BARRIER_SNAP_M:
                        barriers.add(nid)
                        snapped += 1
    print(f"{len(raw_ways)} waterways, {len(nodes)} nodes, {len(barriers)} barrier nodes "
          f"({snapped} snapped geometrically)", flush=True)

    # A way is not atomic: a canal with a weir in the middle is fresh on one side. Split every way
    # AT its barrier nodes so the fill cannot cross a structure inside a single way.
    ways = []
    for w in raw_ways:
        run: list[int] = []
        for nid in w["nodes"]:
            if nid in barriers:
                if len(run) >= 2:
                    ways.append({"id": f"{w['id']}:{len(ways)}", "nodes": run, "tags": w["tags"]})
                run = []
            else:
                run.append(nid)
        if len(run) >= 2:
            ways.append({"id": f"{w['id']}:{len(ways)}", "nodes": run, "tags": w["tags"]})
    print(f"split into {len(ways)} reaches at barriers", flush=True)

    # --- seeds -------------------------------------------------------------------------------
    grid, coast_pts = _coast_index()
    tagged, touching = set(), set()
    rings = 0
    for w in ways:
        t = w["tags"]
        if t.get("tidal") == "yes" or t.get("salt") == "yes":
            # A CLOSED ring is a water POLYGON (a lake or pond outline), not a channel. Splitting
            # it at barriers and flooding it through the channel BFS is meaningless — a lake has
            # no upstream — and its whole outline would be emitted as verdict-moving geometry.
            # 78 of the tagged ways are rings, Dunns Creek's freshwater Crescent Lake among them.
            # Treating them as channels is how a lake ends up voiding a warranty.
            if len(w["nodes"]) > 2 and w["nodes"][0] == w["nodes"][-1]:
                rings += 1
                continue
            tagged.add(w["id"])
            continue
        for nid in (w["nodes"][0], w["nodes"][-1]):
            p = nodes.get(nid)
            if p and _near_coast(p[0], p[1], grid, coast_pts, COAST_SNAP_M):
                touching.add(w["id"])
                break
    print(f"seeds: {len(tagged)} tagged tidal/salt, {len(touching)} touching the coastline, "
          f"{rings} closed rings (water polygons) excluded", flush=True)

    # --- spread through shared nodes, stopping at barriers ------------------------------------
    by_node: dict[int, list] = defaultdict(list)
    by_id = {w["id"]: w for w in ways}
    for w in ways:
        for nid in w["nodes"]:
            if nid not in barriers:
                by_node[nid].append(w["id"])

    # ONLY an explicit OSM tidal/salt tag is authoritative. A reach that merely opens onto the
    # coastline seeds the fill but is itself INFERRED: touching the water at one end says nothing
    # about the other end, and labelling a 43-mile canal "confirmed" from one coastal node is
    # exactly how Golden Gate Estates got told its warranty was void by fresh water.
    confidence = {wid: "tagged" for wid in sorted(tagged)}
    queue = deque(confidence)
    for wid in sorted(touching):
        if wid not in confidence:
            confidence[wid] = "inferred"
            queue.append(wid)
    while queue:
        wid = queue.popleft()
        for nid in by_id[wid]["nodes"]:
            if nid in barriers:
                continue
            for nxt in by_node.get(nid, ()):
                if nxt not in confidence:
                    confidence[nxt] = "inferred"
                    queue.append(nxt)
    # FDEP's class before the gauges, so a gauge reading still overrides it in BOTH directions —
    # `measured` fresh water must beat a marine basin exactly as it beats an OSM tidal tag.
    marine = _classify_wbid(ways, by_id, nodes, confidence)
    for wid in marine:
        confidence[wid] = "mapped"
    measured = _propagate_gauges(ways, by_id, by_node, nodes, barriers)

    print(f"salt-carrying: {len(confidence)} reaches "
          f"({sum(v == 'tagged' for v in confidence.values())} tagged, "
          f"{sum(v == 'mapped' for v in confidence.values())} mapped FDEP-marine, "
          f"{sum(v == 'inferred' for v in confidence.values())} inferred)", flush=True)

    # --- emit: CLIP geometry to the coastal reach, don't just filter whole ways ----------------
    reach_m = REACH_MI * 1609.34
    in_reach = _reach_cells(grid, reach_m)
    geoms, kept, clipped, promoted, suppressed = [], 0, 0, 0, 0
    # A reading outranks the OSM tag AND connectivity, in BOTH directions. Upstream Broad River is
    # tagged tidal and measures 460 uS/cm; keeping it would be preserving a known false VOID to
    # look conservative. Water measured fresh leaves the layer entirely.
    for wid in list(measured):
        if wid not in confidence and measured[wid]["salt"]:
            confidence[wid] = "inferred"          # measured salt water we had not reached at all
    prior: dict[str, str] = {}
    for wid, conf in list(confidence.items()):
        m = measured.get(wid)
        if not m:
            continue
        prior[wid] = conf                     # what we would have said without the reading
        if m["salt"]:
            promoted += 1
            confidence[wid] = "measured"
        else:
            # Known-fresh water is KEPT and labelled, not deleted. Absence cannot be told apart
            # from "never mapped", and the hold-one-out check needs to know what we would have
            # believed here without the gauge. The UI ignores this class entirely.
            confidence[wid] = "fresh"
            suppressed += 1
    print(f"measurement: {promoted} reaches promoted to measured, {suppressed} labelled "
          f"measured FRESH (kept in the file, ignored by the UI)", flush=True)

    for wid, conf in confidence.items():
        coords = [nodes[n] for n in by_id[wid]["nodes"] if n in nodes]
        # ⚠️ The clip measures distance to the COASTLINE. The 1-mile provision measures
        # ADDRESS-to-water. Those are different quantities, and conflating them is why a house
        # 500 ft from the tidal St Johns got no tidal answer at all: the river is 14 mi from the
        # ocean, so it was clipped, even though the homeowner is 500 ft from brackish water.
        #
        # Measured 2026-07-31 with stale gauges already excluded: 18 LIVE salt/brackish gauges sit
        # beyond the 3-mile line, including St Lucie at Speedy Point (30,700 uS/cm, 3.1 mi), the
        # Alafia at Riverview (21,600, 4.3 mi) and the Hillsborough at I-275 (14,000, 4.6 mi).
        #
        # ⚠️ ONLY a gauge reading earns the exemption. `tagged` MUST STILL BE CLIPPED.
        #
        # The first version of this exempted `tagged` too, and that shipped a false VOID. OSM
        # `tidal=yes` is a statement about WATER LEVEL, not about salinity: the St Johns' tidal
        # signal propagates ~160 miles inland, so Dunns Creek — which drains FRESHWATER Crescent
        # Lake near Welaka — carries `tidal=yes` and was emitted as verdict-moving geometry 25 mi
        # inland. A homeowner there would have been told their metal roof warranty is void, from
        # fresh water. That is the Golden Gate Estates failure in this module's own docstring,
        # recreated by the fix for a different problem. Caught by review the same day.
        #
        # This repo already held the disproof: the header note records Upstream Broad River as
        # OSM-tagged tidal and MEASURING 460 uS/cm — fresh. And the gauge override cannot save a
        # tagged reach, because by construction every reach with a gauge is promoted out of
        # `tagged` into `measured`/`fresh` first. So nothing bounds a tagged reach but this clip.
        #
        # `measured` is different in kind: it is anchored to a real reading and propagates at most
        # PROPAGATE_MI along the channel, so it cannot run away inland. `fresh` only ever REMOVES
        # a warning, so keeping it far inland is the safe direction.
        # `mapped` is exempt for the same reason `measured` is, and NOT for the reason `tagged`
        # was wrongly given: a marine WBID is bounded by its own polygon — the class changes to 3F
        # where the water turns fresh — so it cannot run away inland the way an OSM `tidal=yes` tag
        # runs 160 mi up the St Johns. The clip measures distance to the COASTLINE, and Tim's
        # client lives 590 ft from Class III-Marine water that is 2.5 mi from open water.
        evidenced = conf in ("measured", "fresh", "mapped")
        if evidenced:
            parts = [coords] if len(coords) >= 2 else []
        else:
            run: list[tuple[float, float]] = []
            parts = []
            for x, y in coords:
                if (int(x / 0.01), int(y / 0.01)) in in_reach:
                    run.append((x, y))
                else:
                    if len(run) >= 2:
                        parts.append(run)
                    run = []
            if len(run) >= 2:
                parts.append(run)
            if len(parts) != 1 or len(parts[0]) != len(coords):
                clipped += 1
        m = measured.get(wid)
        for part in parts:
            g = {"type": "LineString", "confidence": conf,
                 "coordinates": [[round(x, 5), round(y, 5)]
                                 for x, y in _simplify(part, SIMPLIFY_M)]}
            if conf == "mapped":
                g["wbid"] = marine[wid]
            if conf in ("measured", "fresh") and m:
                g["measurement"] = {
                    "us_cm": m["us_cm"], "station": m["station"],
                    "station_name": m["station_name"], "measured_at": m["measured_at"],
                    "distance_m": m["distance_m"], "windowed": m["windowed"],
                    "prior": prior.get(wid, "inferred")}
            geoms.append(g)
            kept += 1
    out = {"type": "GeometryCollection", "geometries": geoms,
           "_note": ("Salt-carrying inland water for the warranty checker. confidence=measured: a "
                     "USGS salinity gauge on this reach reads brackish or saline — authoritative, "
                     "carries its reading. Water MEASURED FRESH is removed from this file "
                     "entirely. confidence=tagged: OSM "
                     "tags the reach tidal=yes or salt=yes — authoritative, may move a verdict. "
                     "confidence=mapped: FDEP classifies this water body Class III-Marine or "
                     "Class II AND the reach connects to tidewater without crossing a structure — "
                     "authoritative, may move a verdict, carries the water body's name. "
                     "confidence=inferred: reached from tidewater through shared nodes without "
                     "crossing a mapped control structure, INCLUDING reaches that merely open onto "
                     "the coastline. OSM barrier coverage is incomplete, so the UI must never turn "
                     "an inferred reach into a hard 'void' verdict."),
           "_coverage_bbox": BBOX,
           "_built_by": "scripts/build_tidal_layer.py", "_source": "OpenStreetMap via Overpass"}
    # Sorted so a rebuild is byte-identical: without it the asset reshuffles every run and a
    # 0.93 MB diff hides whether anything actually changed.
    geoms.sort(key=lambda g: (g["confidence"], g["coordinates"]))
    path = ASSETS / "tidal.geojson"
    path.write_text(json.dumps(out, separators=(",", ":")))
    print(f"emitted {kept} geometries ({clipped} reaches clipped at {REACH_MI} mi) -> "
          f"{path.name}, {path.stat().st_size / 1e6:.2f} MB", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true",
                    help="pull Overpass + the FDEP WBID classes into the caches first")
    ap.add_argument("--fetch-wbid", action="store_true",
                    help="refresh only the FDEP marine-WBID cache (seconds, vs minutes for OSM)")
    a = ap.parse_args()
    if a.fetch:
        fetch()
    if a.fetch or a.fetch_wbid:
        fetch_wbid()
    build()
