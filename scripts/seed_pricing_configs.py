#!/usr/bin/env python3
"""Seed the Exhibit B pricing config fixture for tenant 1 (miami/jupiter/naples).

Idempotent: skips branches where a config already exists for tenant 1.
Prints a post-seed assertion confirming 3 active configs.

Usage:
    python scripts/seed_pricing_configs.py
    python scripts/seed_pricing_configs.py --check   # assertion only, no writes

Rollout:
    1. Apply migrations: python scripts/apply_migrations_connector.py
    2. Seed:             python scripts/seed_pricing_configs.py
    3. Verify:           python scripts/seed_pricing_configs.py --check
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE_PATH = ROOT / "infra" / "fixtures" / "pricing_config_exhibit_b.json"
BRANCHES = ["miami", "jupiter", "naples"]
TENANT_ID = 1
LABEL = "Exhibit B 2026-Q3"
CREATED_BY = "system@perkins"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _compute_hash(config_dict: dict) -> str:
    from core.pricing_config import compute_hash
    return compute_hash(config_dict)


def seed(check_only: bool = False) -> int:
    """Seed configs. Returns 0 on success, 1 on failure."""
    from sqlalchemy import select

    from app.models import PricingConfig, SessionLocal, init_db

    init_db()

    config_dict = _load_fixture()
    config_hash = _compute_hash(config_dict)

    seeded = []
    skipped = []

    with SessionLocal() as db:
        for branch in BRANCHES:
            existing = db.execute(
                select(PricingConfig).where(
                    PricingConfig.tenant_id == TENANT_ID,
                    PricingConfig.branch == branch,
                )
            ).scalars().first()

            if existing is not None:
                skipped.append(branch)
                continue

            if check_only:
                print(f"MISSING  branch={branch} (would seed)")
                seeded.append(branch)
                continue

            row = PricingConfig(
                tenant_id=TENANT_ID,
                branch=branch,
                version=1,
                label=LABEL,
                config=config_dict,
                config_hash=config_hash,
                is_active=True,
                created_by=CREATED_BY,
            )
            db.add(row)
            seeded.append(branch)

        if not check_only and seeded:
            db.commit()

    if not check_only:
        for b in seeded:
            print(f"SEEDED   branch={b}  hash={config_hash[:16]}...")
        for b in skipped:
            print(f"SKIPPED  branch={b}  (already exists)")

    # Post-seed assertion
    with SessionLocal() as db:
        active_count = db.execute(
            select(PricingConfig).where(
                PricingConfig.tenant_id == TENANT_ID,
                PricingConfig.is_active == True,  # noqa: E712
            )
        ).scalars().all()

    active_branches = sorted(r.branch for r in active_count if r.branch in BRANCHES)
    expected = sorted(BRANCHES)

    if active_branches == expected:
        print(f"\nOK  3 active configs (tenant={TENANT_ID}): {', '.join(active_branches)}")
        print("3/5 golden fixtures (2 pending Tim OI-1)")
        return 0
    else:
        missing = sorted(set(expected) - set(active_branches))
        print(f"\nFAIL  active configs {active_branches} != expected {expected}; missing: {missing}")
        return 1


if __name__ == "__main__":
    check_only = "--check" in sys.argv
    sys.exit(seed(check_only=check_only))
