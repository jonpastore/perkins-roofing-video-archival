#!/usr/bin/env python3
"""Seed the named scope-of-work templates into tenant.settings["scope_templates"].

Source of truth is `assets/scope_templates/*.txt` (git), NOT this file — the text was lifted
verbatim from Josh's real Knowify proposal ("Jon test roof", 2026-07-08, saved in
~/perkins-corpus/golden-proposals/), which is what "Josh's saved templates" actually means.

Only real scope text is seeded. Repair scope is deliberately NOT invented here: sales saves
their own from the Quoting page with "Save as template" once, and it is then reusable.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/seed_scope_templates.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "scope_templates"

# filename -> (template name, job_type)
TEMPLATES = {
    "perkins_protector_tile_reroof.txt": ("Perkins Protector — Tile Re-Roof", "reroof"),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--tenant-id", type=int, default=1)
    args = ap.parse_args()

    from app.models import SessionLocal, Tenant

    s = SessionLocal()
    s.info["tenant_id"] = args.tenant_id
    tenant = s.get(Tenant, args.tenant_id)
    if tenant is None:
        print(f"tenant {args.tenant_id} not found", file=sys.stderr)
        raise SystemExit(1)

    existing = list((tenant.settings or {}).get("scope_templates") or [])
    by_name = {t["name"].strip().lower(): t for t in existing if isinstance(t, dict) and t.get("name")}

    for filename, (name, job_type) in TEMPLATES.items():
        path = ASSETS / filename
        if not path.exists():
            print(f"{filename}: missing under assets/scope_templates — skipped", file=sys.stderr)
            continue
        text = path.read_text().strip()
        current = by_name.get(name.strip().lower())
        if current and current.get("text") == text:
            print(f"{name!r}: already current — skipped")
            continue
        verb = "updated" if current else "added"
        if args.dry_run:
            print(f"{name!r}: would be {verb} ({len(text)} chars, job_type={job_type})")
            continue
        by_name[name.strip().lower()] = {
            "name": name, "text": text, "job_type": job_type,
            "updated_by": "seed_scope_templates.py",
        }
        print(f"{name!r}: {verb} ({len(text)} chars)")

    if not args.dry_run:
        # Reassign — SQLAlchemy only flushes a JSON column when the value identity changes.
        tenant.settings = {**(tenant.settings or {}), "scope_templates": list(by_name.values())}
        s.commit()
        print(f"tenant {args.tenant_id}: {len(by_name)} scope template(s) stored")
    s.close()


if __name__ == "__main__":
    main()
