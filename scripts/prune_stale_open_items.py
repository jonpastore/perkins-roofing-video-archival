"""Rewrite `_meta.tim_verify_open_items` to what is ACTUALLY still open.

Why this exists: the open-items list is the authoritative "what do we still need from Tim"
record, it ships inside every prod pricing config, and nothing fails when an entry goes false.
Six of the nine entries were stale on 2026-07-27 — OI-2 said `low_slope.overhead` was "ALL cells
null" while prod carried flat_oh 155 / tpo_oh 125-135 / coatings 95; OI-4 said tapered was null
while prod carried 400; OI-6 said tear-off was null while prod carried 20; OI-8 said pm_incentive
"needs Tim verification before activation" though e20aa18 resolved it against his live sheet on
2026-07-26. Chasing a closed question wastes his time, and a list that is wrong six ways out of
nine stops being read at all.

Same failure shape as the low-slope test skips whose "pending Tim data" reason had gone false
(docs/R2-2026-07-27.md §2.1): a claim about the config that ages while the config moves.

This script writes ONLY `_meta.tim_verify_open_items` — not even `_meta.description`, which
carries bespoke provenance per config. It moves no money and touches no pricing key —
deliberately, because the repo has been bitten by a seeder
that quietly reverted another seeder's pricing (see the header of seed_office_overhead_config.py).
Each item is re-derived from the live config on every run, so re-running it is safe and it
self-corrects as Tim answers things.

    python scripts/prune_stale_open_items.py --dry-run
    python scripts/prune_stale_open_items.py
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _get(cfg: dict[str, Any], *path: str) -> Any:
    node: Any = cfg
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def open_items(cfg: dict[str, Any]) -> list[str]:
    """Return only the items this config still genuinely leaves unanswered.

    Each check reads the value it describes, so an entry cannot outlive its own blocker.
    """
    items: list[str] = []

    # OI-3: RESOLVED 2026-07-27 — insulation_by_thickness (keyed on board thickness, matching
    # Tim's sheet K15/K16/K17) is the current pricing key and low_slope_insulation_cost() prefers
    # it. insulation_tiers is the vestigial [max_sq, price] shape that generated this open item in
    # the first place; it is kept only as a fallback for older configs and no longer gates this
    # check. Open only if the current key is missing or still carries a null rate.
    by_thickness = _get(cfg, "low_slope", "insulation_by_thickness") or {}
    if not by_thickness or any(v is None for v in by_thickness.values()):
        items.append(
            "OI-3: low_slope.insulation_by_thickness — missing or has null thickness rates; "
            "Tim must supply per-thickness insulation cost-per-sq"
        )

    # OI-5: RESOLVED 2026-07-27 — Tim prices plywood per SHEET (Lumber Schedule), not per SQUARE.
    # low_slope.deck_types.plywood_replace stays null ON PURPOSE (it was the wrong unit); the real
    # adder lives at top-level plywood_replacement.per_sheet, keyed by thickness. Open only if that
    # key is missing or still carries a null rate.
    per_sheet = _get(cfg, "plywood_replacement", "per_sheet") or {}
    if not per_sheet or any(v is None for v in per_sheet.values()):
        items.append(
            "OI-5: plywood_replacement.per_sheet — missing or has null thickness rates; Tim must "
            "supply the per-sheet plywood pricing (Lumber Schedule)"
        )

    # OI-7: still null. Note the shape is also wrong — commission is per SALESPERSON (Marco 15% /
    # Josh 7.5% on identically-zoned tabs), not per slope type. Filling this cell answers the
    # narrow question and leaves the keying defect (docs/R2-2026-07-27.md §3.2) untouched.
    if _get(cfg, "commission_pct", "sloped_hvhz") is None:
        items.append(
            "OI-7: commission_pct.sloped_hvhz — null; engine defaults to sloped (0.10). NOTE the "
            "key SHAPE is wrong regardless: commission is per salesperson, not per zone (PC-1)"
        )

    # OI-9 / OI-10: both carry a presumed default rather than a null, so nothing raises and
    # nothing is verified. They stay open until Tim confirms the boundary rule either way.
    if _get(cfg, "boundary_inclusive_lower") is not None:
        items.append(
            "OI-9: boundary_inclusive_lower / boundary_exclusive_upper — PRESUMED lower-inclusive "
            "/ upper-exclusive per Exhibit B wording, never confirmed (PC-2). Answering it is a "
            "data change only"
        )
    if _get(cfg, "tile_dumpster_boundary_inclusive") is not None:
        items.append(
            "OI-10: tile_dumpster_boundary_inclusive — PRESUMED true (the threshold SQ itself "
            "triggers the next dumpster), never confirmed (Adv-1)"
        )

    # OI-11: NARROWED 2026-07-27. His sheet expresses the zone distinction as AVAILABILITY, not
    # as a second price column — two deck systems are labelled "not HVHZ" and everything else
    # carries one price for both zones. That half is now encoded as data (not_hvhz_deck_types) and
    # the engine warns on it. What is left is only confirming the PRICES against his live
    # calculator, so the item stays open until that check happens — but it no longer implies the
    # zone rule is unknown.
    if _get(cfg, "low_slope", "_note_fbc_deltas"):
        restrictions = _get(cfg, "low_slope", "not_hvhz_deck_types") or {}
        encoded = (f"the not-HVHZ deck restrictions ARE encoded ({len(restrictions)} systems) and "
                   "the engine warns on them; " if restrictions else "")
        items.append(
            "OI-11: low_slope zones — Exhibit B §4 is one table for both zones (Zoom 2026-07-20) "
            f"and his sheet shows the zone split as availability, not price. {encoded}what remains "
            "is confirming the PRICES against his live low-slope calculator"
        )

    # Office burn: an absent key silently inherits Jupiter's daily_overhead_rates, which is how
    # Miami quoted overhead at a third of what that office costs. Surface it as an open item.
    if not cfg.get("office_daily_overhead"):
        items.append(
            "OI-12: office_daily_overhead / office_men — unset, so daily_overhead_rates pass "
            "through UNSCALED (i.e. this branch prices at Jupiter's rates). Tim stated Jupiter "
            "$28k/20 = $1,400 and Miami $85k/20 = $4,250 on 2026-07-27; Naples is still unstated"
        )
    return items


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

        cfg = json.loads(json.dumps(active.config))  # deep copy, never mutate the ORM object
        meta = dict(cfg.get("_meta") or {})
        before = list(meta.get("tim_verify_open_items") or [])
        after = open_items(cfg)

        if before == after:
            print(f"{branch}: open items already accurate ({len(after)}) — skipped")
            continue

        dropped = [b for b in before if b.split(":")[0] not in {a.split(":")[0] for a in after}]
        print(f"{branch}: {len(before)} -> {len(after)} open items")
        for d in dropped:
            print(f"    CLOSED  {d[:96]}")
        for a in after:
            if a.split(":")[0] not in {b.split(":")[0] for b in before}:
                print(f"    NEW     {a[:96]}")

        meta["tim_verify_open_items"] = after
        cfg["_meta"] = meta

        if args.dry_run:
            continue
        nxt = PricingConfig(
            tenant_id=1, branch=branch, version=active.version + 1, config=cfg,
            config_hash=compute_hash(cfg), is_active=True,
            label="prune stale tim_verify_open_items (docs/R2-2026-07-27.md)",
            created_by="prune_stale_open_items.py",   # NOT NULL in pricing_configs
        )
        active.is_active = False
        s.add(nxt)
        s.commit()
        print(f"    wrote {branch} v{nxt.version}")

    if args.dry_run:
        print("\n(dry run — nothing written)")


if __name__ == "__main__":
    main()
