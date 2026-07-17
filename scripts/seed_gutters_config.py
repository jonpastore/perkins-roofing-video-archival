#!/usr/bin/env python3
"""Seed Tim's gutter price list (email 2026-07-17) into every branch's active pricing
config as a NEW config version (immutable versioning — never mutates the active row).

Usage:
    DB_URL=postgresql+psycopg://... PYTHONPATH=. .venv/bin/python scripts/seed_gutters_config.py [--dry-run]

Idempotent-ish: skips a branch whose active config already carries gutters.styles.
"""
from __future__ import annotations

import argparse
import copy
import sys

GUTTERS = {
    "styles": {
        "k6_alum": {"label": '6" Alum K-Style (w/ 3x4 corrugated DS)',
                    "per_lf": 11.55, "two_story_per_lf": 12.95, "elbow_each": 7},
        "k7_alum": {"label": '7" Alum K-Style (w/ 4x5 corrugated DS)',
                    "per_lf": 16.80, "two_story_per_lf": 18.20, "elbow_each": 9},
        "box6_comm": {"label": '6" Commercial Alum Box (w/ 3x4 box DS)', "per_lf": 15.40},
        "box7_comm": {"label": '7" Commercial Alum Box (w/ 4x4 box DS)', "per_lf": 21.00},
        "halfround_alum": {"label": 'Half-Round Alum (w/ 4" round DS)', "per_lf": 14.00},
        "k6_copper": {"label": '6" Copper K-Style (w/ 3x4 corrugated DS)', "per_lf": 50.00},
        "k7_copper": {"label": '7" Copper K-Style (w/ 4x5 corrugated DS)', "per_lf": 70.00},
        "halfround_copper": {"label": 'Copper Half-Round (w/ 4" round DS)', "per_lf": 55.00},
    },
    "removal_per_lf": 3.85,
    "leaf_guard_std_per_lf": 9.80,        # Bulldog (Lansing)
    "leaf_guard_upgraded_per_lf": 14.00,  # Hydroflow
    "leaderhead_res_each": 98,
    "leaderhead_comm_each": 168,
    "small_job_add_per_lf": 2.00,         # Tim: "under 100' add $2 per LF or more"
    "small_job_threshold_lf": 100,
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
        if (active.config.get("gutters") or {}).get("styles"):
            print(f"{branch}: gutters already configured — skipped")
            continue
        cfg = copy.deepcopy(active.config)
        cfg["gutters"] = GUTTERS
        if args.dry_run:
            print(f"{branch}: would create v{active.version + 1} with gutters (from v{active.version})")
            continue
        # Deactivate + flush before inserting the new active version —
        # uq_pricing_configs_active_branch is non-deferrable (one active per branch).
        new_version = active.version + 1
        active.is_active = False
        s.flush()
        new = PricingConfig(
            branch=branch, version=new_version,
            label=f"{active.label or branch} + gutters (Tim email 7/17)",
            config=cfg, config_hash=compute_hash(cfg),
            is_active=True, created_by="seed_gutters_config.py", tenant_id=1,
        )
        s.add(new)
        s.flush()
        print(f"{branch}: created + activated v{new.version} (id={new.id})")
    if not args.dry_run:
        s.commit()
    s.close()


if __name__ == "__main__":
    main()
