#!/usr/bin/env python3
"""Score the tidal layer against MEASURED salinity — USGS real-time gauges.

Jon, 2026-07-31: "research how we can identify water sources that are brackish more definitively.
validate our data sources to be more accurate. can we publish a confidence rate on the results?"

Until now the layer was reasoned about (canals are tidal seaward of a control structure) and spot
-checked against addresses we could argue about. This checks it against instruments.

SOURCE. USGS NWIS instantaneous values, parameter 00095 (specific conductance, uS/cm at 25C) —
a free, keyless, documented REST API with ~67 active gauges inside the South Florida bbox.
Conductance is the standard field proxy for salinity:

    < 1,500 uS/cm     fresh        (~250 mg/L chloride, the drinking-water / isochlor line)
    1,500 - 30,000    brackish
    > 30,000          saline       (seawater is ~50,000)

Manufacturer warranties say "seacoast, salt or brackish water", so anything at or above the
brackish line is water their exclusions are written about.

WHAT IT PROVES. Each gauge sits ON a waterway. If our layer marks that waterway as salt-carrying,
the gauge should read brackish or saline; if we leave it out, the gauge should read fresh. Every
disagreement is a real error with a measured magnitude, and the agreement rate is a confidence
number we can publish rather than assert.

Usage: .venv/bin/python scripts/validate_tidal_against_gauges.py
"""
from __future__ import annotations

import json
import math
import urllib.request
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "wp-plugin/perkins-metal-warranty/assets"
BBOX = (24.30, -87.80, 31.10, -79.80)          # south, west, north, east — matches the tidal layer
FRESH_MAX = 1500.0                              # uS/cm
SALINE_MIN = 30000.0
ON_WATER_M = 250.0                              # a gauge this close counts as "on" that reach

SITES_URL = ("https://waterservices.usgs.gov/nwis/site/?format=rdb&stateCd=fl"
             "&parameterCd=00095&siteType=ST,ES,SP&hasDataTypeCd=iv&siteStatus=active")
IV_URL = ("https://waterservices.usgs.gov/nwis/iv/?format=json&sites={sites}"
          "&parameterCd=00095&siteStatus=active")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "perkins-warranty-tool/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def gauges() -> list[dict]:
    rows = [ln.split("\t") for ln in _get(SITES_URL).decode().splitlines()
            if not ln.startswith("#")]
    hdr, data = rows[0], rows[2:]
    ix = {k: hdr.index(k) for k in ("site_no", "station_nm", "dec_lat_va", "dec_long_va")}
    out = []
    for r in data:
        if len(r) <= max(ix.values()) or not r[ix["dec_lat_va"]]:
            continue
        lat, lon = float(r[ix["dec_lat_va"]]), float(r[ix["dec_long_va"]])
        if BBOX[0] <= lat <= BBOX[2] and BBOX[1] <= lon <= BBOX[3]:
            out.append({"id": r[ix["site_no"]], "name": r[ix["station_nm"]],
                        "lat": lat, "lon": lon})
    return out


def readings(ids: list[str]) -> dict[str, float]:
    vals: dict[str, float] = {}
    for i in range(0, len(ids), 25):               # NWIS caps the site list per request
        chunk = ",".join(ids[i:i + 25])
        d = json.loads(_get(IV_URL.format(sites=chunk)))
        for s in d["value"]["timeSeries"]:
            pts = s["values"][0]["value"]
            if not pts:
                continue
            v = float(pts[-1]["value"])
            if v > 0:
                vals[s["sourceInfo"]["siteCode"][0]["value"]] = v
    return vals


def _segments(path: Path, default_conf: str) -> list[tuple]:
    """Segments as (ax, ay, cx, cy, confidence, station) — station is the gauge a `measured`
    reach got its reading from, which is what makes hold-one-out possible without a rebuild."""
    d = json.loads(path.read_text())
    geoms = d["geometries"] if d.get("type") == "GeometryCollection" else [
        f["geometry"] for f in d["features"]]
    segs = []
    for g in geoms:
        conf = g.get("confidence", default_conf)
        m_ = g.get("measurement") or {}
        station, prior = m_.get("station"), m_.get("prior", "inferred")
        c = g["coordinates"]
        for i in range(len(c) - 1):
            segs.append((c[i][0], c[i][1], c[i + 1][0], c[i + 1][1], conf, station, prior))
    return segs


def nearest(lat: float, lon: float, segs: list[tuple]) -> tuple[float, str]:
    kx, ky = 111320.0 * math.cos(math.radians(lat)), 110540.0
    best, conf = float("inf"), ""
    for ax, ay, cx, cy, c, _st, _pr in segs:
        if abs(ax - lon) > 0.05 or abs(ay - lat) > 0.05:
            continue
        px, py = (lon - ax) * kx, (lat - ay) * ky
        vx, vy = (cx - ax) * kx, (cy - ay) * ky
        l2 = vx * vx + vy * vy
        t = max(0.0, min(1.0, (px * vx + py * vy) / l2)) if l2 else 0.0
        d = math.hypot(px - t * vx, py - t * vy)
        if d < best:
            best, conf = d, c
    return best, conf


