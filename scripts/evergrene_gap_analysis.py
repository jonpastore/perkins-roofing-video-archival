#!/usr/bin/env python3
"""Measure our quote against Tim's real Evergrene bid, building by building.

Jarvis #430/#449. Tim's bid prices 9 buildings at ONE site as one project; we quote each building
as a standalone job. The task recorded the symptom as "+110% on Bus Stop, -20.6% on the Clubhouse,
netting to -7.8% ONLY because the errors offset".

Running it shows the offset is not two pricing errors cancelling. It is ONE systematic over-charge
being masked by project scope we do not quote at all:

    every building is over, +10% to +85%, ~+15% on the buildings taken together
    and Tim carries ~$116k of project-level scope (General Conditions + add-on
    blocks) that has no representation in our engine

That matters for sequencing. Removing the per-building floor and fixed fees WITHOUT also carrying
the project blocks would swing the bid from roughly -9% to roughly -23% — worse, and under.

Two structural causes, both visible in a 3-square outbuilding:

    Bus Stop, 3 sq        ours $8,805      Tim $4,763
      permit_processing + new_bonus_values + delivery_plywood_vents = $3,000 of
        once-per-PROJECT fees charged in full against one 3-square building
      profit floored to $2,500 where the sliding scale gave $600 and Tim's own
        margin is ~$433 (10% of base+overhead)

Usage:
    DB_URL=postgresql+psycopg://... .venv/bin/python scripts/evergrene_gap_analysis.py
    (needs the Cloud SQL proxy; reads the live pricing config, not a fixture)
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests/fixtures/golden/evergrene_project.json"

# Project-level blocks Tim attaches to ONE building rather than spreading. Removing them is the
# only way to compare like with like: without this the Clubhouse looks 20% UNDER when the building
# itself is 10% OVER.
CLUBHOUSE_BLOCKS = 42050 + 31000 + 4250     # sloped add-ons + tile add-ons + an unlabelled 4250
TIKI_EXTRA = 2550


def main() -> None:
    from app.models import SessionLocal
    from core.estimator import QuoteInput, estimate
    from core.pricing_config import load_config

    ev = json.loads(FIXTURE.read_text())
    s = SessionLocal()
    s.info["tenant_id"] = 1
    s.execute(text("set app.tenant_id='1'"))
    raw = s.execute(text(
        "select config from pricing_configs where branch='jupiter' and is_active limit 1")).scalar()
    s.close()
    if raw is None:
        raise SystemExit("no active jupiter pricing config — is DB_URL pointed at the platform DB?")
    cfg = load_config(raw if isinstance(raw, dict) else json.loads(raw))

    rows, tim_bid = [], 0.0
    for b in ev["buildings"]:
        if b["tile_price_per_sq"] is None:
            continue                     # Clubhouse Flats are a separate flat-roof scope
        blocks = CLUBHOUSE_BLOCKS if b["name"].startswith("Clubhouse Sloped") else 0
        blocks += TIKI_EXTRA if b["name"].startswith("Tiki") else 0
        q = QuoteInput(code_zone="FBC", slope_type="sloped", roof_type="13_tile",
                       num_squares=b["squares"], project_kind="commercial", existing_roof="tile")
        r = estimate(cfg, q)
        fixed = sum(li["amount"] for li in r["line_items_detail"]
                    if li["key"] in ("delivery_plywood_vents", "new_bonus_values",
                                     "permit_processing"))
        profit = next((li["amount"] for li in r["line_items_detail"]
                       if li["key"] == "profit"), 0.0)
        rows.append((b["name"], b["squares"], b["tile_total"] - blocks,
                     r["project_total"], fixed, profit))
        tim_bid += b["tile_total"]

    print(f"{'building':<26}{'sq':>5}{'Tim bldg':>11}{'ours':>11}{'delta':>9}"
          f"{'fixed':>9}{'profit':>9}")
    print("-" * 80)
    t = o = f_ = p_ = 0.0
    for name, sq, tim, ours, fixed, profit in rows:
        t += tim
        o += ours
        f_ += fixed
        p_ += profit
        print(f"{name[:25]:<26}{sq:>5.0f}{tim:>11,.0f}{ours:>11,.0f}"
              f"{(ours / tim - 1) * 100:>8.1f}%{fixed:>9,.0f}{profit:>9,.0f}")
    print("-" * 80)
    print(f"{'BUILDINGS ONLY':<26}{'':>5}{t:>11,.0f}{o:>11,.0f}{(o / t - 1) * 100:>8.1f}%"
          f"{f_:>9,.0f}{p_:>9,.0f}")

    gc = ev["project_blocks"]["general_conditions"]["total"]
    unquoted = CLUBHOUSE_BLOCKS + TIKI_EXTRA + gc
    print(f"\nOnce-per-project fees we charge PER BUILDING: ${f_:,.0f} across {len(rows)} buildings")
    print(f"Project scope we do not quote at all:        ${unquoted:,.0f}"
          f"  (${CLUBHOUSE_BLOCKS + TIKI_EXTRA:,.0f} add-ons + ${gc:,.0f} General Conditions)")
    print(f"\nAgainst Tim's full bid of ${tim_bid:,.0f} we quote ${o:,.0f} "
          f"({(o / tim_bid - 1) * 100:+.1f}%) — the two errors mask each other.")


if __name__ == "__main__":
    main()
