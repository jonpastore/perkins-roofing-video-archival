#!/usr/bin/env python3
"""Mixed sloped+flat roofs in the sold record: how common, what split, what price.

Jon: "do we have proposal names in the legacy quotes that we can use to infer the type from the
name?" Yes — Knowify scope-line descriptions name the section ("PERKINS PROTECTOR - Tile Re-Roof",
"PERKINS PROTECTOR - Flat Re-Roof"), so a contract carrying both IS a mixed roof.

Classification has to be tight or it is worse than nothing. A naive keyword match produced 1,395
"mixed" contracts, but was counting:
  * tier UPGRADES as sections — "PERKINS PREFERRED - Metal Re-Roof" at $133/sq is the delta over
    PROTECTOR, not a roof;
  * "(OPTIONAL) Polyglass MTS Secondary Water Barrier" as a FLAT section because it says Polyglass,
    when it is underlayment priced across the SAME squares as the sloped roof.

So: base scope lines only (PROTECTOR, or an unprefixed re-roof line), never OPTIONAL/upgrade tiers,
and a flat section whose square count equals the sloped one is treated as same-area underlayment
rather than a second section.

Prices are time-sliced — an all-time median blends every price list the business has used.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/mixed_roof_sold_analysis.py
"""
from __future__ import annotations

import os
import re
import statistics as st
from collections import defaultdict

from sqlalchemy import create_engine, text

SQ_UNITS = {"squares", "square", "sq"}
# Lines that are add-ons to a scope, not a scope of their own.
UPGRADE = re.compile(
    r"\(optional\)|optional\b|upgrade|preferred|premium|coastal|penny|discount|"
    r"secondary water barrier|\bMTS\b|gutter|solatube|vent|paint|stucco|strap|repair",
    re.I,
)
FLAT = re.compile(r"\bflat\b|built[- ]?up|\bbur\b|3-ply|modified bitumen", re.I)
SLOPED = re.compile(r"\btile\b|\bshingle\b|\bmetal\b|\bslate\b", re.I)


def main() -> None:
    eng = create_engine(os.environ["DB_URL"])
    with eng.connect() as c:
        c.execute(text("set app.tenant_id='1'"))
        contracts = {
            p["Id"]: p
            for (p,) in c.execute(text(
                "select payload from knowify_raw_records "
                "where entity='contracts' and is_present")).all()
            if p.get("Id") is not None
        }
        delivs = [p for (p,) in c.execute(text(
            "select payload from knowify_raw_records "
            "where entity='deliverables' and is_present")).all()]

    jobs: dict[int, dict] = defaultdict(lambda: {"sloped": [], "flat": []})
    for d in delivs:
        desc = (d.get("Description") or "").strip()
        cid = d.get("ContractId")
        if not cid or not desc or d.get("IsChangeOrder"):
            continue
        if (d.get("UnitName") or "").strip().lower() not in SQ_UNITS:
            continue
        if UPGRADE.search(desc):
            continue
        qty, price = d.get("Quantity"), d.get("Price")
        if not qty or not price:
            continue
        sq, dollars = float(qty) / 100.0, float(price) / 100.0
        if sq < 1 or sq > 300 or dollars < 1000:
            continue
        rec = {"desc": desc, "sq": sq, "price": dollars, "per_sq": dollars / sq}
        if FLAT.search(desc):
            jobs[cid]["flat"].append(rec)
        elif SLOPED.search(desc):
            jobs[cid]["sloped"].append(rec)

    mixed = []
    for cid, v in jobs.items():
        if not (v["sloped"] and v["flat"]):
            continue
        s_sq = sum(r["sq"] for r in v["sloped"])
        f_sq = sum(r["sq"] for r in v["flat"])
        # Same-area "flat" line = underlayment across the sloped roof, not a second section.
        if abs(s_sq - f_sq) < 0.01:
            continue
        created = (contracts.get(cid) or {}).get("DateCreated") or ""
        mixed.append({
            "cid": cid, "year": created[:4], "sloped_sq": s_sq, "flat_sq": f_sq,
            "sloped_price": sum(r["price"] for r in v["sloped"]),
            "flat_price": sum(r["price"] for r in v["flat"]),
        })

    sloped_only = sum(1 for v in jobs.values() if v["sloped"] and not v["flat"])
    print(f"sloped-only jobs: {sloped_only}    MIXED sloped+flat jobs: {len(mixed)}"
          f"    ({100 * len(mixed) / max(1, sloped_only + len(mixed)):.0f}% of roofs are mixed)")
    print()

    shares = [m["flat_sq"] / (m["sloped_sq"] + m["flat_sq"]) for m in mixed]
    shares.sort()
    print(f"flat share of a mixed roof: median {100*st.median(shares):.0f}%, "
          f"p25 {100*shares[len(shares)//4]:.0f}%, p75 {100*shares[3*len(shares)//4]:.0f}%, "
          f"max {100*shares[-1]:.0f}%")
    print()

    by_year: dict[str, list[float]] = defaultdict(list)
    for m in mixed:
        if m["year"] and m["flat_sq"] > 0:
            by_year[m["year"]].append(m["flat_price"] / m["flat_sq"])
    print("FLAT section sold $/sq, by year (time-sliced — an all-time median blends price lists):")
    for y in sorted(by_year):
        v = sorted(by_year[y])
        if len(v) < 5:
            continue
        print(f"   {y}  n={len(v):<4} median ${st.median(v):>7,.0f}   "
              f"p25 ${v[len(v)//4]:>7,.0f}  p75 ${v[3*len(v)//4]:>7,.0f}")


if __name__ == "__main__":
    main()
