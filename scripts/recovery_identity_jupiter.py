#!/usr/bin/env python3
"""THE RECOVERY IDENTITY — JUPITER. The branch whose overhead model is actually being tuned.

Jupiter's production is NOT in the local Knowify mirror: that mirror holds ONE tenant and it is
the Miami company (8,510 projects, 83% Miami-Dade/Broward). Tim's Jupiter company is a separate
Knowify tenant (company 30586 / tenant 28403, 995 projects) reachable only through the Knowify
MCP. Every "sold $/sq" number used in the overhead analysis to date came from the MIAMI mirror.

The lines below are the ACCEPTED (BusinessState="Open") per-square roof lines of the JUPITER
tenant since 2025-01-01, pulled 2026-07-30 via
    mcp__knowify__query Deliverables
      where UnitName="Squares", IsChangeOrder=false,
            $Contract.BusinessState$="Open", $Contract.DateCreated$>=2025-01-01
132 raw lines -> the base roof lines below, after dropping:
  - "(OPTIONAL) ..." add-on lines (upgrades, water barriers, base sheets)
  - the PREFERRED / PREMIUM / COASTAL tier lines, which are UPCHARGE DELTAS on top of the
    PROTECTOR base for the SAME squares (e.g. contract 4898043: PROTECTOR metal $78,935 +
    PREMIUM metal $13,505), so counting them would double-count both squares and days
  - $0 lines (unselected menu options)

The identity, under overhead_basis="branch", reduces to a pure day count:
    ratio = SUM(estimator job-days) / working days in the period
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date

import numpy as np
from sqlalchemy import create_engine, text

from core.estimator import QuoteInput, derive_daily_series
from core.pricing_config import load_config

# (contract, sold date, series bucket, squares).  "flat" = low-slope: NO fitted day model exists,
# so those days are MISSING from the ratio — the printed number is a floor.
LINES = [
    (3753565, "2025-01-20", "tile", 51.5),
    (3789568, "2025-02-03", "tile", 44.0),
    (3793306, "2025-02-04", "metal", 42.0), (3793306, "2025-02-04", "flat", 5.0),
    (3798201, "2025-02-06", "tile", 63.0),
    (3799619, "2025-02-06", "flat", 1.0),
    (3781364, "2025-01-30", "tile", 61.5),
    (3824739, "2025-02-17", "tile", 88.5),
    (3834086, "2025-02-19", "shingle", 10.0),
    (3864579, "2025-03-03", "metal", 27.5),
    (3870290, "2025-03-05", "tile", 68.0),
    (3879885, "2025-03-07", "metal", 290.0),
    (3979768, "2025-04-11", "shingle", 26.5), (3979768, "2025-04-11", "flat", 5.0),
    (4004506, "2025-04-22", "flat", 12.5),
    (4011575, "2025-04-23", "shingle", 16.0),
    (4019755, "2025-04-25", "metal", 34.0),
    (4020387, "2025-04-25", "tile", 102.0),
    (4031861, "2025-04-30", "tile", 51.5),
    (4032140, "2025-04-30", "tile", 22.0), (4032140, "2025-04-30", "flat", 3.0),
    (4060887, "2025-05-10", "tile", 55.0),
    (4064202, "2025-05-12", "tile", 39.0),
    (4105622, "2025-05-27", "metal", 63.5),
    (4129425, "2025-06-04", "shingle", 16.0),
    (4141572, "2025-06-09", "shingle", 35.5),
    (4187639, "2025-06-24", "flat", 7.0),
    (4256317, "2025-07-18", "tile_new", 26.0), (4256317, "2025-07-18", "flat", 28.0),
    (4277411, "2025-07-25", "tile", 48.0),
    (4333146, "2025-08-14", "metal", 48.5),
    (4416607, "2025-09-12", "metal", 33.5),
    (4421902, "2025-09-15", "metal", 56.0),
    (4441821, "2025-09-22", "metal", 23.0),
    (4450993, "2025-09-24", "flat", 18.0),
    (4471907, "2025-10-01", "metal", 44.0), (4471907, "2025-10-01", "flat", 46.0),
    (4504317, "2025-10-10", "tile", 32.0),
    (4517419, "2025-10-15", "tile", 34.0),
    (4532119, "2025-10-21", "shingle", 41.0),
    (4559248, "2025-10-29", "tile", 20.0),
    (4573556, "2025-11-04", "shingle", 35.0),
    (4574270, "2025-11-04", "shingle", 18.0),
    (4601962, "2025-11-12", "metal", 36.5),
    (4637482, "2025-11-25", "tile", 33.0),
    (4804208, "2026-01-27", "tile", 36.0),
    (4804453, "2026-01-27", "shingle", 36.0),
    (4856269, "2026-02-11", "tile", 37.5),
    (4864602, "2026-02-13", "metal", 38.5),
    (4871202, "2026-02-16", "flat", 2.0),
    (4898043, "2026-02-24", "metal", 74.0),
    (5024267, "2026-03-30", "shingle", 33.5), (5024267, "2026-03-30", "flat", 6.5),
    (5074168, "2026-04-13", "metal", 33.0), (5074168, "2026-04-13", "flat", 3.5),
    (5120858, "2026-04-24", "tile", 8.0), (5120858, "2026-04-24", "flat", 24.0),
    (5128964, "2026-04-28", "tile", 33.5),
    (5191571, "2026-05-14", "tile", 76.0),
    (5216592, "2026-05-21", "shingle", 21.0),
    (5262477, "2026-06-04", "metal", 45.0),
    (5266911, "2026-06-05", "metal", 9.0),
    (5268422, "2026-06-07", "shingle", 40.0),
    (5301409, "2026-06-16", "shingle", 30.0), (5301409, "2026-06-16", "flat", 5.5),
    (5312523, "2026-06-18", "tile", 43.5),
    (5338362, "2026-06-26", "metal", 26.0),
    (5411711, "2026-07-17", "tile", 39.0),
    (5412688, "2026-07-17", "metal", 29.0),
]

ROOF_TYPE = {"tile": "13_tile", "tile_new": "13_tile", "shingle": "dimensional_shingle",
             "metal": "standing_seam_metal"}
HOLIDAYS_PER_YEAR = 8


def _working_days(start: date, end: date) -> int:
    days = int(np.busday_count(start, end))
    return max(days - round(HOLIDAYS_PER_YEAR * days / 252), 0)


def main() -> None:
    eng = create_engine(os.environ["DB_URL"])
    with eng.connect() as c:
        c.execute(text("set app.tenant_id='1'"))
        cfg = load_config(c.execute(text(
            "select config from pricing_configs where is_active and branch='jupiter'")).scalar())

    burn = 1470.0          # Tim, 2026-07-30 08:30 (config still carries the stale 1400)
    days_by_month: dict[str, float] = defaultdict(float)
    jobs_by_month: dict[str, set] = defaultdict(set)
    flat_sq = flat_lines = 0.0
    per_series: dict[str, float] = defaultdict(float)

    for contract, sold, bucket, sq in LINES:
        month = sold[:7]
        if bucket == "flat":
            flat_sq += sq
            flat_lines += 1
            jobs_by_month[month].add(contract)
            continue
        series = derive_daily_series(cfg, QuoteInput(
            code_zone="FBC", slope_type="sloped", roof_type=ROOF_TYPE[bucket], num_squares=sq,
            project_kind="residential",
            # new construction has no tear-off, so it carries no demo days
            demo=bucket != "tile_new", existing_roof="none" if bucket == "tile_new" else "tile"))
        for s in series:
            per_series[s.series] += s.days
            days_by_month[month] += s.days
        jobs_by_month[month].add(contract)

    print("JUPITER — accepted per-square roof work, 2025-01 .. 2026-07 (Knowify MCP, tenant 28403)")
    print(f"  {len(LINES)} roof lines on {len({c for c, *_ in LINES})} accepted contracts")
    print(f"  low-slope lines with NO fitted day model: {flat_lines:.0f} lines, {flat_sq:,.0f} sq"
          f"  (their days are missing below)")
    print("  estimator days by series: " + ", ".join(f"{k}={v:.1f}" for k, v in sorted(per_series.items())))
    print()
    print(f"{'month':9}{'jobs':>6}{'OH days':>10}{'work days':>11}{'ratio':>8}"
          f"{'OH charged':>13}{'burn':>11}{'gap':>12}")
    # Every calendar month in the window counts, including the ones that sold nothing — a month
    # with no accepted job still burns a full office.
    span, all_months = date(2025, 1, 1), []
    while span < date.today():
        all_months.append(span.strftime("%Y-%m"))
        span = date(span.year + (span.month == 12), (span.month % 12) + 1, 1)
    tot_days = tot_wd = 0.0
    for m in all_months:
        y, mo = int(m[:4]), int(m[5:7])
        start = date(y, mo, 1)
        end = date(y + (mo == 12), (mo % 12) + 1, 1)
        wd = _working_days(start, min(end, date.today()))
        if not wd:
            continue
        d = days_by_month[m]
        tot_days += d
        tot_wd += wd
        print(f"{m:9}{len(jobs_by_month[m]):>6}{d:>10.1f}{wd:>11}{d / wd:>8.2f}"
              f"{d * burn:>13,.0f}{wd * burn:>11,.0f}{d * burn - wd * burn:>12,.0f}")
    print("-" * 80)
    print(f"{'TOTAL':9}{'':>6}{tot_days:>10.1f}{tot_wd:>11.0f}{tot_days / tot_wd:>8.2f}"
          f"{tot_days * burn:>13,.0f}{tot_wd * burn:>11,.0f}"
          f"{(tot_days - tot_wd) * burn:>12,.0f}")
    print()
    # One 290-square metal job (contract 3879885, March 2025, $375k) is 10% of all days sold in
    # the window. Report the ratio without it so the conclusion does not rest on one contract.
    big = sum(s.days for s in derive_daily_series(cfg, QuoteInput(
        code_zone="FBC", slope_type="sloped", roof_type="standing_seam_metal", num_squares=290.0,
        project_kind="residential", demo=True, existing_roof="tile")))
    print(f"excluding the single 290-sq metal job ({big:.1f} days): "
          f"ratio {(tot_days - big) / tot_wd:.2f}")
    print()
    print(f"ratio = estimator-charged overhead days / calendar working days, at ${burn:,.0f}/day burn.")
    print("1.0 = the office is funded exactly. >1 = the parallel-job double count is real and")
    print("      the estimator bills more days than the calendar holds. <1 = the accepted work")
    print("      does not pay for the office.")
    print("Sold-date months, not production months: a job sold in March is built in April, so")
    print("read the TOTAL, not any single month.")


if __name__ == "__main__":
    main()
