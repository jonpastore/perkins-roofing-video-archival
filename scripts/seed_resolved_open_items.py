"""Seed the open items resolved from Tim's own documents on 2026-07-27 (OI-5, OI-11).

Both were answered from the corpus rather than by asking him — see docs/R2-2026-07-27.md.

OI-5, plywood deck replacement. `low_slope.deck_types.plywood_replace` was null and
`low_slope_deck_cost()` raised on it, which is what made this "the only open item that blocks a
flat-roof quote". The reason it was never filled is that the key had the wrong UNIT: everything in
`deck_types` is charged per SQUARE, but Tim's Lumber Schedule prices plywood per SHEET, and it
applies to any roof type — the golden proposal that attaches the schedule is a TILE re-roof.
Filling the old key with 120 would have charged $120/sq. So the adder goes in at top level, keyed
by thickness, with his 2-sheet allowance.

OI-11, low-slope zones. FBC and HVHZ use the same low-slope prices, but Tim's sheet marks two deck
systems "not HVHZ" outright — BUR Wood (WB-3000 Primer), also 1-storey only, and BUR Wood (SA V
Flashing Strips). That lived in config as a `_note_` string, so nothing enforced it and an HVHZ job
could be quoted on a system his own sheet forbids there. Recorded as data so the engine can warn.

⚠️ Both keys are INERT until someone supplies the input: plywood bills only when
`plywood_sheets` exceeds the included allowance (default 0 sheets), and the HVHZ entry only ever
produces a warning. No existing quote changes price. That is deliberately unlike
seed_office_overhead_config.py, which rescales every overhead rate and is gated on Jon.

Idempotent — skips a branch that already carries both keys.

    DB_URL=... PYTHONPATH=. .venv/bin/python scripts/seed_resolved_open_items.py --dry-run
    DB_URL=... PYTHONPATH=. .venv/bin/python scripts/seed_resolved_open_items.py
"""
from __future__ import annotations

import argparse
import json
import sys

# Tim's Lumber Schedule, installed and un-primed, per sheet. Roof decking is explicitly EXEMPT
# from the "$85.00/sheet on 2-storey" carpentry surcharge, so no storey adder is modelled.
PLYWOOD_REPLACEMENT = {
    "per_sheet": {"5_8in": 120, "1_2in": 110, "3_4in": 145},
    "sheets_included": 2,
}
PLYWOOD_NOTE = (
    "OI-5, resolved 2026-07-27 from Tim's Lumber Schedule, which his proposals attach as a "
    "contract exhibit. Per SHEET, not per square, and not low_slope-scoped — the proposal it "
    "comes from is a TILE re-roof. sheets_included=2 matches his scope language: 'An allotment "
    "of 100 linear feet of decking wood (total) OR 2 sheets of plywood is included at no "
    "additional charge.' low_slope.deck_types.plywood_replace stays null on purpose (wrong unit)."
)
NOT_HVHZ_DECK_TYPES = {
    "bur_wood_wb3000": "1 story only",
    "bur_wood_sav_flashing": "plywood only",
}
NOT_HVHZ_NOTE = (
    "OI-11: Tim's sheet labels these two deck systems 'not HVHZ' explicitly. Data, not prose, so "
    "core/estimator.py can warn (never block — he overrides his own sheet) when one is selected "
    "on an HVHZ job."
)


def apply(cfg: dict) -> list[str]:
    """Add the resolved keys in place. Returns the names of what it added."""
    added: list[str] = []
    if not cfg.get("plywood_replacement"):
        cfg["plywood_replacement"] = json.loads(json.dumps(PLYWOOD_REPLACEMENT))
        cfg["_note_plywood_replacement"] = PLYWOOD_NOTE
        # Classified so the scopes contract stays complete (an absent key fails closed to
        # "branch"; this fuses labour and material in one figure, hence "mixed").
        if isinstance(cfg.get("_scopes"), dict):
            cfg["_scopes"]["plywood_replacement"] = "mixed"
        # The old per-square key stays null; replace its pending note with the resolution.
        deck = cfg.get("low_slope", {}).get("deck_types")
        if isinstance(deck, dict):
            deck.pop("_pending_plywood_replace", None)
            deck["_note_plywood_replace"] = (
                "RESOLVED 2026-07-27 (OI-5): stays null ON PURPOSE — priced per SHEET at the "
                "top-level plywood_replacement key, not per square here."
            )
        added.append("plywood_replacement")

    low = cfg.get("low_slope")
    if isinstance(low, dict) and not low.get("not_hvhz_deck_types"):
        low["not_hvhz_deck_types"] = dict(NOT_HVHZ_DECK_TYPES)
        low["_note_not_hvhz_deck_types"] = NOT_HVHZ_NOTE
        added.append("low_slope.not_hvhz_deck_types")
    return added


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

        cfg = json.loads(json.dumps(active.config))
        added = apply(cfg)
        if not added:
            print(f"{branch}: already carries the resolved keys — skipped")
            continue

        print(f"{branch}: v{active.version} -> v{active.version + 1} adding {added}")
        if args.dry_run:
            continue
        nxt = PricingConfig(
            tenant_id=1, branch=branch, version=active.version + 1, config=cfg,
            config_hash=compute_hash(cfg), is_active=True,
            label="OI-5 plywood per-sheet + OI-11 not-HVHZ deck types (inert at default inputs)",
            created_by="seed_resolved_open_items.py",
        )
        active.is_active = False
        s.add(nxt)
        s.commit()
        print(f"    wrote {branch} v{nxt.version}")

    if args.dry_run:
        print("\n(dry run — nothing written)")


if __name__ == "__main__":
    main()
