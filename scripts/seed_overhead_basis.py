#!/usr/bin/env python3
"""Flip overhead to Tim's model: ONE daily number per branch x the days the job runs.

Jon, 2026-07-28: *"use tim's numbers, we validated it in the transcripts and his own quote sheet
showing 1400/day OH. stop blocking that."*

The mechanism shipped 5219dd9 behind `overhead_basis`, defaulted to the legacy per-series rates
because flat $1,400/day prices Tim's 21 sold jobs +13.3% median. That comparison is now closed as
a business decision, not an engineering one: the branch burn is a FLOOR (monthly fixed overhead,
computed outside this system, / 20 working days) and margin is the only negotiable lever. His sold
prices recovering $840-950/day is the margin squeeze (Jarvis #431), not a reason to quote below the
burn.

    Jupiter  $28,000/mo / 20 = $1,400/day   (Tim, 2026-07-27 call; matches his sheet's 7 x $200)
    Miami    $85,000/mo / 20 = $4,250/day   (same call, same arithmetic)
    Naples   ---- never stated ----

NAPLES defaults to Jupiter's $1,400 and that is a CARRY-FORWARD, not a measurement. Naples has no
burn figure and today quotes on Jupiter's per-series rates unscaled (OI-12), so $1,400 keeps it
inheriting exactly what it already inherits instead of raising ConfigError on every Naples quote.
Pass --naples-burn 0 to leave Naples on the series basis instead. Still ask Tim.

`office_men` / `office_oh_basis_reference` go INERT under this basis (they exist only to rescale
the per-series rates). Left in place so a flip back reprices identically.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/seed_overhead_basis.py [--apply]
       (prints the repricing and changes nothing unless --apply is passed)
"""
from __future__ import annotations

import argparse
import sys

BRANCH_ORDER = ("jupiter", "miami", "naples")

# Representative live quote shapes, priced both ways so the repricing is visible before it ships.
SHAPES = (
    ("20 SQ tile FBC", dict(code_zone="FBC", slope_type="sloped", roof_type="13_tile",
                            num_squares=20.0, project_kind="residential", demo=True)),
    ("30 SQ tile FBC", dict(code_zone="FBC", slope_type="sloped", roof_type="13_tile",
                            num_squares=30.0, project_kind="residential", demo=True)),
    ("30 SQ shingle FBC", dict(code_zone="FBC", slope_type="sloped",
                               roof_type="dimensional_shingle", num_squares=30.0,
                               project_kind="residential", demo=True)),
    ("45 SQ metal FBC", dict(code_zone="FBC", slope_type="sloped",
                             roof_type="standing_seam_metal", num_squares=45.0,
                             project_kind="residential", demo=True)),
)


def _price(cfg_raw: dict, shape: dict) -> tuple[float, float]:
    """(overhead, project_total) for one shape, with days derived from geometry."""
    from core.estimator import QuoteInput, estimate
    from core.pricing_config import load_config
    r = estimate(load_config(cfg_raw), QuoteInput(overhead_mode="daily", **shape))
    oh = next((li["amount"] for li in r["line_items_detail"] if li["key"] == "overhead"), 0.0)
    return oh, r["project_total"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--naples-burn", type=float, default=1400.0,
                        help="Naples daily burn; 0 leaves Naples on the series basis (default 1400,"
                             " carried forward from Jupiter — Tim has never stated Naples")
    parser.add_argument("--off", action="store_true",
                        help="revert to the per-series basis")
    parser.add_argument("--apply", action="store_true",
                        help="write a new config version (otherwise print and exit)")
    parser.add_argument("--branches", default="",
                        help="comma-separated branches to touch; default all. Miami is normally "
                             "excluded from a --off flip: putting Jupiter's four per-day rates on "
                             "a $4,257/day office has no Miami evidence behind it (both 2026-07-30 "
                             "adversarial reviews flag it explicitly)")
    args = parser.parse_args()
    only = {b.strip() for b in args.branches.split(",") if b.strip()}

    from sqlalchemy import select

    from app.models import PricingConfig, SessionLocal
    from core.pricing_config import compute_hash

    want = "series" if args.off else "branch"
    s = SessionLocal()
    s.info["tenant_id"] = 1
    branches = [r[0] for r in s.execute(select(PricingConfig.branch).distinct()).all()]
    for branch in sorted(branches, key=lambda b: (BRANCH_ORDER + (b,)).index(b)):
        if only and branch not in only:
            print(f"{branch}: not in --branches — untouched")
            continue
        active = s.execute(select(PricingConfig).where(
            PricingConfig.branch == branch, PricingConfig.is_active == True  # noqa: E712
        )).scalar_one_or_none()
        if active is None:
            print(f"{branch}: no active config", file=sys.stderr)
            continue

        before = dict(active.config)
        cfg = dict(before)
        cfg["overhead_basis"] = want
        if want == "branch" and not cfg.get("office_daily_overhead"):
            if not args.naples_burn:
                print(f"{branch}: no office_daily_overhead and none supplied — LEFT ON series")
                continue
            cfg["office_daily_overhead"] = args.naples_burn
        if cfg == before:
            print(f"{branch}: already {want} — skipped")
            continue

        burn = cfg.get("office_daily_overhead")
        print(f"\n{branch}: overhead_basis {before.get('overhead_basis') or 'series'} -> {want}"
              f"  (${burn:,.0f}/day)")
        for name, shape in SHAPES:
            oh0, tot0 = _price(before, shape)
            oh1, tot1 = _price(cfg, shape)
            pct = (tot1 - tot0) / tot0 * 100 if tot0 else 0.0
            print(f"    {name:<20} OH ${oh0:>8,.0f} -> ${oh1:>8,.0f}   "
                  f"total ${tot0:>9,.0f} -> ${tot1:>9,.0f}  ({pct:+.1f}%)")

        if not args.apply:
            continue
        active.is_active = False
        s.flush()
        new = PricingConfig(
            branch=branch, version=active.version + 1,
            label=f"overhead_basis={want} (${burn:,.0f}/day)" if want == "branch"
                  else "overhead_basis=series",
            config=cfg, config_hash=compute_hash(cfg),
            is_active=True, created_by="seed_overhead_basis.py", tenant_id=1,
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
