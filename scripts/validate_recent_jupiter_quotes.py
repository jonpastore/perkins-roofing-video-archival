#!/usr/bin/env python3
"""Validate the overhead models on RECENT pricing only — Jupiter, accepted, last 3 months.

Jon, 2026-07-30: "we should only look at recent pricing in the last 2-3 months so vintage
pricing doesn't skew the numbers."

Every ACCEPTED (BusinessState="Open") per-square roof line in Tim's Jupiter Knowify tenant
(30586/28403) dated 2026-05-01 or later, pulled via the Knowify MCP on 2026-07-30. Tier lines
(PREFERRED / PREMIUM / COASTAL) are UPCHARGE DELTAS on the PROTECTOR base for the same squares
and are excluded; so are "(OPTIONAL)" add-ons and $0 menu options.

Days are DERIVED by the shipped model, not taken from Tim — these ten jobs have no RoofR cut
measurements, so this is exactly the path production takes when a quote is built from squares
alone. That makes it a harder and more honest test than the 30-home set.

Five of these ten also appear in Tim's 30-home day-count sheet at the same price (503 Xanadu,
104 Via Veracruz, 309 Palm Trail, 113 Coventry, 1141 Vintner), which is what ties the two
datasets together.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/validate_recent_jupiter_quotes.py
"""
from __future__ import annotations

import os
import statistics as st

from sqlalchemy import create_engine, text

from core.estimator import QuoteInput, derive_daily_series, estimate
from core.pricing_config import load_config

# (contract, sold, roof bucket, squares, charged $, note)
JOBS = [
    (5191571, "2026-05-14", "tile", 76.0, 94_460.00, "309 Palm Trail"),
    (5262477, "2026-06-04", "metal", 45.0, 55_600.00, "113 Coventry (DISCOUNTED line)"),
    (5266911, "2026-06-05", "metal", 9.0, 13_985.00, ""),
    (5268422, "2026-06-07", "shingle", 40.0, 28_180.73, ""),
    (5301409, "2026-06-16", "shingle", 30.0, 22_840.47, "flat + copper billed separately"),
    (5312523, "2026-06-18", "tile", 43.5, 49_698.00, "104 Via Veracruz"),
    (5338362, "2026-06-26", "metal", 26.0, 38_380.00, "503 Xanadu"),
    (5411711, "2026-07-17", "tile", 39.0, 51_950.00, "1141 Vintner"),
    (5412688, "2026-07-17", "metal", 29.0, 37_735.00, ""),
    # 5216592 (2026-05-21, $22,430) is a single "Shingle and Flat Re-Roof" line: the sloped and
    # low-slope scopes are not separable from it, so it cannot be scored. Counted as a miss.
]
ROOF_TYPE = {"tile": "13_tile", "shingle": "dimensional_shingle", "metal": "standing_seam_metal"}


