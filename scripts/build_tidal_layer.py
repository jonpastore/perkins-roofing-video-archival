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
    spread      breadth-first through shared OSM node ids across waterway=canal|river|stream|drain
    barriers    stop at lock_gate / weir / dam / floodgate / sluice_gate / tidal_gate, whether
                tagged on a node in the way or as a crossing way

Output `assets/tidal.geojson` — a GeometryCollection of LineStrings, each carrying a `confidence`
of "tagged" (OSM says so outright) or "inferred" (connectivity). The UI must show the two
differently: OSM barrier coverage is incomplete, and a false "void" tells a homeowner their
warranty is dead when it is not.

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
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "wp-plugin/perkins-metal-warranty/assets"
CACHE = Path.home() / "perkins-corpus/osm/south-florida-waterways.json"
OVERPASS = "https://overpass-api.de/api/interpreter"

# South Florida, both coasts: Keys up through Martin / St. Lucie and across to Lee / Collier.
BBOX = "24.40,-82.60,27.70,-79.90"
WATERWAY_KINDS = "canal|river|stream|drain|ditch"
BARRIER_KINDS = "lock_gate|weir|dam|floodgate|sluice_gate|tidal_gate|check_dam"

COAST_SNAP_M = 60.0      # a waterway mouth this close to the coastline counts as touching it
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


def build() -> None:
    if not CACHE.exists():
        sys.exit(f"no cache at {CACHE} — run with --fetch first")
    data = json.loads(CACHE.read_text())
    elements = data["elements"]

    nodes = {e["id"]: (e["lon"], e["lat"]) for e in elements if e["type"] == "node" and "lat" in e}
    barrier_nodes = {e["id"] for e in elements
                     if e["type"] == "node" and (e.get("tags") or {}).get("waterway") in
                     set(BARRIER_KINDS.split("|"))}
    ways = []
    barrier_way_nodes: set[int] = set()
    for e in elements:
        if e["type"] != "way":
            continue
        tags = e.get("tags") or {}
        wtype = tags.get("waterway")
        if wtype in set(BARRIER_KINDS.split("|")):
            barrier_way_nodes.update(e.get("nodes") or ())
            continue
        ways.append({"id": e["id"], "nodes": e.get("nodes") or [], "tags": tags})
    barriers = barrier_nodes | barrier_way_nodes

    print(f"{len(ways)} waterways, {len(nodes)} nodes, {len(barriers)} barrier nodes", flush=True)

    # --- seeds -------------------------------------------------------------------------------
    grid, coast_pts = _coast_index()
    tagged, touching = set(), set()
    for w in ways:
        t = w["tags"]
        if t.get("tidal") == "yes" or t.get("salt") == "yes":
            tagged.add(w["id"])
            continue
        for nid in (w["nodes"][0], w["nodes"][-1]) if w["nodes"] else ():
            p = nodes.get(nid)
            if p and _near_coast(p[0], p[1], grid, coast_pts, COAST_SNAP_M):
                touching.add(w["id"])
                break
    print(f"seeds: {len(tagged)} tagged tidal/salt, {len(touching)} touching the coastline",
          flush=True)

    # --- spread through shared nodes, stopping at barriers ------------------------------------
    by_node: dict[int, list[int]] = defaultdict(list)
    by_id = {w["id"]: w for w in ways}
    for w in ways:
        for nid in w["nodes"]:
            if nid not in barriers:
                by_node[nid].append(w["id"])

    confidence = {wid: "tagged" for wid in tagged}
    for wid in touching:
        confidence.setdefault(wid, "tagged")     # a mouth on the coastline is not an inference
    queue = deque(confidence)
    while queue:
        wid = queue.popleft()
        for nid in by_id[wid]["nodes"]:
            if nid in barriers:
                continue
            for nxt in by_node.get(nid, ()):
                if nxt not in confidence:
                    confidence[nxt] = "inferred"
                    queue.append(nxt)
    print(f"salt-carrying: {len(confidence)} ways "
          f"({sum(v == 'tagged' for v in confidence.values())} tagged, "
          f"{sum(v == 'inferred' for v in confidence.values())} inferred)", flush=True)

    # --- emit, clipped to the coastal reach and thinned ----------------------------------------
    reach_m = REACH_MI * 1609.34
    geoms, kept, dropped = [], 0, 0
    for wid, conf in confidence.items():
        coords = [nodes[n] for n in by_id[wid]["nodes"] if n in nodes]
        if len(coords) < 2:
            continue
        if not any(_near_coast(x, y, grid, coast_pts, reach_m, cell=0.01) for x, y in
                   coords[:: max(1, len(coords) // 4)]):
            dropped += 1
            continue
        geoms.append({"type": "LineString", "confidence": conf,
                      "coordinates": [[round(x, 5), round(y, 5)]
                                      for x, y in _simplify(coords, SIMPLIFY_M)]})
        kept += 1
    out = {"type": "GeometryCollection", "geometries": geoms,
           "_note": ("Salt-carrying inland water for the warranty checker. confidence=tagged: OSM "
                     "says tidal/salt outright, or the reach opens onto the mapped coastline. "
                     "confidence=inferred: connected to tidewater through shared nodes without "
                     "crossing a mapped control structure — OSM barrier coverage is incomplete, so "
                     "the UI must not turn an inferred reach into a hard 'void' verdict."),
           "_built_by": "scripts/build_tidal_layer.py", "_source": "OpenStreetMap via Overpass"}
    path = ASSETS / "tidal.geojson"
    path.write_text(json.dumps(out, separators=(",", ":")))
    print(f"kept {kept} reaches ({dropped} dropped beyond {REACH_MI} mi of coast) -> "
          f"{path.name}, {path.stat().st_size / 1e6:.2f} MB", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="pull from Overpass into the cache first")
    a = ap.parse_args()
    if a.fetch:
        fetch()
    build()
