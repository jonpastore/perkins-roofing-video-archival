#!/usr/bin/env python3
"""Revert MIAMI to overhead factor 1.0 — the 1.725x multiplier was never validated.

R2 architect review, 2026-07-25 (CRITICAL C1).

v14 seeded miami with office_daily_overhead=4140 / office_men=12, scaling its daily overhead
rates by 1.725. The A/B that supposedly validated it ran scripts/tim_quote_breakdown.py over
Tim's 29 homes — every one of which is Palm Beach County, i.e. the JUPITER branch, whose factor
is exactly 1.0 by construction. The test was mathematically incapable of detecting an error in
the only branch the change moves.

Measured on a 30 SQ HVHZ 13" tile tear-off:

    before (factor 1.0)     overhead $212/sq   project $37,200   $1,240/sq
    after  (factor 1.725)   overhead $365/sq   project $41,804   $1,393/sq

Two independent checks say the new number is too high:
  * Tim's own published guide is sloped_overhead["HVHZ"]["13_tile"] = $270/sq. Before the change
    we were 21% UNDER it (conservative); after, 35% OVER it.
  * The ~$1,228/sq Knowify sold median for 25-35 SQ tile is Miami-weighted (Perkins HQ is
    575 NW 152 St, Miami). Jupiter lands on it at $1,227; Miami went to +13%. The change moved
    the branch that generated the calibration target away from the target.

Dropping the two keys returns miami to the pass-through branch in
PricingConfig.daily_overhead_rates(), which is the already-tested inert path. The zone-keyed
adder fixes from v14 are KEPT — those were verified against the sheet and are unrelated.

Restore the multiplier only once it is fitted from MIAMI sold jobs, the same way Jupiter earned
its 1.0. Until then Jupiter and Naples are unaffected: Jupiter's factor is 1.0 either way, and
Naples never carried the keys.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/revert_miami_office_overhead.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys

BRANCH = "miami"
DROP_KEYS = ("office_daily_overhead", "office_men", "office_oh_basis_reference")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from sqlalchemy import select

    from app.models import PricingConfig, SessionLocal
    from core.pricing_config import compute_hash, load_config

    s = SessionLocal()
    s.info["tenant_id"] = 1
    active = s.execute(select(PricingConfig).where(
        PricingConfig.branch == BRANCH, PricingConfig.is_active == True  # noqa: E712
    )).scalar_one_or_none()
    if active is None:
        print(f"{BRANCH}: no active config", file=sys.stderr)
        raise SystemExit(1)

    cfg = dict(active.config)
    dropped = [k for k in DROP_KEYS if k in cfg]
    if not dropped:
        print(f"{BRANCH}: already on factor 1.0 (no office keys) — nothing to do")
        return
    for k in dropped:
        cfg.pop(k)

    before = load_config(active.config).daily_overhead_rates()
    after = load_config(cfg).daily_overhead_rates()
    print(f"{BRANCH} daily_overhead_rates")
    for series in sorted(after):
        print(f"  {series:20} {before.get(series):>10,.2f} -> {after[series]:>10,.2f}")

    if args.dry_run:
        print(f"{BRANCH}: would create v{active.version + 1} dropping {dropped}")
        return

    # Deactivate + FLUSH before insert: uq_pricing_configs_active_branch is non-deferrable.
    active.is_active = False
    s.flush()
    new = PricingConfig(
        branch=BRANCH, version=active.version + 1,
        label="revert office-burn scaling (R2 C1: 1.725x unvalidated)",
        config=cfg, config_hash=compute_hash(cfg),
        is_active=True, created_by="revert_miami_office_overhead.py", tenant_id=1,
    )
    s.add(new)
    s.flush()
    print(f"{BRANCH}: created + activated v{new.version} (id={new.id})")
    s.commit()
    s.close()


if __name__ == "__main__":
    main()
