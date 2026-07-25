#!/usr/bin/env python3
"""Run Tim's 30 real homes (TIME LEARNING email, 2026-07-24) through the estimator.

Source of truth: `Residential OH Calculator (SLOPED ONLY).xlsx` — for each home Tim gives the
existing roof, sloped squares, and his own DAY estimate for demo + each possible new material.

Compares, per home:
  * engine total in per-square OH mode (the current default)
  * engine total with day-based OH fed TIM'S OWN DAYS (demo + like-for-like install)
  * the flat catalog $/sq for the system

Like-for-like re-roof is assumed (tile→tile, shingle→shingle, metal→metal): Tim's sheet prices
every option, and re-roofing in the same material is the common case. All addresses are Palm
Beach / Martin / St. Lucie county → FBC (HVHZ is Miami-Dade + Broward only), jupiter branch.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/validate_against_tim_30_homes.py
"""
from __future__ import annotations

import os
from pathlib import Path

import openpyxl
from sqlalchemy import create_engine, text

from core.estimator import DailyOverheadSeries, QuoteInput, estimate
from core.perkins_packages import _ROOF_TYPE_SYSTEM, sell_price_per_sq
from core.pricing_config import load_config

XLSX = Path.home() / "perkins-corpus/roofr-attachments" / (
    "2026-07-24__Re_TIME_LEARNING_Overhead_for_AI_Systems__Residential_OH_Calculator_SLOPED_ONLY_.xlsx")

# Tim's "Existing Roof" -> the roof_type we quote like-for-like, and his day column for it.
LIKE_FOR_LIKE = {
    "tile":    ("13_tile", "tile_days"),
    "shingle": ("dimensional_shingle", "shingle_days"),
    "metal":   ("standing_seam_metal", "metal_days"),
}
# Which daily_overhead_rates series each install maps to.
INSTALL_SERIES = {"13_tile": "tile", "dimensional_shingle": "shingle", "standing_seam_metal": "metal"}


def load_homes() -> list[dict]:
    ws = openpyxl.load_workbook(XLSX, data_only=True)["Sheet1"]
    rows = ws.iter_rows(min_row=2, values_only=True)
    homes = []
    for r in rows:
        if not r or not r[0]:
            continue
        homes.append({
            "address": str(r[0]).strip(), "city": str(r[1] or "").strip(),
            "existing": str(r[4] or "").strip().lower(),
            "sloped_sq": float(r[5] or 0), "flat_sq": float(r[6] or 0),
            "demo_days": float(r[7] or 0), "shingle_days": float(r[8] or 0),
            "tile_days": float(r[9] or 0), "metal_days": float(r[10] or 0),
        })
    return homes


def half(x: float) -> float:
    """Round to the 0.5 the DailyOverheadSeries contract requires."""
    return max(0.5, round(x * 2) / 2)