def main() -> None:
    coast = _segments(ASSETS / "coastline.geojson", "coast")
    tidal = _segments(ASSETS / "tidal.geojson", "inferred")
    tagged = [s for s in tidal if s[4] in ("measured", "tagged")]
    inferred = [s for s in tidal if s[4] == "inferred"]   # "fresh" is deliberately in neither

    gs = gauges()
    vals = readings([g["id"] for g in gs])
    print(f"{len(gs)} USGS conductance gauges in the bbox, {len(vals)} reporting a live value\n")

    # ---- HOLD-ONE-OUT ---------------------------------------------------------------------
    # The layer is now BUILT from these gauges, so scoring it against them in-sample grades the
    # model on its own training data — the same circularity the overhead analysis fell into. For
    # each gauge we therefore ask: with THIS gauge's own reading removed, what would we have said?
    print("HOLD-ONE-OUT — each gauge scored with its own reading excluded\n")
    ho = {"right": 0, "wrong": 0, "by": {}}
    ho_misses = []
    for g in gs:
        v = vals.get(g["id"])
        if v is None:
            continue
        measured_salt = v >= FRESH_MAX
        # Excluding a gauge must REVERT its reaches to what we would have believed without it —
        # deleting them understates our knowledge and makes the score look worse than it is.
        others = [(s[0], s[1], s[2], s[3], (s[6] if s[5] == g["id"] else s[4]), s[5], s[6])
                  for s in tidal]
        oth_tag = [s for s in others if s[4] in ("measured", "tagged")]
        oth_inf = [s for s in others if s[4] == "inferred"]
        dc, _ = nearest(g["lat"], g["lon"], coast)
        dtag, _ = nearest(g["lat"], g["lon"], oth_tag)
        dinf, _ = nearest(g["lat"], g["lon"], oth_inf)
        says_salt = dc <= ON_WATER_M or dtag <= ON_WATER_M
        bucket = ("coast" if dc <= ON_WATER_M else "measured/tagged" if dtag <= ON_WATER_M
                  else "inferred" if dinf <= ON_WATER_M else "none")
        ho["by"].setdefault(bucket, [0, 0])[0 if measured_salt else 1] += 1
        if says_salt == measured_salt:
            ho["right"] += 1
        else:
            ho["wrong"] += 1
            ho_misses.append((g, v, bucket))
    tot_ho = ho["right"] + ho["wrong"]
    print(f"{'without its own gauge':<22}{'reads SALT':>12}{'reads FRESH':>13}")
    for k, (s_, f_) in sorted(ho["by"].items()):
        print(f"{k:<22}{s_:>12}{f_:>13}")
    print(f"\nHELD-OUT AGREEMENT: {ho['right']}/{tot_ho} = {100 * ho['right'] / tot_ho:.0f}%")
    if ho_misses:
        print("  still wrong without their own reading:")
        for g, v, b in sorted(ho_misses, key=lambda m: -m[1])[:8]:
            print(f"    {g['name'][:46]:<48}{v:>9,.0f} uS/cm   we would say: {b}")

    print("\n" + "=" * 78)
    print("IN-SAMPLE (every gauge's own reading available — inflated, shown for contrast)\n")
    stats = {"tagged": [0, 0], "inferred": [0, 0], "coast": [0, 0], "none": [0, 0]}
    misses = []
    for g in gs:
        v = vals.get(g["id"])
        if v is None:
            continue
        measured_salt = v >= FRESH_MAX
        dc, _ = nearest(g["lat"], g["lon"], coast)
        dtag, _ = nearest(g["lat"], g["lon"], tagged)
        dinf, _ = nearest(g["lat"], g["lon"], inferred)
        # what our data says about the water this instrument is standing in
        if dc <= ON_WATER_M:
            says = "coast"
        elif dtag <= ON_WATER_M:
            says = "tagged"
        elif dinf <= ON_WATER_M:
            says = "inferred"
        else:
            says = "none"
        stats[says][0 if measured_salt else 1] += 1
        if (says in ("coast", "tagged")) != measured_salt:
            misses.append((g, v, says))

    print(f"{'our layer says':<14}{'gauge reads SALT':>18}{'gauge reads FRESH':>19}   what it means")
    meaning = {
        "coast": "open salt water in our data",
        "tagged": "OSM-confirmed tidal",
        "inferred": "connectivity guess only",
        "none": "we map no water here",
    }
    for k in ("coast", "tagged", "inferred", "none"):
        salt, fresh = stats[k]
        print(f"{k:<14}{salt:>18}{fresh:>19}   {meaning[k]}")

    verdict_layers = stats["coast"][0] + stats["tagged"][0] + stats["inferred"][1] + stats["none"][1]
    total = sum(sum(v) for v in stats.values())
    print(f"\nAgreement between what we treat as salt water and what the instruments read: "
          f"{verdict_layers}/{total} = {100 * verdict_layers / total:.0f}%")
    print("(counting inferred/none as 'not salt', which is how the tool actually behaves —"
          " inferred never moves a verdict)")

    if misses:
        print("\nDisagreements — each one is a real error, with its measured magnitude:")
        for g, v, says in sorted(misses, key=lambda m: -m[1]):
            cls = "SALINE" if v >= SALINE_MIN else ("brackish" if v >= FRESH_MAX else "fresh")
            print(f"  {g['name'][:50]:<52}{v:>9,.0f} uS/cm  {cls:<9} we say: {says}")


if __name__ == "__main__":
    main()
