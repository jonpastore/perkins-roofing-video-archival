#!/usr/bin/env python3
"""Add the newly-confirmed tile brands (Verea Spanish 'S', Verea Caribbean, Other/Custom —
rake units confirmed 2026-07-21, docs/estimating/tile-roof-cuts-pricing-linkage.md) into each
branch's active pricing config as a NEW config version (immutable versioning — never mutates
the active row). Same pattern as reconcile_low_slope_pricing.py.

Scope: ONLY adds missing keys under cuts_calc.tile_brands. Never overwrites an existing brand
entry and never touches any other config key. Idempotent: skips a branch that already has all
three brand keys.

Usage:
    DB_URL=postgresql+psycopg://... PYTHONPATH=. .venv/bin/python scripts/reconcile_tile_brands.py --dry-run
    DB_URL=postgresql+psycopg://... PYTHONPATH=. .venv/bin/python scripts/reconcile_tile_brands.py
"""
from __future__ import annotations

import argparse
import copy
import sys

NEW_BRANDS = {
    "verea_s":         {"label": "Verea Spanish \"S\"", "field": None, "rake": 5.78},
    "verea_caribbean": {"label": "Verea Caribbean",     "field": None, "rake": 19.14},
    "other":           {"label": "Other / Custom",      "field": None, "rake": 45.00},
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

        cc = active.config.get("cuts_calc")
        if not cc:
            print(f"{branch}: no cuts_calc block — skipped (run seed_cuts_calc_config.py first)", file=sys.stderr)
            continue

        existing_brands = cc.get("tile_brands") or {}
        missing = {k: v for k, v in NEW_BRANDS.items() if k not in existing_brands}
        if not missing:
            print(f"{branch}: all new tile brands already present — skipped")
            continue

        print(f"\n{branch}: v{active.version} -> v{active.version + 1}  (+{len(missing)} tile brand(s))")
        for k, v in missing.items():
            print(f"  cuts_calc.tile_brands.{k}: <absent> -> {v!r}")

        if args.dry_run:
            continue

        cfg = copy.deepcopy(active.config)
        cfg["cuts_calc"]["tile_brands"] = {**cfg["cuts_calc"].get("tile_brands", {}), **missing}

        # Deactivate + flush before inserting the new active version —
        # uq_pricing_configs_active_branch is a non-deferrable partial unique index.
        new_version = active.version + 1
        active.is_active = False
        s.flush()
        new = PricingConfig(
            branch=branch, version=new_version,
            label=f"{active.label or branch} + tile brands (Verea/Other 2026-07-21)",
            config=cfg, config_hash=compute_hash(cfg),
            is_active=True, created_by="reconcile_tile_brands.py", tenant_id=active.tenant_id,
        )
        s.add(new)
        s.flush()
        print(f"{branch}: created + activated v{new.version} (id={new.id})")

    if not args.dry_run:
        s.commit()
    s.close()


if __name__ == "__main__":
    main()
