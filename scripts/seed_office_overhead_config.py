#!/usr/bin/env python3
"""Seed the office-burn overhead model + the four zone-keyed adders as a new config version.

Both corrections come from reading Tim's LIVE sloped calculator with FORMULA render on
2026-07-25 and diffing every value against the active config.

1. Four adders shipped as bare scalars holding the HVHZ (Miami) value while every price around
   them was keyed {FBC, HVHZ}, so FBC jobs took Miami's number — 7/12+ billed $200/sq against
   his FBC tab's $305.

2. Overhead is the office's gross daily cost divided across working days, so it belongs to the
   BRANCH. His sheet states OH Basis = burn / men; multiplying back gives Jupiter ~$1,400/day
   (7 x $200) and Miami ~$4,140/day (12 x $345). The per-series rates he emailed 2026-07-24
   came with 30 Palm Beach homes, so they are Jupiter's — and every branch carried them.

   What scales is the BASIS, not the burn: Miami burns 2.98x Jupiter but runs 12 men to 7, so
   the same roof takes fewer days and his published per-square OH differs by 1.73x. Jupiter's
   factor is therefore exactly 1.0 and it reprices to the dollar — verified against his 29
   homes (66% within 0.5d, 93% within 1.0d, mean 0.53 — all unchanged).

NAPLES is deliberately left without office keys: we have no burn figure for it, and absent
those keys the rates pass through unscaled, so Naples keeps quoting exactly as it does today
while still picking up the zone-keyed adder fix. Do not invent a number for it — ask Tim.

Idempotent: a branch already carrying the office keys and dict-shaped adders is skipped.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/seed_office_overhead_config.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys

# Verified against the live sheet 2026-07-25. HVHZ = the "Tim (HVHZ)" tab (Miami),
# FBC = the "FBC (Palm / Lee / St. Lucie)" tab (Jupiter).
ZONED_ADDS = {
    "pitch_7_12_add": {"HVHZ": 200, "FBC": 305},
    "tile_demo_add": {"HVHZ": 40, "FBC": 30},
    "metal_demo_add": {"HVHZ": 60, "FBC": 45},
    "winterguard_add": {"HVHZ": 140, "FBC": 150},
}

# $/man-day of the office the base daily_overhead_rates were measured in (Jupiter, 7-men column).
OH_BASIS_REFERENCE = 200

# Per-branch office burn. men = the crew-size column that branch prices from.
OFFICE = {
    "jupiter": {"office_daily_overhead": 1400, "office_men": 7},    # 7 x $200  -> factor 1.000
    "miami": {"office_daily_overhead": 4140, "office_men": 12},     # 12 x $345 -> factor 1.725
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

        cfg = dict(active.config)
        added = []
        for key, zoned in ZONED_ADDS.items():
            if not isinstance(cfg.get(key), dict):
                cfg[key] = dict(zoned)
                added.append(key)
        office = OFFICE.get(branch)
        if office and not cfg.get("office_daily_overhead"):
            cfg.update(office)
            cfg["office_oh_basis_reference"] = OH_BASIS_REFERENCE
            added.append("office_daily_overhead")
        elif not office:
            print(f"{branch}: no office burn figure — rates left unscaled (pending Tim)")

        if not added:
            print(f"{branch}: already carries the office model + zoned adders — skipped")
            continue

        label = f"office overhead + zoned adders ({', '.join(added)})"
        if args.dry_run:
            print(f"{branch}: would create v{active.version + 1} adding {added} "
                  f"(from v{active.version})")
            continue

        # Deactivate + FLUSH before inserting: uq_pricing_configs_active_branch is a
        # non-deferrable unique constraint on (branch, is_active).
        new_version = active.version + 1
        active.is_active = False
        s.flush()
        new = PricingConfig(
            branch=branch, version=new_version, label=label,
            config=cfg, config_hash=compute_hash(cfg),
            is_active=True, created_by="seed_office_overhead_config.py", tenant_id=1,
        )
        s.add(new)
        s.flush()
        print(f"{branch}: created + activated v{new.version} (id={new.id}) — {label}")
    if not args.dry_run:
        s.commit()
    s.close()


if __name__ == "__main__":
    main()