def main() -> None:
    eng = create_engine(os.environ["DB_URL"])
    with eng.connect() as c:
        c.execute(text("set app.tenant_id='1'"))
        raw = c.execute(text(
            "select config from pricing_configs where is_active and branch='jupiter'")).scalar()
    cfg = load_config(raw)
    # crew-share = the model Tim's OWN Jupiter tab uses: (office / men) x crew size, with his
    # tab's crew sizes (3 on every install, 5 on demo/dry-in). $200 = 1,400/7 is the basis printed
    # on that tab; $210 = 1,470/7 is his current stated burn over the same 7 men.
    def _crew(per_man: float) -> dict:
        return {"tile": 3 * per_man, "shingle": 3 * per_man, "metal": 3 * per_man,
                "demo_dry_in_flat": 5 * per_man}
    variants = {
        "per_sq": (cfg, "per_sq"),
        "day-branch": (load_config({**raw, "overhead_basis": "branch",
                                    "office_daily_overhead": 1400}), "daily"),
        "day-series": (load_config({**raw, "overhead_basis": "series"}), "daily"),
        "crew@200": (load_config({**raw, "overhead_basis": "series",
                                  "daily_overhead_rates": _crew(200.0)}), "daily"),
        "crew@210": (load_config({**raw, "overhead_basis": "series",
                                  "daily_overhead_rates": _crew(210.0)}), "daily"),
    }

    print(f"{len(JOBS)} accepted Jupiter jobs, 2026-05-01 .. 2026-07-30, days DERIVED\n")
    hdr = (f"{'sold':12}{'roof':9}{'SQ':>6}{'days':>6}{'charged':>11}"
           + "".join(f"{m:>13}" for m in variants) + "   note")
    print(hdr)
    print("-" * len(hdr))
    errs: dict[str, list[float]] = {m: [] for m in variants}
    for _cid, sold, bucket, sq, charged, note in JOBS:
        q = QuoteInput(code_zone="FBC", county="palm_beach", slope_type="sloped",
                       roof_type=ROOF_TYPE[bucket], num_squares=sq, project_kind="residential",
                       demo=True, existing_roof=bucket)
        days = sum(s.days for s in derive_daily_series(cfg, q))
        cells = []
        for name, (cfg_v, mode) in variants.items():
            series = derive_daily_series(cfg_v, q) if mode == "daily" else []
            total = estimate(cfg_v, QuoteInput(**{**q.__dict__, "overhead_mode": mode,
                                                  "daily_series": series}))["project_total"]
            e = total / charged - 1
            errs[name].append(e)
            cells.append(f"{100 * e:>12.1f}%")
        print(f"{sold:12}{bucket:9}{sq:>6.1f}{days:>6.1f}{charged:>11,.0f}"
              + "".join(cells) + f"   {note}")

    print("-" * len(hdr))
    print(f"\n{'model':14}{'within 5%':>11}{'within 10%':>12}{'median':>10}{'median abs':>12}")
    for name, e in errs.items():
        print(f"{name:14}{sum(1 for x in e if abs(x) <= 0.05):>8}/{len(e):<3}"
              f"{sum(1 for x in e if abs(x) <= 0.10):>9}/{len(e):<3}"
              f"{100 * st.median(e):>9.1f}%{100 * st.median([abs(x) for x in e]):>11.1f}%")
    print("\nn=9 scoreable (a tenth job bundles sloped and flat on one line and cannot be split).")
    print("Days are derived from squares alone here — no cut geometry — so this is the floor of")
    print("what the day models do, not their ceiling.")

    # WHY the ranking here disagrees with the 30-home run: there the days were TIM'S, here they
    # are DERIVED. Overhead is rate x days, so an error in one is absorbed by the other. On the
    # five jobs that appear in both datasets we can see it directly.
    print("\n" + "=" * 78)
    print("DERIVED DAYS vs TIM'S OWN DAYS, on the five jobs that appear in both datasets")
    print("=" * 78)
    matched = {
        94_460.00: ("tile", 76.0, 5.5 + 13.0), 55_600.00: ("metal", 45.0, 3.5 + 4.5),
        49_698.00: ("tile", 43.5, 3.5 + 6.0), 38_380.00: ("metal", 26.0, 3.0 + 4.0),
        51_950.00: ("tile", 39.0, 4.0 + 6.0),
    }
    print(f"{'roof':9}{'SQ':>6}{'derived':>9}{'Tim':>7}{'gap':>8}"
          f"{'day-series @derived':>21}{'day-series @Tim':>18}")
    gaps, e_der, e_tim = [], [], []
    for _cid, _sold, bucket, sq, charged, _note in JOBS:
        if charged not in matched:
            continue
        tim_days = matched[charged][2]
        q = QuoteInput(code_zone="FBC", county="palm_beach", slope_type="sloped",
                       roof_type=ROOF_TYPE[bucket], num_squares=sq, project_kind="residential",
                       demo=True, existing_roof=bucket)
        cfg_s = variants["day-series"][0]
        der = derive_daily_series(cfg_s, q)
        d_der = sum(s.days for s in der)
        scaled = [type(s)(series=s.series, days=max(0.5, round(s.days * tim_days / d_der * 2) / 2))
                  for s in der]
        a = estimate(cfg_s, QuoteInput(**{**q.__dict__, "overhead_mode": "daily",
                                          "daily_series": der}))["project_total"] / charged - 1
        b = estimate(cfg_s, QuoteInput(**{**q.__dict__, "overhead_mode": "daily",
                                          "daily_series": scaled}))["project_total"] / charged - 1
        gaps.append(d_der / tim_days - 1)
        e_der.append(a)
        e_tim.append(b)
        print(f"{bucket:9}{sq:>6.1f}{d_der:>9.1f}{tim_days:>7.1f}{100 * (d_der / tim_days - 1):>7.0f}%"
              f"{100 * a:>20.1f}%{100 * b:>17.1f}%")
    print(f"\n  the day model under-counts Tim's own days by a median "
          f"{-100 * st.median(gaps):.0f}%, and feeding his days moves the SAME rate model from "
          f"{100 * st.median(e_der):+.1f}% to {100 * st.median(e_tim):+.1f}%.")
    print("  Overhead is rate x days. Getting the days wrong and the rate wrong in opposite")
    print("  directions lands on the right price for the wrong reason — which is exactly what")
    print("  makes the flat $1,400/day look best HERE and worst on Tim's own day counts.")


if __name__ == "__main__":
    main()
