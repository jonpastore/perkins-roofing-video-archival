#!/usr/bin/env python3
"""Switch ON the enforced profit floor, and show what it moves before it does.

Tim, 2026-07-17 Zoom [08:52]: "i like to make 2500 bucks a week that we're on the job ... and if
it's one day it still counts as one week and i'm still gonna charge 2500 bucks minimum on
re-roofs". The floor is therefore PER JOB and PER WEEK ON THAT JOB, one week minimum -- five
separate one-day jobs owe $2,500 each, nothing pools across a calendar week.

The amount already existed as weekly_profit_floor ($2,500) and job_profit_floor ($2,500), and
compute_profit_guidance already computed effective_floor = max(absolute, weeks x weekly). It was
advisory only. This flips enforce_profit_floor so it moves the price and warns.

UNLIKE `job_profit_floor` and `weekly_profit_floor`, which only feed the margin badge, this one
MOVES THE QUOTED PRICE: `_apply_min_margin` raises the profit line to it and stamps a
`min_margin_applied` warning. Explicit operator pricing (`profit_mode="flat"`,
`override_profit_per_sq`) is never overridden.

BASIS: "job" (Jon's call 2026-07-25) -- one flat $2,500 however long the job runs. The "weekly"
basis multiplies by on-site weeks, which follows from his words but repriced 17 of his own 29
homes upward, because most re-roofs run 7-10 days and a $5,000 two-week floor beats his sliding
scale on nearly every tile job. He said "$2,500 a week"; he never said "$5,000 on a two-week
job". Flip with --basis weekly if he confirms.

⚠️ profit_floor_days_per_week is ASSUMED 6 (Mon-Sat). Only used by the "weekly" basis and by the
guidance figures. Confirm 5, 6 or 7 with Tim.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/seed_min_margin.py [--apply]
       (prints the impact and changes nothing unless --apply is passed)
"""
from __future__ import annotations

import argparse
import sys

BRANCH_ORDER = ("jupiter", "miami", "naples")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weekly", type=float, default=2500.0,
                        help="profit floor per on-site week (default 2500)")
    parser.add_argument("--days-per-week", type=float, default=6.0,
                        help="working days per week (default 6, Mon-Sat)")
    parser.add_argument("--basis", choices=("job", "weekly"), default="job",
                        help="'job' = one flat floor per job (default); "
                             "'weekly' = x on-site weeks")
    parser.add_argument("--off", action="store_true",
                        help="disable enforcement instead of enabling it")
    parser.add_argument("--apply", action="store_true",
                        help="write a new config version (otherwise print and exit)")
    args = parser.parse_args()

    from sqlalchemy import select

    from app.models import PricingConfig, SessionLocal
    from core.pricing_config import compute_hash, load_config

    s = SessionLocal()
    s.info["tenant_id"] = 1
    branches = [r[0] for r in s.execute(select(PricingConfig.branch).distinct()).all()]
    for branch in sorted(branches, key=lambda b: (BRANCH_ORDER + (b,)).index(b)):
        active = s.execute(select(PricingConfig).where(
            PricingConfig.branch == branch, PricingConfig.is_active == True  # noqa: E712
        )).scalar_one_or_none()
        if active is None:
            print(f"{branch}: no active config", file=sys.stderr)
            continue
        want = not args.off
        cfg = dict(active.config)
        cfg["enforce_profit_floor"] = want
        cfg["profit_floor_basis"] = args.basis
        cfg["job_profit_floor"] = args.weekly
        cfg["weekly_profit_floor"] = args.weekly
        cfg["profit_floor_days_per_week"] = args.days_per_week
        if cfg == dict(active.config):
            print(f"{branch}: already set — skipped")
            continue

        pc = load_config(cfg)
        # Smallest job the sliding scale carries unaided for ONE week — under this, a one-week
        # job gets repriced. Longer jobs owe a multiple, so this is the floor's gentlest case.
        bites = next((sq for sq in range(1, 401)
                      if pc.profit_per_sq(float(sq)) * sq >= args.weekly), None)
        unit = "per job" if args.basis == "job" else "per on-site week"
        print(f"{branch}: enforce_profit_floor -> {want}, ${args.weekly:,.0f} {unit}"
              + (f"  (repricing jobs under ~{bites} squares)" if want and bites else ""))

        if not args.apply:
            continue
        active.is_active = False
        s.flush()
        new = PricingConfig(
            branch=branch, version=active.version + 1,
            label=("enforce profit floor ${:,.0f}/wk, {:g}-day week"
                   .format(args.weekly, args.days_per_week)),
            config=cfg, config_hash=compute_hash(cfg),
            is_active=True, created_by="seed_min_margin.py", tenant_id=1,
        )
        s.add(new)
        s.flush()
        print(f"  created + activated v{new.version} (id={new.id})")

    if args.apply:
        s.commit()
    else:
        s.rollback()
        print("\n(dry run — nothing written; pass --apply to commit)")
    s.close()


if __name__ == "__main__":
    main()
