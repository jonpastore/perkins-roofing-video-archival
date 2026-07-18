#!/usr/bin/env python3
"""Seed Tim's decoded 'Custom Tile Calc' cut calculator into every branch's active pricing
config as a NEW config version (immutable versioning — never mutates the active row).

The cuts_calc block is zone-scoped internally (FBC calibrated from Tim's live sheet; HVHZ
left null → graceful flat-base fallback until Tim's HVHZ detail is captured). Decode +
derivation: docs/plans/2026-07-17-cut-calculator-spec.md.

Usage:
    DB_URL=postgresql+psycopg://... PYTHONPATH=. .venv/bin/python scripts/seed_cuts_calc_config.py [--dry-run]

Idempotent: skips a branch whose active config already carries cuts_calc.
"""
from __future__ import annotations

import argparse
import copy
import sys

CUTS_CALC = {
    "_source": "Tim 'Custom Tile Calc' tab, decoded 2026-07-17; docs/plans/2026-07-17-cut-calculator-spec.md",
    "rounding": {"eaves": 10, "hips_ridges": 10, "valleys": 50, "rakes": 10, "wall_flashings": 10},
    "fixed_per_sq": {"FBC": 519, "HVHZ": None},
    "coeff": {"drip_a": 1.10, "drip_b": 0.46, "valley_a_div": 50, "valley_a_rate": 90,
              "valley_b_div": 65, "valley_b_rate": 151, "hipridge_tile_rate": 2.30,
              "eave_closure_rate": 3.10, "field_tiles_addon": 5},
    "standard_tile": {"field": 147.59, "rake": 4.82},
    "default_tile_brand": "eagle",
    "tile_brands": {
        "eagle":    {"label": "Eagle (concrete, standard)", "field": 147.59, "rake": 4.82},
        "crown":    {"label": "Crown (concrete)",           "field": 143.19, "rake": 4.30},
        "westlake": {"label": "West Lake (concrete)",        "field": 145.71, "rake": 4.50},
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
        if active.config.get("cuts_calc"):
            print(f"{branch}: cuts_calc already configured — skipped")
            continue
        cfg = copy.deepcopy(active.config)
        cfg["cuts_calc"] = CUTS_CALC
        if args.dry_run:
            print(f"{branch}: would create v{active.version + 1} with cuts_calc (from v{active.version})")
            continue
        # Deactivate + flush before inserting the new active version —
        # uq_pricing_configs_active_branch is a partial unique index (one active per branch).
        new_version = active.version + 1
        active.is_active = False
        s.flush()
        new = PricingConfig(
            branch=branch, version=new_version,
            label=f"{active.label or branch} + cut calculator (Tim sheet 7/17)",
            config=cfg, config_hash=compute_hash(cfg),
            is_active=True, created_by="seed_cuts_calc_config.py", tenant_id=1,
        )
        s.add(new)
        s.flush()
        print(f"{branch}: created + activated v{new.version} (id={new.id})")
    if not args.dry_run:
        s.commit()
    s.close()


if __name__ == "__main__":
    main()
