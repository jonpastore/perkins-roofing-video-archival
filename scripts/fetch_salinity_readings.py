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

SWEEP, NOT PER-QUERY. Jon, 2026-07-31: "poll all of the data from all sensors every day and build
the cache to hit and not do this per query. spread out the requests over the day." So `--slice i/n`
walks a fraction of the stations and MERGES into the cache; run hourly with n=24 and every station
is refreshed daily at a flat few-requests-an-hour load. A slice that fails leaves yesterday's value
in place rather than blanking the reach.

Usage:
    .venv/bin/python scripts/fetch_salinity_readings.py              # every station, one pass
    .venv/bin/python scripts/fetch_salinity_readings.py --slice 3/24 # the scheduled hourly slice
    .venv/bin/python scripts/fetch_salinity_readings.py --summary    # print what is cached
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
# Same service, latest-value mode. About half the gauges carry a current reading but no series for
# the window; they are disproportionately the ones we need (Loxahatchee among them), so they get
# recorded with samples=1 and are marked lower confidence rather than dropped.
IV_LATEST_URL = ("https://waterservices.usgs.gov/nwis/iv/?format=json&sites={sites}"
                 "&parameterCd=00095&siteStatus=active")

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
    ap.add_argument("--slice", help="i/n — refresh only the i-th of n slices and merge (0-indexed)")
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
    meta = {g["id"]: g for g in gs}
    ids = [g["id"] for g in gs]

    # --slice i/n takes a deterministic fraction (sorted, strided) so consecutive runs cover
    # different stations and the whole set is refreshed once per n runs.
    slice_label = "all"
    if args.slice:
        i_s, n_s = args.slice.split("/")
        i_s, n_s = int(i_s), int(n_s)
        if not 0 <= i_s < n_s:
            raise SystemExit(f"--slice {args.slice}: need 0 <= i < n")
        ids = sorted(ids)[i_s::n_s]
        slice_label = f"slice {i_s}/{n_s}"
    print(f"{len(gs)} gauges in the bbox; refreshing {len(ids)} ({slice_label}), "
          f"{WINDOW_DAYS}d window", flush=True)

    # Merge, never blank: a station not in this slice, or one whose request failed, keeps the
    # reading it already had.
    out: dict[str, dict] = {}
    if CACHE.exists():
        try:
            out = json.loads(CACHE.read_text()).get("gauges", {})
        except json.JSONDecodeError:
            out = {}

    def record(sid: str, vals: list[float], latest_at: str, windowed: bool) -> None:
        m = meta.get(sid, {})
        out[sid] = {
            "id": sid, "name": m.get("name", sid),
            "lat": m.get("lat"), "lon": m.get("lon"),
            "median_us_cm": round(st.median(vals), 1),
            "max_us_cm": round(max(vals), 1),
            "latest_us_cm": round(vals[-1], 1),
            "samples": len(vals),
            "windowed": windowed,
            "latest_at": latest_at,
            "refreshed_at": end.isoformat(timespec="seconds"),
        }

    def series_from(url: str) -> dict[str, tuple[list[float], str]]:
        d = json.loads(_get(url))
        got: dict[str, tuple[list[float], str]] = {}
        for s in d["value"]["timeSeries"]:
            sid = s["sourceInfo"]["siteCode"][0]["value"]
            pts = s["values"][0]["value"]
            vals = [float(pt["value"]) for pt in pts
                    if pt.get("value") not in (None, "") and float(pt["value"]) > 0]
            if vals:
                got[sid] = (vals, pts[-1]["dateTime"])
        return got

    missing: list[str] = []
    for i in range(0, len(ids), CHUNK):
        chunk = ids[i:i + CHUNK]
        try:
            got = series_from(IV_URL.format(
                sites=",".join(chunk),
                start=start.strftime("%Y-%m-%dT%H:%MZ"),
                end=end.strftime("%Y-%m-%dT%H:%MZ")))
        except Exception as e:                       # noqa: BLE001 — keep yesterday's values
            print(f"    chunk failed, leaving previous values: {e}", flush=True)
            time.sleep(PAUSE_S)
            continue
        for sid, (vals, at) in got.items():
            record(sid, vals, at, windowed=True)
        missing.extend(s for s in chunk if s not in got)
        print(f"  {min(i + CHUNK, len(ids))}/{len(ids)} sites", flush=True)
        time.sleep(PAUSE_S)

    # Second pass for stations with a current reading but no series in the window. Dropping them
    # would silently measure only the easy half — Loxahatchee at Jupiter is one of these.
    if missing:
        print(f"  {len(missing)} with no windowed series; asking for their latest value", flush=True)
        for i in range(0, len(missing), CHUNK):
            chunk = missing[i:i + CHUNK]
            try:
                got = series_from(IV_LATEST_URL.format(sites=",".join(chunk)))
            except Exception as e:                   # noqa: BLE001
                print(f"    latest-value chunk failed: {e}", flush=True)
                time.sleep(PAUSE_S)
                continue
            for sid, (vals, at) in got.items():
                record(sid, vals, at, windowed=False)
            time.sleep(PAUSE_S)

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({
        "fetched_at": end.isoformat(timespec="seconds"),
        "window_days": WINDOW_DAYS, "bbox": BBOX,
        "parameter": "00095 specific conductance uS/cm at 25C",
        "source": "USGS NWIS instantaneous values",
        "_note": ("median classifies; max is the cautious read; windowed=false means a single "
                  "latest value, which the build must treat as lower confidence. A reading older "
                  "than the window degrades from 'measured' to 'mapped'."),
        "gauges": out,
    }, indent=1))
    fresh = sum(1 for x in out.values() if classify(x["median_us_cm"]) == "fresh")
    win = sum(1 for x in out.values() if x.get("windowed"))
    print(f"cache now holds {len(out)} gauges ({win} windowed, {len(out) - win} latest-only) -> "
          f"{CACHE}  ({fresh} fresh, {len(out) - fresh} salt/brackish)")



if __name__ == "__main__":
    main()
