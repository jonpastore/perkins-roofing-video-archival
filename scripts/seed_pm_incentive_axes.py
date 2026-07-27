#!/usr/bin/env python3
"""Bring prod's pricing config up to the git fixture — PM incentive first, it is live money.

A 35-square Palm Beach RESIDENTIAL re-roof charges $50 of PM incentive where Tim's live sheet
(FBC N7:O9) says $100, because we keyed the top two FBC bands as commercial-only and the lookup
falls back to `residential_lt20`. `pm_incentive` sits inside `project_total`, so this is money on
the customer's price, not a badge. The same defect 422s a small Miami COMMERCIAL job.

`e20aa18` re-keyed it to the axes his sheet actually uses — Miami/HVHZ by PROJECT KIND only
(Residential $150 / Commercial $300 at any size), Palm Beach/FBC by SIZE only (<20 $50, 20-50 $100,
>50 $250, for BOTH kinds) — and prod never got it.

Five other paths are also git-only and ship in the same version rather than as six separate
activations. Every one is sourced from the LIVE sheet:

  cuts_calc.tile_brands.verea_caribbean.rake   19.14 -> 13.98   (Custom Tile Calc E42)
  cuts_calc.tile_brands.verea_caribbean.field   null -> 230.00  (D39)
  cuts_calc.tile_brands.verea_s.field           null -> 297.04
  cuts_calc.tile_brands.other.field             null -> 310.00
  low_slope.overhead.FBC.tpo_oh                  135 -> 125     (comment: "Tim (FBC) - $125")
  low_slope.insulation_by_thickness / stockwmeier_* / default_flat_system, profit_mode_default

This is a MERGE onto the active config, never a fixture overwrite: prod carries keys the fixture
does not (`office_daily_overhead`, `office_men`, `office_oh_basis_reference` on jupiter, and the
enforced profit floor), and replacing wholesale would silently drop them.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/seed_pm_incentive_axes.py [--apply]
       (prints the diff and the money impact; changes nothing unless --apply is passed)
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

FIXTURE = Path("infra/fixtures/pricing_config_exhibit_b.json")
BRANCH_ORDER = ("jupiter", "miami", "naples")

# (path, "why") — every value is taken from the fixture, so git stays the source of truth.
PATHS: list[tuple[tuple[str, ...], str]] = [
    (("pm_incentive",), "re-key to the sheet's real axes (FBC size-only, HVHZ kind-only)"),
    (("cuts_calc", "tile_brands", "verea_caribbean", "rake"), "live Custom Tile Calc E42"),
    (("cuts_calc", "tile_brands", "verea_caribbean", "field"), "live Custom Tile Calc D39"),
    (("cuts_calc", "tile_brands", "verea_s", "field"), "live Custom Tile Calc"),
    (("cuts_calc", "tile_brands", "other", "field"), "live Custom Tile Calc"),
    (("low_slope", "overhead", "FBC", "tpo_oh"), "live comment: Tim (FBC) - $125"),
    (("low_slope", "insulation_by_thickness"), "low-slope comment audit"),
    (("low_slope", "stockmeier_min_sq"), "live M29: min 12 SQ"),
    (("low_slope", "stockmeier_under_min_material_per_sq"), "live M29: $390/sq under min"),
    (("low_slope", "default_flat_system"), "all three mixed proposals sold Polyglass SAP"),
    (("profit_mode_default",), "sliding scale is the default profit mode"),
    (("exhibit_version",), "version stamp"),
]

_MISSING = object()


def dig(d: dict, path: tuple[str, ...]):
    cur = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return _MISSING
        cur = cur[k]
    return cur


def put(d: dict, path: tuple[str, ...], value) -> None:
    cur = d
    for k in path[:-1]:
        cur = cur.setdefault(k, {})
    cur[path[-1]] = value


def fmt(v) -> str:
    if v is _MISSING:
        return "(absent)"
    return json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else str(v)


def pm_probe(pc) -> list[str]:
    """The cases the old keying got wrong, priced through the real resolver."""
    out = []
    for zone, kind, sq in (("FBC", "residential", 35.0), ("FBC", "residential", 60.0),
                           ("FBC", "commercial", 35.0), ("HVHZ", "residential", 35.0),
                           ("HVHZ", "commercial", 10.0)):
        try:
            val = f"${pc.pm_incentive(zone, kind, sq):,.0f}"
        except Exception as exc:  # ConfigError on the un-quotable small commercial job
            val = f"{type(exc).__name__}"
        out.append(f"{zone:<5}{kind:<12}{sq:>5.0f} sq -> {val}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write and activate a new config version (otherwise print and exit)")
    args = ap.parse_args()

    from sqlalchemy import select

    from app.models import PricingConfig, SessionLocal
    from core.pricing_config import compute_hash, load_config

    fixture = json.loads(FIXTURE.read_text())
    s = SessionLocal()
    s.info["tenant_id"] = 1
    branches = [r[0] for r in s.execute(select(PricingConfig.branch).distinct()).all()]
    touched = 0

    for branch in sorted(branches, key=lambda b: (BRANCH_ORDER + (b,)).index(b)):
        active = s.execute(select(PricingConfig).where(
            PricingConfig.branch == branch, PricingConfig.is_active == True  # noqa: E712
        )).scalar_one_or_none()
        if active is None:
            print(f"{branch}: no active config", file=sys.stderr)
            continue

        cfg = copy.deepcopy(dict(active.config))
        changes = []
        for path, why in PATHS:
            want = dig(fixture, path)
            if want is _MISSING:
                print(f"  ! {'.'.join(path)} absent from the fixture — skipped", file=sys.stderr)
                continue
            have = dig(cfg, path)
            if have == want:
                continue
            put(cfg, path, copy.deepcopy(want))
            changes.append((".".join(path), have, want, why))

        print(f"\n=== {branch}  (active v{active.version}) ===")
        if not changes:
            print("  already current — nothing to do")
            continue
        touched += 1
        for name, have, want, why in changes:
            print(f"  {name}\n      {fmt(have)}\n   -> {fmt(want)}      [{why}]")

        before, after = load_config(dict(active.config)), load_config(cfg)
        print("  PM incentive, before -> after:")
        for b, a in zip(pm_probe(before), pm_probe(after)):
            mark = "  <-- CHANGED" if b.split("-> ")[-1] != a.split("-> ")[-1] else ""
            print(f"    {b}   |   {a.split('-> ')[-1]:>12}{mark}")

        # Keys prod carries that the fixture does not must survive the merge.
        for guard in ("office_daily_overhead", "enforce_profit_floor", "gutters"):
            if guard in active.config:
                assert cfg.get(guard) == active.config[guard], f"{guard} lost in merge"

        if not args.apply:
            continue
        active.is_active = False
        s.flush()
        new = PricingConfig(
            branch=branch, version=active.version + 1,
            label="pm_incentive axes + live-sheet tile/low-slope values",
            config=cfg, config_hash=compute_hash(cfg),
            is_active=True, created_by="seed_pm_incentive_axes.py", tenant_id=1,
        )
        s.add(new)
        s.flush()
        print(f"  created + activated v{new.version} (id={new.id})")

    if args.apply and touched:
        s.commit()
        print(f"\ncommitted — {touched} branch(es) updated")
    else:
        s.rollback()
        if touched:
            print("\n(dry run — nothing written; pass --apply to commit)")
    s.close()


if __name__ == "__main__":
    main()
