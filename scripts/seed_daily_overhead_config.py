#!/usr/bin/env python3
"""Seed the v2 time-based-overhead fields (Zoom 2026-07-17) plus the fitted days-from-squares
day model (2026-07-24) into each branch's active pricing config as a new immutable version.
Rates are Tim's stated daily targets; the day model is fit from his 30-home time log.

Prod configs seeded on 2026-07-10 predate these fields, so the "By time (days)" quote
mode 422s with "Valid series: []". Idempotent per key: adds only what a branch is missing,
skips branches already carrying both.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/seed_daily_overhead_config.py [--dry-run]
"""
from __future__ import annotations

import argparse
import copy
import sys

# Tim's daily overhead targets ($/day on-site) + minimum-profit floors, verbatim from the
# 2026-07-17 Zoom [09:15-12:54] (and matching infra/fixtures/pricing_config_exhibit_b.json).
DAILY = {
    "daily_overhead_rates": {
        "demo_dry_in_flat": 1050,
        "tile": 745,
        "metal": 850,
        "shingle": 700,
    },
    "daily_overhead_weeks_rounding_mode": "ceil",
    "weekly_profit_floor": 2500,   # Tim: "at least $2,500 a week we're on the job"
    "job_profit_floor": 2500,
}

# days = setup + rate x SQ — least-squares fit over Tim's 30-home "TIME LEARNING (Overhead)"
# log; see docs/ROOFR_OVERHEAD_TIERS.md. Lets the quote-builder auto-fill labor days from
# squares instead of silently dropping back to per-square overhead.
DAY_MODEL = {
    "daily_overhead_day_model": {
        "demo_series": "demo_dry_in_flat",
        "install_series_by_roof_type": {
            "13_tile": "tile",
            "barrel_tile": "tile",
            "standing_seam_metal": "metal",
            "3tab_shingle": "shingle",
            "dimensional_shingle": "shingle",
        },
        "series": {
            "demo_dry_in_flat": {"setup": 1.31, "rate": 0.044},   # R² 0.37 — noisy
            "shingle": {"setup": 1.06, "rate": 0.024},            # R² 0.38 — noisy
            "tile": {"setup": 0.45, "rate": 0.129},               # R² 0.70
            "metal": {"setup": 0.59, "rate": 0.106},              # R² 0.66
        },
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from sqlalchemy import select

    from app.models import PricingConfig, SessionLocal
    from core.pricing_config import compute_hash

    s = SessionLocal()
    s.info["tenant_id"] = 1
    branches = [r[0] for r in s.execute(select(PricingConfig.branch).distinct()).all()]
    for branch in sorted(branches):
        active = s.execute(select(PricingConfig).where(
            PricingConfig.branch == branch, PricingConfig.is_active == True  # noqa: E712
        )).scalar_one_or_none()
        if active is None:
            print(f"{branch}: no active config — skipped", file=sys.stderr)
            continue
        missing = {}
        if not active.config.get("daily_overhead_rates"):
            missing.update(DAILY)
        if not active.config.get("daily_overhead_day_model"):
            missing.update(DAY_MODEL)
        if not missing:
            print(f"{branch}: daily_overhead + day model already configured — skipped")
            continue
        cfg = copy.deepcopy(active.config)
        cfg.update(missing)
        added = ", ".join(sorted(missing))
        if args.dry_run:
            print(f"{branch}: would create v{active.version + 1} adding {added} (from v{active.version})")
            continue
        # Deactivate the current version and FLUSH before inserting the new active one —
        # uq_pricing_configs_active_branch (one active per branch) is a non-deferrable
        # partial unique index, so the two must never both be active in the same statement.
        new_version = active.version + 1
        active.is_active = False
        s.flush()
        new = PricingConfig(
            branch=branch, version=new_version,
            label=f"{active.label or branch} + {added}",
            config=cfg, config_hash=compute_hash(cfg),
            is_active=True, created_by="seed_daily_overhead_config.py", tenant_id=1,
        )
        s.add(new)
        s.flush()
        print(f"{branch}: created + activated v{new.version} (id={new.id})")
    if not args.dry_run:
        s.commit()
    s.close()


if __name__ == "__main__":
    main()
