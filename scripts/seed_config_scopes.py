#!/usr/bin/env python3
"""Step 1 of the copy-config feature: classify every key, move no money.

`docs/specs/2026-07-27-copy-config-between-branches.md`. Jon, 2026-07-27: *"material cost should be
shared by default, overhead and labor costs are branch specific."*

Writes the `_scopes` map from the git fixture onto each branch's active config. Nothing else is
touched, and the script ASSERTS that: if any priced value differs before and after the merge it
refuses to write. Classification is inert by construction — the point of shipping it alone is that
the badges and the "branches differ" warning become possible before any write path to prices exists.

Why one top-level `_scopes` map rather than a `_scope` beside each value: `daily_overhead_rates()`
does `rate * factor` over `.items()`, so an inline string raises TypeError on every quote, and
`profit_scale` is a list with nowhere to put one.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/seed_config_scopes.py [--apply]
       (prints the classification and changes nothing unless --apply is passed)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

FIXTURE = Path("infra/fixtures/pricing_config_exhibit_b.json")
BRANCH_ORDER = ("jupiter", "miami", "naples")
META = ("_scopes", "_scopes_doc")


def _priced(cfg: dict) -> str:
    """Everything that is not classification metadata, canonically ordered."""
    return json.dumps({k: v for k, v in cfg.items() if k not in META},
                      sort_keys=True, default=str)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write and activate a new config version (otherwise print and exit)")
    args = ap.parse_args()

    from sqlalchemy import select

    from app.models import PricingConfig, SessionLocal
    from core.pricing_config import compute_hash, load_config

    fixture = json.loads(FIXTURE.read_text())
    scopes = dict(fixture.get("_scopes") or {})
    if not scopes:
        print("fixture carries no _scopes map", file=sys.stderr)
        raise SystemExit(1)

    print(f"{len(scopes)} keys classified: {dict(Counter(scopes.values()))}\n")
    by_scope: dict[str, list[str]] = {}
    for key, scope in sorted(scopes.items()):
        by_scope.setdefault(scope, []).append(key)
    for scope in ("shared", "branch", "mixed", "unclassified"):
        if by_scope.get(scope):
            print(f"  {scope:<14} {', '.join(by_scope[scope])}\n")

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

        cfg = dict(active.config)
        # A branch may legitimately carry keys the fixture does not (jupiter's office_* trio), and
        # they must still be classified or they would default to `branch` silently rather than
        # deliberately. Report any the map does not name.
        unnamed = sorted(k for k in cfg if not k.startswith("_") and k not in scopes)
        if unnamed:
            print(f"{branch}: NOT IN THE MAP -> defaults to 'branch': {', '.join(unnamed)}")

        cfg["_scopes"] = scopes
        if fixture.get("_scopes_doc"):
            cfg["_scopes_doc"] = fixture["_scopes_doc"]

        if _priced(cfg) != _priced(active.config):
            raise SystemExit(f"{branch}: a priced value moved — classification must be inert")
        if cfg == dict(active.config):
            print(f"{branch}: already classified — skipped")
            continue
        touched += 1
        cov = Counter(scopes.get(k, "branch")
                      for k in cfg if not k.startswith("_"))
        print(f"{branch} (active v{active.version}): {dict(cov)}")

        if not args.apply:
            continue
        load_config(cfg)  # refuse to activate anything the loader will not accept
        active.is_active = False
        s.flush()
        new = PricingConfig(
            branch=branch, version=active.version + 1,
            label="classify keys shared/branch/mixed (no price change)",
            config=cfg, config_hash=compute_hash(cfg),
            is_active=True, created_by="seed_config_scopes.py", tenant_id=1,
        )
        s.add(new)
        s.flush()
        print(f"  created + activated v{new.version} (id={new.id})")

    if args.apply and touched:
        s.commit()
        print(f"\ncommitted — {touched} branch(es) classified, no price changed")
    else:
        s.rollback()
        if touched:
            print("\n(dry run — nothing written; pass --apply to commit)")
    s.close()


if __name__ == "__main__":
    main()
