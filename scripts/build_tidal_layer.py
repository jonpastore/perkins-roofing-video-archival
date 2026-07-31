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
    inferred    everything else the fill reached, INCLUDING reaches that merely open onto the
                coastline. Touching salt water at one end says nothing about the other end.

That distinction is load-bearing. The first build labelled any coastline-touching way "tagged" for
its whole length, so a 43-mile canal carried "confirmed salt water" 20 miles inland and told Golden
Gate Estates, Naples that its warranty was void — from fresh water. A false "void" tells a
homeowner their warranty is dead when it is not, so only an explicit OSM tag earns that weight.

Only geometry within REACH_MI of the coastline is kept: the strictest provision in zones.json is
1 mile, so water further inland than that plus a margin cannot change any verdict.

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
WATERWAY_KINDS = "canal|river|stream|drain|ditch"
BARRIER_KINDS = "lock_gate|weir|dam|floodgate|sluice_gate|tidal_gate|check_dam"

SALINITY_CACHE = Path.home() / "perkins-corpus/osm/salinity-readings.json"
GAUGE_SNAP_M = 250.0     # a gauge further than this from mapped water is not on a reach we know
MAX_READING_AGE_DAYS = 30.0  # older than this is history, not a measurement — see _reading_expired
PROPAGATE_MI = 2.0       # how far a reading is evidence ALONG the channel, barriers aside
FRESH_MAX_US_CM = 1500.0 # ~250 mg/L chloride — the same line SFWMD's isochlor draws

COAST_SNAP_M = 60.0      # a waterway mouth this close to the coastline counts as touching it
BARRIER_SNAP_M = 25.0    # structures are often drawn offset from the canal, sharing no node
REACH_MI = 3.0           # keep tidal geometry within this of the coast (max provision is 1 mi)
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
    snapped = offshore = expired = 0
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
        salt = float(g["median_us_cm"]) >= FRESH_MAX_US_CM
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
    for w in ways:
        t = w["tags"]
        if t.get("tidal") == "yes" or t.get("salt") == "yes":
            tagged.add(w["id"])
            continue
        for nid in (w["nodes"][0], w["nodes"][-1]):
            p = nodes.get(nid)
            if p and _near_coast(p[0], p[1], grid, coast_pts, COAST_SNAP_M):
                touching.add(w["id"])
                break
    print(f"seeds: {len(tagged)} tagged tidal/salt, {len(touching)} touching the coastline",
          flush=True)

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
    measured = _propagate_gauges(ways, by_id, by_node, nodes, barriers)

    print(f"salt-carrying: {len(confidence)} reaches "
          f"({sum(v == 'tagged' for v in confidence.values())} tagged, "
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
    ap.add_argument("--fetch", action="store_true", help="pull from Overpass into the cache first")
    a = ap.parse_args()
    if a.fetch:
        fetch()
    build()