def main() -> None:
    eng = create_engine(os.environ["DB_URL"])
    with eng.connect() as c:
        c.execute(text("SET app.tenant_id='1'"))
        cfg = load_config(c.execute(text(
            "select config from pricing_configs where is_active and branch='jupiter'")).scalar())
    rates = cfg.daily_overhead_rates()

    homes = load_homes()
    print(f"{len(homes)} homes from Tim's calculator (FBC, jupiter branch, like-for-like re-roof)\n")
    hdr = (f"{'address':<26}{'exist':<8}{'SQ':>6}{'roof':<20}"
           f"{'engine/sq':>10}{'TimOH/sq':>10}{'engine(Tim d)':>14}{'catalog/sq':>11}{'cat vs eng':>11}")
    print(hdr); print("-" * len(hdr))

    agg = {"eng": 0.0, "tim": 0.0, "cat": 0.0, "n": 0}
    per_type: dict[str, list[float]] = {}
    for h in homes:
        if h["existing"] not in LIKE_FOR_LIKE or h["sloped_sq"] <= 0:
            print(f"{h['address'][:25]:<26}{h['existing']:<8}{h['sloped_sq']:>6.1f}  SKIPPED (no like-for-like mapping)")
            continue
        rt, day_col = LIKE_FOR_LIKE[h["existing"]]
        sq = h["sloped_sq"]
        base = dict(code_zone="FBC", county="palm_beach", roof_type=rt, num_squares=sq,
                    project_kind="residential", demo=True, existing_roof=h["existing"])

        r_persq = estimate(cfg, QuoteInput(**base))
        eng_per_sq = r_persq["project_total"] / sq

        # Tim's OWN days for this home: demo + like-for-like install.
        series = [DailyOverheadSeries(series="demo_dry_in_flat", days=half(h["demo_days"]))] if h["demo_days"] else []
        if h[day_col]:
            series.append(DailyOverheadSeries(series=INSTALL_SERIES[rt], days=half(h[day_col])))
        tim_oh_total = sum(s.days * float(rates[s.series]) for s in series)
        r_tim = estimate(cfg, QuoteInput(**base, overhead_mode="daily", daily_series=series))
        tim_per_sq = r_tim["project_total"] / sq

        cat = float(sell_price_per_sq(_ROOF_TYPE_SYSTEM[rt], "PROTECTOR"))
        print(f"{h['address'][:25]:<26}{h['existing']:<8}{sq:>6.1f}{rt:<20}"
              f"{eng_per_sq:>10.0f}{tim_oh_total/sq:>10.0f}{tim_per_sq:>14.0f}{cat:>11.0f}"
              f"{cat-eng_per_sq:>+11.0f}")
        agg["eng"] += eng_per_sq; agg["tim"] += tim_per_sq; agg["cat"] += cat; agg["n"] += 1
        per_type.setdefault(rt, []).append(cat - eng_per_sq)

    n = agg["n"]
    print("-" * len(hdr))
    print(f"{'MEAN $/sq':<60}{agg['eng']/n:>10.0f}{'':>10}{agg['tim']/n:>14.0f}"
          f"{agg['cat']/n:>11.0f}{(agg['cat']-agg['eng'])/n:>+11.0f}")
    print("\nCatalog minus engine, by roof type (negative = catalog under-quotes Tim's build):")
    for rt, deltas in sorted(per_type.items()):
        print(f"  {rt:<22} n={len(deltas):<3} mean {sum(deltas)/len(deltas):>+8.0f}/sq  "
              f"worst {min(deltas):>+8.0f}/sq")

    # Does Tim's day data support days = SQ/rate (his OH Metrics model) or setup + rate*SQ?
    print("\nDay-model check against Tim's own numbers (least squares over these homes):")
    for label, col, rt in (("demo", "demo_days", None), ("tile", "tile_days", "13_tile"),
                           ("shingle", "shingle_days", "dimensional_shingle"),
                           ("metal", "metal_days", "standing_seam_metal")):
        pts = [(h["sloped_sq"], h[col]) for h in homes if h["sloped_sq"] > 0 and h[col]]
        if len(pts) < 3:
            continue
        n2 = len(pts); sx = sum(p[0] for p in pts); sy = sum(p[1] for p in pts)
        sxx = sum(p[0] ** 2 for p in pts); sxy = sum(p[0] * p[1] for p in pts)
        denom = n2 * sxx - sx * sx
        slope = (n2 * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / n2
        # no-intercept fit (Tim's OH Metrics shape: days = SQ / squares_per_day)
        rate_only = sxy / sxx
        ybar = sy / n2
        sst = sum((p[1] - ybar) ** 2 for p in pts)
        sse_a = sum((p[1] - (intercept + slope * p[0])) ** 2 for p in pts)
        sse_b = sum((p[1] - rate_only * p[0]) ** 2 for p in pts)
        print(f"  {label:<9} n={n2:<3} setup+rate: {intercept:+.2f} + {slope:.4f}/SQ  R2={1-sse_a/sst:.3f}"
              f"   |  rate-only: {rate_only:.4f}/SQ ({1/rate_only:.1f} SQ/day)  R2={1-sse_b/sst:.3f}")


if __name__ == "__main__":
    main()
