#!/usr/bin/env python3
"""Re-price the 7/12 and WinterGuard adders from Tim's CELL COMMENTS, and fix the band edges.

Jon, 2026-07-25: "you have to use his sheet comments as the source of truth". The headline cell
values drift; the comments carry the L/M/OH/P build-up Tim actually reasons with, and they agree
across tabs where the headlines do not.

7/12+ TILE ADDER -> $305 in BOTH zones (was FBC $305 / HVHZ $200)

    live sloped, comment on the HVHZ tab cell "Add $200 for 7/12+":
        Demo L $70 + Tile L $70 + M $40 + OH $90 + P $35 = $305
    live sloped, comment on the cell "Add $385 for 7/12+":
        Demo L $70 + Tile L $70 + M $40 + OH $95 + P $30 = $305

    Two independent comments on the live sheet both build to $305, so the $200 headline
    contradicts its own comment and the $385 headline overshoots it. There is no real zone
    split here — the apparent FBC>HVHZ "inversion" both R2 reviewers flagged was an artifact of
    a stale headline cell, not a genuine per-zone price.

    (The separate "NEW ***Sloped" sheet builds to $200 via L $50 + M $25 + OH $95 + P $30 —
    note it carries NO demo component, where both live comments include Demo L $70. That sheet
    is not the one we price from; flag it to Tim rather than average it in.)

WINTERGUARD -> $135 in BOTH zones (was FBC $150 / HVHZ $140)

    identical comment on BOTH the live sloped and the NEW sheet:
        M $60 + L $25 + OH $32 + P $18 = $135
    while the headlines read $125 (the cell the comment is attached to), $140 and $150. Every
    headline disagrees with the build; the build agrees with itself across two sheets.

TILE/METAL DEMO ADDERS -> UNCHANGED ($30/$40 and $45/$60).
    No comment exists on either, so the per-tab headlines are the only evidence, and those are
    direction-consistent with every other zoned price (HVHZ > FBC). Both R2 reviewers said keep.

BAND EDGES -> boundary_exclusive_upper = false (Jon's call, 2026-07-25)
    profit_scale stores Tim's INCLUSIVE band labels ([1,400] = "1 square") while the lookup
    treated max_sq as exclusive, so a job landing exactly on an edge took the next band's LOWER
    rate: 1 sq got $200 where his sheet says $400, and 4/7/14/29 likewise. The flag already
    exists and is read in exactly one place (PricingConfig.profit_per_sq). Flipping it resolves
    every edge to the higher rate — never under-quote.
    sq=20 is genuinely double-claimed on his sheet ("15-20" AND "20-29"); the flip lands it on
    $120. That is question #9 in the drafted email — confirm, do not assume.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/seed_comment_derived_adders.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys

UPDATES = {
    "pitch_7_12_add": {"FBC": 305, "HVHZ": 305},
    "winterguard_add": {"FBC": 135, "HVHZ": 135},
    "boundary_exclusive_upper": False,
}
LABEL = "comment-derived 7/12 + WinterGuard; band edges inclusive"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from sqlalchemy import select

    from app.models import PricingConfig, SessionLocal
    from core.pricing_config import compute_hash, load_config

    s = SessionLocal()
    s.info["tenant_id"] = 1
    branches = [r[0] for r in s.execute(select(PricingConfig.branch).distinct()).all()]
    for branch in sorted(branches):
        active = s.execute(select(PricingConfig).where(
            PricingConfig.branch == branch, PricingConfig.is_active == True  # noqa: E712
        )).scalar_one_or_none()
        if active is None:
            print(f"{branch}: no active config", file=sys.stderr)
            continue

        cfg = dict(active.config)
        changed = {k: (cfg.get(k), v) for k, v in UPDATES.items() if cfg.get(k) != v}
        if not changed:
            print(f"{branch}: already current — skipped")
            continue
        cfg.update(UPDATES)

        for k, (was, now) in changed.items():
            print(f"  {branch:8} {k:26} {was} -> {now}")
        # profit at the band edges, before/after — the flip's whole point
        before, after = load_config(active.config), load_config(cfg)
        edges = [1, 4, 7, 14, 20, 29]
        print(f"  {branch:8} profit/sq at band edges "
              f"{[f'{e}:{before.profit_per_sq(float(e)):.0f}->{after.profit_per_sq(float(e)):.0f}' for e in edges]}")

        if args.dry_run:
            print(f"  {branch}: would create v{active.version + 1}")
            continue

        active.is_active = False
        s.flush()
        new = PricingConfig(
            branch=branch, version=active.version + 1, label=LABEL,
            config=cfg, config_hash=compute_hash(cfg),
            is_active=True, created_by="seed_comment_derived_adders.py", tenant_id=1,
        )
        s.add(new)
        s.flush()
        print(f"  {branch}: created + activated v{new.version} (id={new.id})")
    if not args.dry_run:
        s.commit()
    s.close()


if __name__ == "__main__":
    main()
