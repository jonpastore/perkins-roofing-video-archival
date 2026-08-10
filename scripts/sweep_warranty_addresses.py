#!/usr/bin/env python3
"""Run every real Perkins customer address through the warranty layer and diff the verdicts.

WHY THIS EXISTS. The layer had two hand-written pin sets — inland addresses that must NOT void,
waterfront addresses that MUST. Pins catch what someone thought to pin. They did not catch 188 Lone
Pine Drive, because nobody had her address until the day Tim sent it, and the stand-in pinned in her
place passed. The population the tool actually runs on is Tim's customer list, so sweep that.

    .venv/bin/python scripts/sweep_warranty_addresses.py --out before.json   # on the old asset
    ... rebuild the layer ...
    .venv/bin/python scripts/sweep_warranty_addresses.py --out after.json --diff before.json

Geocoding is the US Census batch geocoder: free, keyless, no rate limit, and it resolves US street
addresses Nominatim misses. It is NOT the geocoder the live tool uses (Google), so treat a
single-address disagreement as geocoder noise and the aggregate as the signal.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
ASSETS = ROOT / "wp-plugin/perkins-metal-warranty/assets"
CENSUS = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
CENSUS_CHUNK = 1000        # the service accepts 10k per file; 1k keeps a retry cheap
FT_PER_M = 3.28084


def clients() -> list[dict]:
    """Every client with an address, via the Knowify MCP token Claude Code already holds."""
    sys.path.insert(0, str(ROOT / "scripts/knowify"))
    from mcp_pull import MCP, _load_token, pull_all  # noqa: E402 — path set above

    m = MCP(_load_token())
    m.initialize()
    rows = pull_all(m, "Clients",
                    ["Id", "ClientName", "Address1", "City", "StateProvince", "Zip"],
                    where={"ObjectState": {"$in": ["Active", "Inactive"]}})
    return [r for r in rows if (r.get("Address1") or "").strip()]


def _split(row: dict) -> tuple[str, str, str, str] | None:
    """Knowify addresses are free text: half carry City/Zip columns, half stuff the whole thing
    into Address1 ("7369 NW 34th St, Miami, FL, 33122"). Both shapes have to reach the geocoder."""
    a1 = (row.get("Address1") or "").strip().rstrip(",")
    city = (row.get("City") or "").strip().rstrip(",")
    state = (row.get("StateProvince") or "").strip() or "FL"
    zip_ = re.sub(r"\D", "", (row.get("Zip") or ""))[:5]
    if not city and "," in a1:
        parts = [p.strip() for p in a1.split(",") if p.strip()]
        if len(parts) >= 3:
            a1 = parts[0]
            city = parts[1]
            state = parts[2][:2].upper() or "FL"
            if len(parts) >= 4:
                zip_ = re.sub(r"\D", "", parts[3])[:5]
    if not city:
        # "7803 NW 194th St Hialeah, FL 33015" — no comma before the city. Give up rather than
        # guess: a wrong city geocodes to a real place miles away, which is worse than a miss.
        return None
    return a1, city, state, zip_


def geocode(rows: list[dict]) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    todo = [(str(r["Id"]), s) for r in rows if (s := _split(r))]
    print(f"geocoding {len(todo)} of {len(rows)} client addresses "
          f"({len(rows) - len(todo)} unparseable)", flush=True)
    for i in range(0, len(todo), CENSUS_CHUNK):
        chunk = todo[i:i + CENSUS_CHUNK]
        buf = io.StringIO()
        w = csv.writer(buf)
        for cid, (a1, city, state, zip_) in chunk:
            w.writerow([cid, a1, city, state, zip_])
        body, boundary = _multipart(buf.getvalue())
        req = urllib.request.Request(
            CENSUS, data=body, method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                     "User-Agent": "perkins-warranty-tool/1.0 (address sweep)"})
        with urllib.request.urlopen(req, timeout=900) as r:
            text = r.read().decode("utf-8", "replace")
        hit = 0
        for rec in csv.reader(io.StringIO(text)):
            # id, input, match, exact, matched-address, "lon,lat", tiger id, side
            if len(rec) >= 6 and rec[2] == "Match" and "," in rec[5]:
                lon, lat = rec[5].split(",")[:2]
                out[rec[0]] = (float(lat), float(lon))
                hit += 1
        print(f"  batch {i // CENSUS_CHUNK + 1}: {hit}/{len(chunk)} matched", flush=True)
    return out


def _multipart(csv_text: str) -> tuple[bytes, str]:
    b = "----perkinssweep"
    parts = [
        f"--{b}\r\nContent-Disposition: form-data; name=\"addressFile\"; "
        f"filename=\"a.csv\"\r\nContent-Type: text/csv\r\n\r\n{csv_text}\r\n",
        f"--{b}\r\nContent-Disposition: form-data; name=\"benchmark\"\r\n\r\n"
        f"Public_AR_Current\r\n",
        f"--{b}--\r\n"]
    return "".join(parts).encode(), b


def _segments(path: Path, keep=None) -> list[tuple]:
    d = json.loads(path.read_text())
    geoms = d["geometries"] if d.get("type") == "GeometryCollection" else [
        f["geometry"] for f in d["features"]]
    segs = []
    for g in geoms:
        conf = g.get("confidence", "coast")
        if keep is not None and conf not in keep:
            continue
        name = (g.get("wbid") or {}).get("name")
        c = g["coordinates"]
        for i in range(len(c) - 1):
            segs.append((c[i][0], c[i][1], c[i + 1][0], c[i + 1][1], conf, name))
    return segs


def nearest(lat: float, lon: float, segs: list[tuple]) -> tuple[float, str, str]:
    """Point-to-SEGMENT, the same quantity checker.js measures. Not point-to-vertex."""
    kx, ky = 111320.0 * math.cos(math.radians(lat)), 110540.0
    best, conf, name = float("inf"), "", None
    for ax, ay, cx, cy, c, n in segs:
        if abs(ax - lon) > 0.3 or abs(ay - lat) > 0.3:
            continue
        px, py = (lon - ax) * kx, (lat - ay) * ky
        vx, vy = (cx - ax) * kx, (cy - ay) * ky
        l2 = vx * vx + vy * vy
        t = max(0.0, min(1.0, (px * vx + py * vy) / l2)) if l2 else 0.0
        d = math.hypot(px - t * vx, py - t * vy)
        if d < best:
            best, conf, name = d, c, n
    return best, conf, name


def verdicts(ft: float, zones: dict) -> dict[str, str]:
    """checker.js verdictFor, per material: the worst state any manufacturer gives."""
    out = {}
    for m in zones["materials"]:
        state = "ok"
        for p in m["provisions"]:
            if p.get("void_within_ft") is not None and ft < p["void_within_ft"]:
                state = "void"
                break
            if p.get("conditional_within_ft") is not None and ft < p["conditional_within_ft"]:
                state = "cond"
        out[m["name"]] = state
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="write results here")
    ap.add_argument("--diff", help="a previous --out file to compare against")
    ap.add_argument("--geocache", default=str(Path.home() / "perkins-corpus/knowify/geocoded.json"),
                    help="reuse geocodes so a re-run costs nothing and compares like with like")
    a = ap.parse_args()

    cache = Path(a.geocache)
    rows = clients()
    if cache.exists():
        geo = {k: tuple(v) for k, v in json.loads(cache.read_text()).items()}
        print(f"reusing {len(geo)} cached geocodes from {cache}", flush=True)
    else:
        geo = geocode(rows)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({k: list(v) for k, v in geo.items()}))
        print(f"cached {len(geo)} geocodes -> {cache}", flush=True)

    zones = json.loads((ASSETS / "zones.json").read_text())
    from scripts.build_tidal_layer import VERDICT_MOVING  # noqa: E402 — path set above
    coast = _segments(ASSETS / "coastline.geojson")
    tidal = _segments(ASSETS / "tidal.geojson", keep=set(VERDICT_MOVING))
    print(f"{len(coast):,} coastline segments, {len(tidal):,} verdict-moving tidal segments",
          flush=True)

    results = {}
    for n, r in enumerate(rows, 1):
        p = geo.get(str(r["Id"]))
        if not p:
            continue
        lat, lon = p
        dc, _, _ = nearest(lat, lon, coast)
        dt, conf, name = nearest(lat, lon, tidal)
        m = min(dc, dt)
        if math.isinf(m):
            # No water within the 0.3-degree prefilter — an out-of-state or badly geocoded pin.
            # Dropped rather than recorded as "very far", which would read as a clean warranty-safe.
            continue
        ft = m * FT_PER_M
        results[str(r["Id"])] = {
            "name": r.get("ClientName"), "address": r.get("Address1"), "city": r.get("City"),
            "lat": lat, "lon": lon, "ft": round(ft), "via": "tidal" if dt < dc else "coast",
            "confidence": conf if dt < dc else "coast", "water": name if dt < dc else None,
            "verdicts": verdicts(ft, zones)}
        if n % 250 == 0:
            print(f"  measured {n}/{len(rows)}", flush=True)

    Path(a.out).write_text(json.dumps(results, indent=1))
    steel = [k for k in results
             if any(s == "void" for mat, s in results[k]["verdicts"].items() if "teel" in mat)]
    print(f"\n{len(results):,} customers measured -> {a.out}")
    print(f"  {len(steel):,} have at least one steel product VOID "
          f"({100 * len(steel) / max(len(results), 1):.1f}%)")

    if a.diff:
        old = json.loads(Path(a.diff).read_text())
        changed = []
        for k, v in results.items():
            o = old.get(k)
            if o and o["verdicts"] != v["verdicts"]:
                changed.append((k, o, v))
        # Rank the states, do not count the voids. Counting only `void` transitions reported an
        # ok -> conditional move as "now clear" — the exact opposite of what happened — and printed
        # 54 reassuring lines on a run where every single change was more restrictive.
        rank = {"ok": 0, "cond": 1, "void": 2}
        print(f"\n{len(changed)} customers changed verdict vs {a.diff}:")
        for k, o, v in sorted(changed, key=lambda c: c[2]["ft"]):
            deltas = [rank[v["verdicts"][m]] - rank[o["verdicts"][m]] for m in v["verdicts"]]
            label = ("STRICTER" if all(d >= 0 for d in deltas)
                     else "looser" if all(d <= 0 for d in deltas) else "MIXED")
            worst = max(v["verdicts"].values(), key=lambda s: rank[s])
            print(f"  [{label}/{worst}] {v['name']} — {v['address']}, "
                  f"{v['city']}: {o['ft']:,} ft -> {v['ft']:,} ft ({v['confidence']}, {v['water']})")
        looser = [c for c in changed
                  if any(rank[c[2]["verdicts"][m]] < rank[c[1]["verdicts"][m]] for m in
                         c[2]["verdicts"])]
        # Adding water can only ever bring the nearest water CLOSER. A looser verdict means
        # geometry was removed, which is the false-CLEAR direction and must be explained, not
        # skimmed past.
        print(f"\n{len(looser)} customers got a LOOSER verdict — each one needs a reason "
              f"(geometry that used to be there is gone)")


if __name__ == "__main__":
    main()
