#!/usr/bin/env python3
"""Cache measured salinity for the warranty tool's tidal layer (W1, gauge anchoring).

Jon approved gauge anchoring 2026-07-31. This is step 1.1: pull the readings ONCE at build time so
the plugin never calls anything at runtime, and so we hit USGS on a schedule we control rather than
once per homeowner.

SOURCE. USGS NWIS instantaneous values, parameter 00095 (specific conductance, uS/cm at 25C) — free,
keyless, documented. 64 active gauges inside the South Florida bbox at time of writing.

WHY A WINDOW AND NOT A SPOT READING. Conductance swings with tide, season and rainfall, so a single
instantaneous value can call a reach fresh at low tide and saline six hours later. We keep 30 days
and store the median, the max, the latest, and the sample count — the median is what classifies, the
max is what a cautious estimator may want to see, and the count is how much to trust either.

UPSTREAM MANNERS. One request per 25-site chunk with a pause between, a descriptive User-Agent, and
a cache on disk so a rebuild does not re-hit the service. USGS asks for exactly this.

Usage:
    .venv/bin/python scripts/fetch_salinity_readings.py            # refresh the cache
    .venv/bin/python scripts/fetch_salinity_readings.py --summary  # print what is cached
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CACHE = Path.home() / "perkins-corpus/osm/salinity-readings.json"
BBOX = (24.40, -82.60, 27.70, -79.90)          # south, west, north, east — matches the tidal layer
WINDOW_DAYS = 30
CHUNK = 25                                      # NWIS caps the site list per request
PAUSE_S = 1.0
UA = "perkins-warranty-tool/1.0 (build-time salinity cache; contact jon@degenito.ai)"

SITES_URL = ("https://waterservices.usgs.gov/nwis/site/?format=rdb&stateCd=fl"
             "&parameterCd=00095&siteType=ST,ES,SP&hasDataTypeCd=iv&siteStatus=active")
IV_URL = ("https://waterservices.usgs.gov/nwis/iv/?format=json&sites={sites}"
          "&parameterCd=00095&startDT={start}&endDT={end}")

FRESH_MAX = 1500.0        # uS/cm — ~250 mg/L chloride, the same line SFWMD's isochlor draws
SALINE_MIN = 30000.0      # seawater is ~50,000


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 3:
                raise
            print(f"    retry {attempt} after {e}", flush=True)
            time.sleep(5 * attempt)
    raise RuntimeError("unreachable")


def classify(us_cm: float) -> str:
    if us_cm >= SALINE_MIN:
        return "saline"
    if us_cm >= FRESH_MAX:
        return "brackish"
    return "fresh"


def sites() -> list[dict]:
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
            out.append({"id": r[ix["site_no"]], "name": r[ix["station_nm"]].strip(),
                        "lat": lat, "lon": lon})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", action="store_true", help="print the cache instead of refreshing")
    args = ap.parse_args()

    if args.summary:
        if not CACHE.exists():
            raise SystemExit(f"no cache at {CACHE}")
        d = json.loads(CACHE.read_text())
        g = d["gauges"]
        by = {}
        for x in g.values():
            by[classify(x["median_us_cm"])] = by.get(classify(x["median_us_cm"]), 0) + 1
        print(f"cached {d['fetched_at']}  window {d['window_days']}d  {len(g)} gauges")
        print("  by class:", ", ".join(f"{k}={v}" for k, v in sorted(by.items())))
        for x in sorted(g.values(), key=lambda x: -x["median_us_cm"])[:8]:
            print(f"  {x['name'][:52]:<54}{x['median_us_cm']:>9,.0f} uS/cm  "
                  f"{classify(x['median_us_cm']):<9} n={x['samples']}")
        return

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=WINDOW_DAYS)
    gs = sites()
    print(f"{len(gs)} active conductance gauges in the bbox; pulling {WINDOW_DAYS}d of readings",
          flush=True)

    out: dict[str, dict] = {}
    ids = [g["id"] for g in gs]
    meta = {g["id"]: g for g in gs}
    for i in range(0, len(ids), CHUNK):
        chunk = ids[i:i + CHUNK]
        url = IV_URL.format(sites=",".join(chunk),
                            start=start.strftime("%Y-%m-%dT%H:%MZ"),
                            end=end.strftime("%Y-%m-%dT%H:%MZ"))
        d = json.loads(_get(url))
        for s in d["value"]["timeSeries"]:
            sid = s["sourceInfo"]["siteCode"][0]["value"]
            vals = [float(p["value"]) for p in s["values"][0]["value"]
                    if p.get("value") not in (None, "") and float(p["value"]) > 0]
            if not vals:
                continue
            m = meta.get(sid, {})
            out[sid] = {
                "id": sid, "name": m.get("name", sid),
                "lat": m.get("lat"), "lon": m.get("lon"),
                "median_us_cm": round(st.median(vals), 1),
                "max_us_cm": round(max(vals), 1),
                "latest_us_cm": round(vals[-1], 1),
                "samples": len(vals),
                "latest_at": s["values"][0]["value"][-1]["dateTime"],
            }
        print(f"  {min(i + CHUNK, len(ids))}/{len(ids)} sites", flush=True)
        time.sleep(PAUSE_S)

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({
        "fetched_at": end.isoformat(timespec="seconds"),
        "window_days": WINDOW_DAYS, "bbox": BBOX,
        "parameter": "00095 specific conductance uS/cm at 25C",
        "source": "USGS NWIS instantaneous values",
        "_note": ("median classifies; max is the cautious read; a reading older than the window "
                  "must degrade from 'measured' to 'mapped' in the build."),
        "gauges": out,
    }, indent=1))
    fresh = sum(1 for x in out.values() if classify(x["median_us_cm"]) == "fresh")
    print(f"cached {len(out)} gauges -> {CACHE}  ({fresh} fresh, {len(out) - fresh} salt/brackish)")


if __name__ == "__main__":
    main()
