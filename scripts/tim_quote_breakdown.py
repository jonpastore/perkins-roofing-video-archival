#!/usr/bin/env python3
"""Per-home breakdown for Tim: our predicted crew-days and quote vs his own numbers.

Feeds the 30 homes from his TIME LEARNING sheet through the estimator with the geometry-driven
day model, using each home's real RoofR cut measurements, and prints:

  * his days (demo + install) vs ours, and the difference
  * the resulting overhead each way
  * our quote total, and what the flat catalog price would have been

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/tim_quote_breakdown.py [--csv out.csv]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import os
from pathlib import Path

from sqlalchemy import create_engine, text

from core.estimator import DailyOverheadSeries, QuoteInput, derive_daily_series, estimate
from core.perkins_packages import _ROOF_TYPE_SYSTEM, sell_price_per_sq
from core.pricing_config import load_config

LIKE_FOR_LIKE = {"tile": ("13_tile", "tile"), "shingle": ("dimensional_shingle", "shingle"),
                 "metal": ("standing_seam_metal", "metal")}
INSTALL_SERIES = {"13_tile": "tile", "dimensional_shingle": "shingle",
                  "standing_seam_metal": "metal"}


def _load_fitter():
    spec = importlib.util.spec_from_file_location(
        "fitmod", Path(__file__).with_name("fit_days_from_roofr.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def half(x: float) -> float:
    return max(0.5, round(x * 2) / 2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="")
    args = ap.parse_args()

    fitter = _load_fitter()
    homes = fitter.load()          # only homes matched to a RoofR report carry geometry

    eng = create_engine(os.environ["DB_URL"])
    with eng.connect() as c:
        c.execute(text("SET app.tenant_id='1'"))
        cfg = load_config(c.execute(text(
            "select config from pricing_configs where is_active and branch='jupiter'")).scalar())
    rates = cfg.daily_overhead_rates()

    hdr = (f"{'address':<25}{'roof':<9}{'SQ':>5}{'cutLF':>7}"
           f"{'Tim d':>7}{'our d':>7}{'Δd':>6}"
           f"{'Tim OH':>9}{'our OH':>9}{'our quote':>11}{'catalog':>10}{'Δ$':>10}")
    print(hdr)
    print("-" * len(hdr))
    rows = []
    for h in homes:
        if h["existing"] not in LIKE_FOR_LIKE:
            continue
        rt, day_key = LIKE_FOR_LIKE[h["existing"]]
        sq = h["squares"]
        # apply_cut_calc_to_base=False mirrors what /estimator/quote does: cuts drive the DAYS,
        # the base stays on Tim's flat standard pricing. Without it these totals would be
        # cut-calculator numbers, which is not what we would quote.
        q = QuoteInput(code_zone="FBC", county="palm_beach", roof_type=rt, num_squares=sq,
                       project_kind="residential", demo=True, existing_roof=h["existing"],
                       overhead_mode="daily", apply_cut_calc_to_base=False,
                       hips_lf=h["hips"], valleys_lf=h["valleys"], ridges_lf=h["ridges"],
                       rakes_lf=h["rakes"], wall_flashings_lf=h["wall_flash"],
                       eaves_lf=h["eaves"])
        ours = derive_daily_series(cfg, q)
        our_days = sum(s.days for s in ours)
        our_oh = sum(s.days * float(rates[s.series]) for s in ours)

        tim_series = ([DailyOverheadSeries(series="demo_dry_in_flat", days=half(h["demo"]))]
                      if h["demo"] else [])
        if h[day_key]:
            tim_series.append(DailyOverheadSeries(series=INSTALL_SERIES[rt],
                                                  days=half(h[day_key])))
        tim_days = sum(s.days for s in tim_series)
        tim_oh = sum(s.days * float(rates[s.series]) for s in tim_series)

        r = estimate(cfg, QuoteInput(**{**q.__dict__, "daily_series": ours}))
        cut_lf = h["hips"] + h["valleys"] + h["ridges"] + h["rakes"] + h["wall_flash"]
        cat = float(sell_price_per_sq(_ROOF_TYPE_SYSTEM[rt], "PROTECTOR")) * sq
        print(f"{h['address'][:24]:<25}{h['existing']:<9}{sq:>5.1f}{cut_lf:>7.0f}"
              f"{tim_days:>7.1f}{our_days:>7.1f}{our_days-tim_days:>+6.1f}"
              f"{tim_oh:>9,.0f}{our_oh:>9,.0f}{r['project_total']:>11,.0f}{cat:>10,.0f}"
              f"{cat-r['project_total']:>+10,.0f}")
        rows.append({"address": h["address"], "existing": h["existing"], "squares": sq,
                     "cut_lf": round(cut_lf), "tim_days": tim_days, "our_days": our_days,
                     "day_delta": round(our_days - tim_days, 1), "tim_oh": round(tim_oh),
                     "our_oh": round(our_oh), "our_quote": round(r["project_total"]),
                     "catalog": round(cat), "catalog_minus_ours": round(cat - r["project_total"])})

    n = len(rows)
    exact = sum(1 for r in rows if abs(r["day_delta"]) <= 0.5)
    within1 = sum(1 for r in rows if abs(r["day_delta"]) <= 1.0)
    print("-" * len(hdr))
    print(f"{n} homes | days within 0.5d of Tim: {exact} ({exact/n:.0%}) | "
          f"within 1.0d: {within1} ({within1/n:.0%})")
    print(f"mean |Δdays| {sum(abs(r['day_delta']) for r in rows)/n:.2f}  "
          f"| mean OH ours-his {sum(r['our_oh']-r['tim_oh'] for r in rows)/n:+,.0f}  "
          f"| mean catalog vs ours {sum(r['catalog_minus_ours'] for r in rows)/n:+,.0f}")
    if args.csv:
        with open(args.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {args.csv}")


if __name__ == "__main__":
    main()
