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

# ⚠️ REMOVED 2026-07-25. This block used to carry the zoned adders read off the sheet HEADLINES
# (pitch_7_12 HVHZ 200 / FBC 305, winterguard HVHZ 140 / FBC 150). scripts/seed_comment_derived_adders.py
# later replaced those with the values Tim's own CELL COMMENTS build to (305/305 and 135/135), which
# is now what prod runs. The two seeders were not idempotent against each other: re-running this one —
# a plausible thing to do when finally seeding Naples' office burn — silently reverted the
# comment-derived pricing with no diff to review.
#
# This script now writes ONLY office burn. Zoned adders belong to seed_comment_derived_adders.py;
# that is the single writer. See docs/four-way-review-2026-07-25.md F11.
ZONED_ADDS: dict = {}

# $/man-day of the office the base daily_overhead_rates were measured in (Jupiter, 7-men column).
OH_BASIS_REFERENCE = 200

# Per-branch office burn. men = the crew-size column that branch prices from.
#
# Miami was 4140, read off his OH Basis rows (9x$460, 12x$345, 15x$275 all land near $4,140/day).
# Tim gave the real figure on the 2026-07-27 call, by his own arithmetic: "my branch is like 28
# grand, their branch is like 85 grand, and we just divide that by 20 work days." $85,000/20 =
# $4,250. Jupiter's $28,000/20 = $1,400 confirms the method — it reproduces the existing value
# exactly. So 4140 is stale and 4250 is his number.
#
# `men` moves more money than the burn does, and the sheet answers it once you read the labels
# rather than the numbers. Both tabs of "**Low-Slope Roof Price Calculator" carry THREE OH-basis
# columns, and each pairs a crew size with a THROUGHPUT — the $/man-day falls left to right because
# the same office overhead spreads over more jobs per week:
#
#   Jupiter   (gid=1121451883)  C1 4 men 1 re-roof/wk $345 | F1  7 men 2/wk $200 | I1 10 men 3/wk $140
#   Overhead Metrics (gid=8964429)  C1 9 men 1/wk $460 | F1 12 men 2/wk $345 | I1 15 men 3/wk $275
#
# Jupiter is already configured off its 2-re-roofs-per-week column (7 men, $200) — that IS
# office_oh_basis_reference. So Miami's figure is the same tempo column, not a middle-of-three pick.
#
# ⚠️ Miami's row 1 is STALE. Jon, 2026-07-28: "miami grew and row 1 not updated." The detail rows
# below it (D3/E3/F3) read 11 / 14 / 18 men against row 1's 9 / 12 / 15, while Jupiter's two blocks
# agree (4/7/10 in both) — which is why Jupiter is the trusted side. Miami's CURRENT 2-per-week crew
# is therefore 14, not row 1's 12. Taking the stale 12 would price $4,250/12 = $354/man-day against
# the true $4,250/14 = $304, overcharging a 30 SQ tile job by $1,512 (43,435 vs 41,923).
#
# Naples stays absent on purpose: Tim has never stated it, and an absent key leaves rates unscaled
# rather than guessing.
OFFICE = {
    "jupiter": {"office_daily_overhead": 1400, "office_men": 7},    # 7 x $200 -> factor 1.0000
    "miami": {"office_daily_overhead": 4250, "office_men": 14},     # 14 x $304 -> factor 1.5179
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
