#!/usr/bin/env python3
"""Set the enforced minimum-margin floor, and show what it would move before it does.

R2 review, MEDIUM: `min_margin_dollars` shipped reachable only by hand-editing JSONB, which is
an R3 violation (git -> apply, never the reverse). This is the git-tracked way to set it.

UNLIKE `job_profit_floor` and `weekly_profit_floor`, which only feed the margin badge, this one
MOVES THE QUOTED PRICE: `_apply_min_margin` raises the profit line to it and stamps a
`min_margin_applied` warning. Explicit operator pricing (`profit_mode="flat"`,
`override_profit_per_sq`) is never overridden.

⚠️ MEASURE BEFORE YOU SET IT. Jon's framing was a one-square job whose overhead alone is
~$1,400. But Tim's sliding scale only reaches $2,500 of profit at ~23 squares, so a $2,500 floor
reaches ordinary jobs, not just the T&M edge case. Measured against his own 29 homes:

    314 5th St.        16.5 sq   $14,085 -> $14,605   +$520
    892 Camellia Dr.   21.5 sq   $17,095 -> $17,230   +$135

Two of twenty-nine of HIS OWN SOLD HOMES get more expensive. Confirm the number with Tim before
seeding it, or pick a value that only bites where he says it should.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/seed_min_margin.py --dollars 2500 [--apply]
       (prints the impact and changes nothing unless --apply is passed)
"""
from __future__ import annotations

import argparse
import sys

BRANCH_ORDER = ("jupiter", "miami", "naples")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dollars", type=float, required=True,
                        help="minimum profit dollars per job; 0 disables the floor")
    parser.add_argument("--apply", action="store_true",
                        help="write a new config version (otherwise print and exit)")
    args = parser.parse_args()

    from sqlalchemy import select

    from app.models import PricingConfig, SessionLocal
    from core.pricing_config import compute_hash, load_config

    value = args.dollars or None

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
        if active.config.get("min_margin_dollars") == value:
            print(f"{branch}: already {value} — skipped")
            continue

        cfg = dict(active.config)
        cfg["min_margin_dollars"] = value
        # Smallest job size at which the sliding scale clears the floor on its own — anything
        # under this gets repriced, which is the number worth eyeballing before applying.
        pc = load_config(cfg)
        bites_below = next((sq for sq in range(1, 201)
                            if value and pc.profit_per_sq(float(sq)) * sq >= value), None)
        print(f"{branch}: min_margin_dollars {active.config.get('min_margin_dollars')} -> {value}"
              + (f"  (repricing every job under ~{bites_below} squares)" if bites_below else ""))

        if not args.apply:
            continue
        active.is_active = False
        s.flush()
        new = PricingConfig(
            branch=branch, version=active.version + 1,
            label=f"min_margin_dollars={value}",
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
