#!/usr/bin/env python3
"""Price Tim's Evergrene bid as ONE project and diff it against what he actually charged.

The R1 behavioural validation for core/bid_project.py (#430/#449). Same shape as
scripts/validate_against_tim_30_homes.py: score the engine against a known-good bid rather than
against our own expectations.

⚠️ LIKE-FOR-LIKE. Tim's stated project total (`K42 = SUM(K35:K41)+K33`) EXCLUDES two things:
the Clubhouse Flats (K34, a separate flat-roof scope) and General Conditions ($36,570, which is
computed in D19 and referenced by no total formula on his sheet). Comparing our all-in number
against his K42 would read +11.9% purely from the GC line, so GC is left out of the comparison
and reported separately.

Usage:
    DB_URL=postgresql+psycopg://... .venv/bin/python scripts/validate_against_evergrene.py
    (needs the Cloud SQL proxy; reads the live jupiter config, not a fixture)
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests/fixtures/golden/evergrene_project.json"

#: Tim's own markup per building, read off his G-column formulas. Used only to state what HIS
#: margin was — we do not price this way.
TIM_MARKUP = {
    "Clubhouse Sloped": 1.11, "Tiki Hut": 1.12, "Pool Pump House": 1.10, "Gazebo": 1.12,
    "Boat House": 1.12, "Bus Stop": 1.10, "Donald Ross Gate (North)": 1.12,
    "Hood Road Gate (South)": 1.12,
}
#: Project blocks Tim folds into one building. Removed from HIS per-building number so the
#: building-level comparison is like for like.
FOLDED = {"Clubhouse Sloped": 42050 + 31000 + 4250, "Tiki Hut": 2550}


def main() -> None:
    from app.models import SessionLocal
    from core.bid_project import Building, ProjectItem, price_project
    from core.estimator import QuoteInput
    from core.pricing_config import load_config

    ev = json.loads(FIXTURE.read_text())
    s = SessionLocal()
    s.info["tenant_id"] = 1
    s.execute(text("set app.tenant_id='1'"))
    raw = s.execute(text(
        "select config from pricing_configs where branch='jupiter' and is_active limit 1")).scalar()
    s.close()
    if raw is None:
        raise SystemExit("no active jupiter pricing config — is DB_URL on the platform DB?")
    cfg = load_config(raw if isinstance(raw, dict) else json.loads(raw))

    tile = [b for b in ev["buildings"] if b["tile_price_per_sq"] is not None]
    buildings = [
        Building(name=b["name"], days=b["days"]["total_tile"],
                 quote=QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="13_tile",
                                  num_squares=b["squares"], project_kind="commercial",
                                  existing_roof="tile"))
        for b in tile
    ]
    pb = ev["project_blocks"]
    items = [
        ProjectItem("sloped_add_ons", "Sloped roof add-ons", pb["sloped_add_ons"]["total"]),
        ProjectItem("tile_add_ons", "Tile roof add-ons", pb["tile_add_ons"]["total"]),
    ]
    r = price_project(cfg, buildings, project_items=items)

    tim_by_name = {b["name"]: b for b in tile}
    print(f"{'structure':<26}{'sq':>5}{'ours':>11}{'Tim':>11}{'delta':>9}")
    print("-" * 62)
    for row in r["buildings"]:
        t = tim_by_name[row["name"]]["tile_total"] - FOLDED.get(row["name"], 0)
        print(f"{row['name'][:25]:<26}{row['squares']:>5.0f}{row['total']:>11,.0f}"
              f"{t:>11,.0f}{(row['total'] / t - 1) * 100:>8.1f}%")
    print("-" * 62)

    print("\nCharged ONCE for the site (each was charged per building before):")
    for f in r["project_fixed"]:
        print(f"   {f['label']:<28}{f['amount']:>10,.0f}   {f['basis']}")

    tim_total = ev["totals"]["tile_project_total"]
    tim_profit = sum(
        (b["base_cost_per_sq"] + b["tile_overhead_per_sq"]) * (TIM_MARKUP[b["name"]] - 1)
        * b["squares"] for b in tile if b["name"] in TIM_MARKUP)

    print(f"\nPROJECT TOTAL   ours ${r['project_total']:>10,.0f}   Tim ${tim_total:>10,.0f}"
          f"   {(r['project_total'] / tim_total - 1) * 100:+.1f}%")
    print(f"PROFIT          ours ${r['profit']:>10,.0f}   Tim ${tim_profit:>10,.0f}"
          f"   {(r['profit'] / tim_profit - 1) * 100:+.1f}%")

    gc = pb["general_conditions"]["total"]
    print(f"\nGeneral Conditions ${gc:,.0f} is EXCLUDED above because Tim's K42 excludes it.")
    print(f"All-in, both carrying GC: ours ${r['project_total'] + gc:,.0f}")

    fl = r["floor"]
    print(f"\nFloor: basis={fl['basis']}  {fl['on_site_days']:.0f} days = {fl['on_site_weeks']} "
          f"weeks  applied=${fl['applied']:,.0f}")
    print(f"  #449's weekly basis would have been ${fl['weekly_basis_would_be']:,.0f} "
          f"against Tim's own ${tim_profit:,.0f}.")
    for w in r["warnings"]:
        print(f"  ! {w}")

    print("\nBEFORE the project container: every building +10.2% to +84.9% (+15.0% together), "
          "and the bid netted -9.1% only because $116,420 of unquoted project scope masked it.")


if __name__ == "__main__":
    main()
