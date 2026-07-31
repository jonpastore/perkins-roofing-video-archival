#!/usr/bin/env python3
"""Sanity-check the tidal layer against known addresses before it ships.

The connectivity inference does most of the work (3,480 inferred segments against 159 tagged),
and a FALSE positive here tells a homeowner their warranty is void when it is not. So the layer
gets checked against addresses whose answer we can reason about independently, not just eyeballed.

Geocodes through Nominatim (build-time only, same as the layer itself) and reports, per address,
the distance to the mapped coastline and to the nearest tidal reach with its confidence.

Usage: .venv/bin/python scripts/check_tidal_layer.py
"""
from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "wp-plugin/perkins-metal-warranty/assets"

CASES = [
    # address, what we expect and why
    ("10307 Utopia Cir N, Boynton Beach, FL 33437",
     "~5.6 mi inland, west of I-95; canals here sit behind SFWMD salinity structures"),
    ("100 Worth Ave, Palm Beach, FL 33480",
     "barrier island between the ocean and the Intracoastal — must read as salt water, very close"),
    ("1 E Las Olas Blvd, Fort Lauderdale, FL 33301",
     "New River downtown — tidal/brackish, Tim's own example of the problem"),
    ("2000 Main St, Sarasota, FL 34237", "Gulf coast, a few blocks inland"),
    ("1200 S Pine Island Rd, Plantation, FL 33324",
     "deep inland Broward, behind the water-management structures — should NOT read as salt"),
    # Inland tidal rivers: the whole point of the layer. Open water is far, the river is not.
    ("1350 SW 21st Ter, Fort Lauderdale, FL 33312", "New River south fork, inland FTL — Tim's case"),
    ("1701 NW North River Dr, Miami, FL 33125", "Miami River, well inland of Biscayne Bay"),
    ("18989 SE Federal Hwy, Tequesta, FL 33469", "Loxahatchee River, Jupiter branch's own back yard"),
]

# Regression pins. The first build labelled any reach that merely touched the coastline "tagged"
# for its whole length, so a 24-mile canal carried "confirmed salt water" 20 miles inland and told
# Golden Gate Estates its warranty was void from fresh water. Nothing may be TAGGED this far
# inland — inferred is fine there, it only raises a caveat.
NEVER_TAGGED_NEAR = [
    ((26.1876, -81.6431), "Golden Gate Estates, Naples — miles behind the weirs on C-4/Golden Gate"),
    ((25.9490, -80.2800), "inland reach of Snake Creek Canal (C-9), behind structure S-29"),
    ((26.1224, -80.2960), "Plantation, inland Broward behind the water-management structures"),
]


def geocode(addr: str) -> tuple[float, float]:
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": addr, "format": "json", "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": "perkins-warranty-tool/1.0 (check)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        js = json.loads(r.read())
    if not js:
        raise RuntimeError(f"no geocode for {addr}")
    return float(js[0]["lat"]), float(js[0]["lon"])


def _segments(path: Path) -> list[tuple]:
    d = json.loads(path.read_text())
    geoms = d["geometries"] if d.get("type") == "GeometryCollection" else [
        f["geometry"] for f in d["features"]]
    segs = []
    for g in geoms:
        conf = g.get("confidence", "coast")
        c = g["coordinates"]
        for i in range(len(c) - 1):
            segs.append((c[i][0], c[i][1], c[i + 1][0], c[i + 1][1], conf))
    return segs


def nearest(lat: float, lon: float, segs: list[tuple]) -> tuple[float, str]:
    kx, ky = 111320.0 * math.cos(math.radians(lat)), 110540.0
    best, best_conf = float("inf"), ""
    for ax, ay, cx, cy, conf in segs:
        if abs(ax - lon) > 0.3 or abs(ay - lat) > 0.3:
            continue
        px, py = (lon - ax) * kx, (lat - ay) * ky
        vx, vy = (cx - ax) * kx, (cy - ay) * ky
        l2 = vx * vx + vy * vy
        t = max(0.0, min(1.0, (px * vx + py * vy) / l2)) if l2 else 0.0
        d = math.hypot(px - t * vx, py - t * vy)
        if d < best:
            best, best_conf = d, conf
    return best, best_conf


def main() -> None:
    coast = _segments(ASSETS / "coastline.geojson")
    tidal = _segments(ASSETS / "tidal.geojson")
    print(f"coastline segments {len(coast):,}   tidal segments {len(tidal):,}\n")
    for addr, expect in CASES:
        try:
            lat, lon = geocode(addr)
        except Exception as e:                      # noqa: BLE001 — a bad geocode is not fatal here
            print(f"{addr}\n   GEOCODE FAILED: {e}\n")
            continue
        dc, _ = nearest(lat, lon, coast)
        dt, conf = nearest(lat, lon, tidal)
        f = 3.28084
        print(f"{addr}")
        print(f"   expected: {expect}")
        print(f"   coastline {dc * f:>9,.0f} ft ({dc * f / 5280:.2f} mi)")
        print(f"   tidal     {dt * f:>9,.0f} ft ({dt * f / 5280:.2f} mi)   confidence={conf or '—'}")
        print()
        time.sleep(1.1)                             # Nominatim asks for <=1 req/sec

    # --- assertions: this script must be able to FAIL a build, not just print for eyeballing ---
    failures = []
    # Measure the TAGGED layer specifically. Asking for the globally nearest segment is vacuous:
    # inferred reaches outnumber tagged 3,480 to 159, so the nearest is almost always inferred and
    # the pin passes while verdict-moving tagged water sits just behind it.
    tagged_only = [s for s in tidal if s[4] == "tagged"]
    print(f"\n{len(tagged_only):,} tagged segments of {len(tidal):,} — pins measure tagged ONLY\n")
    for (lat, lon), why in NEVER_TAGGED_NEAR:
        dt, _ = nearest(lat, lon, tagged_only)
        ft = dt * 3.28084
        verdict = "ok" if ft > 5280 else "FAIL"
        print(f"[{verdict}] never-tagged pin: {why}\n"
              f"        nearest TAGGED water {ft:,.0f} ft")
        if verdict == "FAIL":
            failures.append(f"{why}: TAGGED water {ft:,.0f} ft away would move a verdict")

    dc_far, _ = nearest(26.1876, -81.6431, coast)
    print(f"\n(Golden Gate Estates is {dc_far * 3.28084 / 5280:.1f} mi from open salt water)")
    if failures:
        print("\nFAILURES:")
        for f_ in failures:
            print("  -", f_)
        raise SystemExit(1)
    print("\nall pins pass")


if __name__ == "__main__":
    main()
