#!/usr/bin/env python3
"""Reconcile the reviewed low-slope pricing (infra/fixtures/pricing_config_exhibit_b.json)
into each branch's active pricing config as a NEW config version (immutable versioning —
never mutates the active row). Same pattern as seed_cuts_calc_config.py / seed_daily_overhead_config.py.

Why: seed_pricing_configs.py is skip-if-exists, so prod's original 2026-07-10 low_slope block
(all null placeholders — bur/tpo/coatings/silicone OI-1..OI-6) never picked up the reviewed
2026-07-10 fill (granular product keys, all_in_systems, wood_deck_oh_adder=50, FBC
polyglass_sav_sap=450, tear_off_extras, etc.). _priced_low_slope_types() in
api/routes/estimator.py derives the quotable roof-type list from low_slope.base_cost_lm[zone]
keys with non-null values — with the stale block every value is null, so prod shows zero
low-slope roof types ("Pending Tim") even though the fixture + 47-test suite have real values.

Only the top-level `low_slope` key is touched. Every other key in the active config is
carried over unchanged. Idempotent: skips a branch whose active low_slope block already
matches the fixture's.

Usage:
    DB_URL=postgresql+psycopg://... PYTHONPATH=. .venv/bin/python scripts/reconcile_low_slope_pricing.py --dry-run
    DB_URL=postgresql+psycopg://... PYTHONPATH=. .venv/bin/python scripts/reconcile_low_slope_pricing.py
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE_PATH = ROOT / "infra" / "fixtures" / "pricing_config_exhibit_b.json"


def _load_fixture_low_slope() -> dict:
    return json.loads(FIXTURE_PATH.read_text())["low_slope"]


def _diff(old: dict, new: dict, path: str = "low_slope") -> list[str]:
    """Flat list of 'path: old -> new' lines for every leaf that changed, added, or removed."""
    lines: list[str] = []
    keys = sorted(set(old) | set(new))
    for k in keys:
        p = f"{path}.{k}"
        ov, nv = old.get(k, "<absent>"), new.get(k, "<absent>")
        if isinstance(ov, dict) and isinstance(nv, dict):
            lines.extend(_diff(ov, nv, p))
        elif ov != nv:
            lines.append(f"  {p}: {ov!r} -> {nv!r}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from sqlalchemy import select

    from app.models import PricingConfig, SessionLocal
    from core.pricing_config import compute_hash

    fixture_low_slope = _load_fixture_low_slope()

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

        current_low_slope = active.config.get("low_slope") or {}
        if current_low_slope == fixture_low_slope:
            print(f"{branch}: low_slope already matches fixture — skipped")
            continue

        diff_lines = _diff(current_low_slope, fixture_low_slope)
        print(f"\n{branch}: v{active.version} -> v{active.version + 1}  ({len(diff_lines)} field(s) changed)")
        for line in diff_lines:
            print(line)

        if args.dry_run:
            continue

        cfg = copy.deepcopy(active.config)
        cfg["low_slope"] = copy.deepcopy(fixture_low_slope)

        # Deactivate + flush before inserting the new active version —
        # uq_pricing_configs_one_active_per_branch is a non-deferrable partial unique index.
        new_version = active.version + 1
        active.is_active = False
        s.flush()
        new = PricingConfig(
            branch=branch, version=new_version,
            label=f"{active.label or branch} + low-slope reconcile (Exhibit B 2026-07-10 fill)",
            config=cfg, config_hash=compute_hash(cfg),
            is_active=True, created_by="reconcile_low_slope_pricing.py", tenant_id=active.tenant_id,
        )
        s.add(new)
        s.flush()
        print(f"{branch}: created + activated v{new.version} (id={new.id})")

    if not args.dry_run:
        s.commit()
    s.close()


if __name__ == "__main__":
    main()
