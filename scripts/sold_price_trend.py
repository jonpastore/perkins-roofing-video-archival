#!/usr/bin/env python3
"""Sold $/sq by material, SLICED BY TIME — because an all-time median blends years of price moves.

Jon, 2026-07-25: "prices fluctuate over time. you have to look at data in time slices to see how
they ebb and flow together. If the price recently increased it skews the results."

Joins Knowify deliverables (Quantity in 1/100 squares, Price in cents) to their contract for a
date, and reports the median sold price per square per material per period. Our pricing config is
built from Tim's CURRENT sheet, so the only fair comparison is against the MOST RECENT slice — an
all-time median is a weighted average of every price list he has ever used.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/sold_price_trend.py [--signed-only]
"""
from __future__ import annotations

import argparse
import os
import re
import statistics as st
from collections import defaultdict

from sqlalchemy import create_engine, text

MATERIALS = [
    ("barrel", r"\bbarrel\b"),
    ("tile", r"\btile\b"),
    ("shingle", r"\bshingle\b"),
    ("metal", r"\bmetal\b|standing seam"),
    ("tpo", r"\btpo\b"),
    ("silicone", r"\bsilicone\b"),
    ("coating", r"\bcoating\b"),
]
# Quantity is hundredths of a square and Price is cents — confirmed by rows whose own description
# repeats the figure ("(Qty.: 29 Squares)" against Quantity=2900).
QTY_SCALE = 100.0
CENTS = 100.0


def _bucket(desc: str) -> str | None:
    for name, pat in MATERIALS:
        if re.search(pat, desc, re.I):
            return name
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--signed-only", action="store_true",
                    help="only contracts with IsSigned (sold, not quoted)")
    ap.add_argument("--period", choices=("year", "half"), default="year")
    args = ap.parse_args()

    eng = create_engine(os.environ["DB_URL"])
    with eng.connect() as c:
        c.execute(text("set app.tenant_id='1'"))
        contracts = {
            p["Id"]: p for (p,) in c.execute(text(
                "select payload from knowify_raw_records "
                "where entity='contracts' and is_present")).all()
            if p.get("Id") is not None
        }
        delivs = [p for (p,) in c.execute(text(
            "select payload from knowify_raw_records "
            "where entity='deliverables' and is_present")).all()]

    obs: dict[tuple[str, str], list[float]] = defaultdict(list)
    skipped_nodate = 0
    for d in delivs:
        if (d.get("UnitName") or "").strip().lower() not in ("squares", "square", "sq"):
            continue
        if d.get("IsChangeOrder"):
            continue
        qty, price = d.get("Quantity"), d.get("Price")
        if not qty or not price:
            continue
        sq = float(qty) / QTY_SCALE
        dollars = float(price) / CENTS
        if sq < 5 or sq > 200 or dollars < 2000:
            continue
        mat = _bucket(d.get("Description") or "")
        if not mat:
            continue
        ct = contracts.get(d.get("ContractId"))
        created = (ct or {}).get("DateCreated")
        if not created:
            skipped_nodate += 1
            continue
        if args.signed_only and not (ct or {}).get("IsSigned"):
            continue
        year, month = int(created[:4]), int(created[5:7])
        period = f"{year}" if args.period == "year" else f"{year}H{1 if month <= 6 else 2}"
        obs[(mat, period)].append(dollars / sq)

    periods = sorted({p for _, p in obs})
    mats = [m for m, _ in MATERIALS if any((m, p) in obs for p in periods)]
    print(f"median sold $/sq by material and {args.period}"
          f"{' (signed contracts only)' if args.signed_only else ''}"
          f"   [{skipped_nodate} rows dropped: no contract date]")
    print()
    print(f"{'material':10} " + " ".join(f"{p:>14}" for p in periods))
    print("-" * (10 + 15 * len(periods)))
    for m in mats:
        cells = []
        for p in periods:
            v = obs.get((m, p)) or []
            cells.append(f"{st.median(v):>9,.0f} n={len(v):<3}" if len(v) >= 5 else
                         (f"{st.median(v):>9,.0f} n={len(v):<3}" if v else f"{'—':>14}"))
        print(f"{m:10} " + " ".join(cells))

    print()
    print("Change from first to last period with n>=5, per material:")
    for m in mats:
        pts = [(p, st.median(obs[(m, p)])) for p in periods
               if len(obs.get((m, p)) or []) >= 5]
        if len(pts) >= 2:
            (p0, v0), (p1, v1) = pts[0], pts[-1]
            print(f"  {m:10} {p0} ${v0:,.0f}/sq  ->  {p1} ${v1:,.0f}/sq   "
                  f"{100 * (v1 / v0 - 1):+.1f}%")


if __name__ == "__main__":
    main()
