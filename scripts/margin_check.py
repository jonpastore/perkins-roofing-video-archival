#!/usr/bin/env python3
"""What margin does Tim's real pricing leave, once materials/labor and overhead are paid?

Jon, 2026-07-29: *"the pricing should be materials, costs including OH, plus margin. margin is
the negotiable value ... maybe we're not calculating something right."*

That is exactly the arithmetic here, run against his own charged prices:

    margin$ = charged price − (every cost line the engine emits) − overhead
    margin% = margin$ / charged price

Run under BOTH overhead models, because the choice between them is the whole question:

  * ``branch``  — one flat daily number per branch (Jupiter $28,000/mo ÷ 20 = $1,400/day).
  * ``series``  — Tim's 7/24 per-day rates ($745 tile / $700 shingle / $850 metal / $1,050 demo),
                  which are that same office burn divided across the crews actually out.

⚠️ The two are not rival estimates of one quantity. $1,400/day recovers the office exactly when
ONE job runs every working day ($1,400 × 250 ≈ the $336k annual burn); the per-series rates
recover it when ~1.75 run at once. So a job "only recovering $840/day" is not evidence of a
margin squeeze — it is what per-job allocation looks like with two crews out. Measured
concurrency from invoiced work: ~0.9–1.7 job-equivalents per working day in 2025, ~1.5–4.3 in
2024. Which model is right is a business decision (see
docs/email-drafts/2026-07-29-tim-overhead-and-pricing.md), not an engineering one.

This script replaces the numbers in the unsent 2026-07-28 draft, which reported a −0.4% median
margin. That does not reproduce on the current config — it predates the per-week profit floor,
the refit day model and the cut-geometry base.

Data: ~/perkins-corpus/tim30_with_actual_prices.json — Tim's 30 homes (TIME LEARNING email,
2026-07-24) with his own day counts, 21 of which carry a charged price for the existing material.
Like-for-like re-roof, FBC / Palm Beach / jupiter branch.

Usage: PYTHONPATH=. .venv/bin/python scripts/margin_check.py
       (reads the live jupiter config over the Cloud SQL proxy; writes nothing)
"""
from __future__ import annotations

import json
import math
import statistics as st
import subprocess
from pathlib import Path

import psycopg

from core.estimator import DailyOverheadSeries, QuoteInput, estimate
from core.pricing_config import load_config

HOMES = Path.home() / "perkins-corpus/tim30_with_actual_prices.json"

# existing roof -> (roof_type we quote, his day column, daily_overhead_rates series)
LIKE_FOR_LIKE = {
    "tile": ("13_tile", "tile", "tile"),
    "shingle": ("dimensional_shingle", "shingle", "shingle"),
    "metal": ("standing_seam_metal", "metal", "metal"),
}


def _db_password() -> str:
    return subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest", "--secret=db-password"],
        capture_output=True, text=True, check=True,
    ).stdout


def _active_config(branch: str = "jupiter") -> dict:
    with psycopg.connect(host="127.0.0.1", port=5432, dbname="perkins", user="app",
                         password=_db_password()) as cn, cn.cursor() as c:
        c.execute("set app.tenant_id='1'")
        c.execute("select config from pricing_configs where is_active and branch=%s", (branch,))
        return c.fetchone()[0]


def half(x: float) -> float:
    """Round to the 0.5 DailyOverheadSeries requires."""
    return max(0.5, round(x * 2) / 2)


def price_home(cfg_raw: dict, home: dict, basis: str) -> dict | None:
    """One home priced under one overhead basis. None when it carries no charged price."""
    ex = home["existing"]
    if ex not in LIKE_FOR_LIKE or not home.get("sloped_sq"):
        return None
    roof_type, day_col, series_name = LIKE_FOR_LIKE[ex]
    price = home.get(f"price_{ex}")
    if not price:
        return None

    series = []
    if home.get("demo"):
        series.append(DailyOverheadSeries(series="demo_dry_in_flat", days=half(home["demo"])))
    if home.get(day_col):
        series.append(DailyOverheadSeries(series=series_name, days=half(home[day_col])))

    q = QuoteInput(code_zone="FBC", county="palm_beach", roof_type=roof_type,
                   num_squares=home["sloped_sq"], project_kind="residential", demo=True,
                   existing_roof=ex, overhead_mode="daily", daily_series=series)
    result = estimate(load_config({**cfg_raw, "overhead_basis": basis}), q)
    amounts = {li["key"]: li["amount"] for li in result["line_items_detail"]}

    overhead = amounts.get("overhead", 0.0)
    # Every line except overhead and profit is a cost Tim cannot negotiate away.
    cost = sum(v for k, v in amounts.items() if k not in ("overhead", "profit"))
    days = sum(s.days for s in series)
    return {
        "address": home["address"][:22], "existing": ex, "sq": home["sloped_sq"], "days": days,
        "price": price, "cost": cost, "overhead": overhead,
        "engine_total": result["project_total"], "margin": price - cost - overhead,
        "margin_pct": 100 * (price - cost - overhead) / price,
        "engine_vs_price_pct": 100 * (result["project_total"] - price) / price,
    }


def main() -> None:
    cfg_raw = _active_config()
    homes = json.loads(HOMES.read_text())

    priced = {b: [r for r in (price_home(cfg_raw, h, b) for h in homes) if r]
              for b in ("branch", "series")}

    for basis, label in (("branch", "FLAT $1,400/day (branch basis)"),
                         ("series", "per-series ($745 / $700 / $850 / $1,050)")):
        rows = priced[basis]
        margins = [r["margin_pct"] for r in rows]
        engine = [r["engine_vs_price_pct"] for r in rows]
        below = [r for r in rows if r["margin"] < 2500 * math.ceil(r["days"] / 5)]
        print(f"\n=== {label} — n={len(rows)}")
        print(f"  our quote vs his charged price : median {st.median(engine):+.1f}%   "
              f"within 10%: {sum(1 for e in engine if abs(e) <= 10)}/{len(engine)}")
        print(f"  margin left after cost + OH    : median {st.median(margins):+.1f}%  "
              f"min {min(margins):+.1f}%  max {max(margins):+.1f}%")
        print(f"  below the $2,500/on-site-week floor: {len(below)}/{len(rows)}")

    rows = priced["branch"]
    solved = [(r["price"] - r["cost"] - 2500 * math.ceil(r["days"] / 5)) / r["days"] for r in rows]
    solved15 = [(r["price"] - r["cost"] - 0.15 * r["price"]) / r["days"] for r in rows]
    print(f"\nDaily overhead his prices support, after paying the weekly floor: "
          f"median ${st.median(solved):,.0f}")
    print(f"Same at a flat 15% margin instead:                                 "
          f"median ${st.median(solved15):,.0f}")
    print("For scale: $28,000/mo ÷ 20 = $1,400/day, and $1,400 × 250 working days = $350,000/yr "
          "against a $336,000/yr burn — i.e. exactly right for ONE job at a time.")

    print(f"\n{'address':<24}{'ex':<9}{'SQ':>5}{'days':>6}{'his price':>11}{'cost':>10}"
          f"{'OH@1400':>9}{'margin$':>9}{'margin%':>9}")
    for r in sorted(rows, key=lambda x: x["margin_pct"]):
        print(f"{r['address']:<24}{r['existing']:<9}{r['sq']:>5.0f}{r['days']:>6.1f}"
              f"{r['price']:>11,.0f}{r['cost']:>10,.0f}{r['overhead']:>9,.0f}"
              f"{r['margin']:>9,.0f}{r['margin_pct']:>8.1f}%")


if __name__ == "__main__":
    main()
