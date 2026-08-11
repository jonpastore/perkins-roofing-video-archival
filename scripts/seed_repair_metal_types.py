#!/usr/bin/env python3
"""Break repair.roof_types' generic "metal" into the metal profiles Perkins actually repairs.

Jon, 2026-08-11: "in the estimate tool for select the metal roof type there is no option for
select standing seam roof type — we have metal but we need to be able to choose metal type."

REPLACEMENT mode already offers `standing_seam_metal` (it is a key in sloped_base_cost_lm).
REPAIR mode is the one with the gap: repair.roof_types is ['shingle','tile','metal','flat'], so a
standing-seam repair and a 5V-crimp repair are the same word on the estimate.

SAFE TO ADD, and this is the whole reason the change is config-only: `core.estimator
.estimate_repair` prices a repair as days x daily_labor_rate + materials. roof_type is VALIDATED
against this list and never multiplies anything, so new categories carry no new price data and
nothing here invents a number of Tim's. It changes what an estimator can say, not what anything
costs.

Generic "metal" is KEPT. Repair estimates already saved against it would fail validation if it
disappeared, and "the customer could not tell me which profile" stays a legitimate answer.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/seed_repair_metal_types.py [--apply]
       (prints the change and rolls back unless --apply is passed)
"""
from __future__ import annotations

import argparse
import json
import os

# Ordered most-common-first for South Florida. Standing seam is the profile Jon named and the one
# Perkins specifies (see the warranty guide's 1.5" mechanical seam comparison).
METAL_TYPES = [
    "metal_standing_seam",   # mechanically seamed or snap lock, concealed clips
    "metal_5v_crimp",        # exposed-fastener 5V — very common on older FL homes
    "metal_corrugated",      # exposed-fastener corrugated / ag panel
    "metal_tile",            # stamped metal tile profile
]


def new_roof_types(existing: list[str]) -> list[str]:
    """Insert the metal profiles after generic 'metal', preserving order and dropping dupes."""
    out: list[str] = []
    for key in existing:
        if key in out:
            continue
        out.append(key)
        if key == "metal":
            out.extend(t for t in METAL_TYPES if t not in existing and t not in out)
    # 'metal' missing entirely would mean this config is not shaped the way we think it is.
    if "metal" not in existing:
        raise SystemExit(f"repair.roof_types has no 'metal' entry: {existing!r} — check the config")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write + activate a new config version")
    args = ap.parse_args()

    from sqlalchemy import create_engine, text  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    from app.models import PricingConfig  # noqa: PLC0415
    from core.pricing_config import compute_hash  # noqa: PLC0415

    s = Session(create_engine(os.environ["DB_URL"]))
    s.execute(text("set app.tenant_id='1'"))

    for branch in ("jupiter", "miami", "naples"):
        active = s.query(PricingConfig).filter(
            PricingConfig.branch == branch, PricingConfig.is_active == True).one()  # noqa: E712
        old = active.config if isinstance(active.config, dict) else json.loads(active.config)
        existing = list((old.get("repair") or {}).get("roof_types") or [])
        updated = new_roof_types(existing)

        print(f"{branch:8} v{active.version}")
        print(f"         before: {existing}")
        print(f"         after : {updated}")
        if existing == updated:
            print("         no change")
            continue

        new = {**old, "repair": {**(old.get("repair") or {}), "roof_types": updated}}
        if not args.apply:
            continue
        active.is_active = False
        s.flush()
        row = PricingConfig(
            branch=branch, version=active.version + 1,
            label="repair metal profiles (Jon 2026-08-11)",
            config=new, config_hash=compute_hash(new),
            is_active=True, created_by="seed_repair_metal_types.py", tenant_id=1,
        )
        s.add(row)
        s.flush()
        print(f"         created + activated v{row.version} (id={row.id})")

    if args.apply:
        s.commit()
        print("\napplied.")
    else:
        s.rollback()
        print("\n(dry run — nothing written; pass --apply to commit)")
    s.close()


if __name__ == "__main__":
    main()
