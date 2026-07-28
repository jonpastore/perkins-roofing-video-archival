#!/usr/bin/env python3
"""Load Tim's Knowify scope-of-work library into tenant.settings["scope_templates"].

Tim, 2026-07-27: *"I would scrape MY notify... I update my catalog all the time, way more than
Josh does... Sometimes I'll even forget [to tell Josh]."* He asked for scope-of-work templates,
accent items (skylight / solar vent / chimney), PROTECTOR/PREFERRED/PREMIUM per roof type, and
repair scopes by type — applied to the scope-of-work section on BOTH re-roof and repair.

Source: ~/perkins-corpus/knowify/jupiter_catalog_perkins_items_2026-07-28.json — 226 items pulled
2026-07-28 from Perkins Roofing JUPITER (Company 30586 / Tenant 28403) over the MCP, after Tim
granted admin. That is Tim's own tenant, NOT Josh's (11267 / 9258), whose catalog has been
untouched since 2026-05-07 and whose accent items are $0 placeholders from 2024-10-23.

219 of the 226 carry scope text (339,753 chars, median 1,063). The text IS the proposal body from
the golden PDFs, so a template here is what the customer actually reads.

CLASSIFICATION is by name, deterministically, into the job_type the Quoting page filters on:

  repair  work on an existing roof — repair / replacement / restoration / maintenance / cleaning
  both    ACCENT items (skylight, solar vent, turbine, ridge vent, chimney cap). Tim asked for
          these on re-roof AND repair, so they carry "both" and show in either mode.
  reroof  everything else — the tier systems, coatings, membranes, gutters

Idempotent: upsert is by name (the API dedupes on name alone, case-insensitively), so re-running
replaces text in place. Names come from Knowify verbatim so a later re-scrape lands on the same key.

⚠️ PRICES ARE NOT TOUCHED. This seeds TEXT only. Tim's tier prices disagree with Josh's in five
places and with our config in more; that is a separate, reviewed change — see
docs/knowify-price-diff-2026-07-28.md.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/seed_knowify_scope_templates.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CATALOG = Path.home() / "perkins-corpus" / "knowify" / "jupiter_catalog_perkins_items_2026-07-28.json"

# Accent items Tim named by hand, plus the rest of the same family. These go to BOTH modes.
ACCENT = re.compile(r"skylight|solar roof vent|turbine|ridge vent|chimney cap|gooseneck", re.I)
# Work on an existing roof rather than a new system.
REPAIR = re.compile(
    r"repair|replacement|restoration|maintenance|clean|spall|drywall|soffit|fascia|stucco"
    r"|mortar|re-install|temporary", re.I)

MAX_TEXT = 20000   # api.routes.proposals.ScopeTemplateUpsert
MAX_NAME = 120


def classify(name: str) -> str:
    if ACCENT.search(name):
        return "both"
    if REPAIR.search(name):
        return "repair"
    return "reroof"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-id", type=int, default=1)
    ap.add_argument("--apply", action="store_true", help="write (otherwise print and exit)")
    args = ap.parse_args()

    if not CATALOG.exists():
        print(f"catalog not found: {CATALOG}", file=sys.stderr)
        raise SystemExit(1)
    items = json.loads(CATALOG.read_text())["Data"]

    entries, skipped = [], []
    for it in items:
        name = (it.get("Name") or "").strip()
        text = (it.get("KnowifyDescription") or "").strip()
        if not name or not text:
            skipped.append((name or "(unnamed)", "no scope text"))
            continue
        if len(name) > MAX_NAME or len(text) > MAX_TEXT:
            skipped.append((name, f"too long (name {len(name)}, text {len(text)})"))
            continue
        entries.append({"name": name, "text": text, "job_type": classify(name),
                        "updated_by": "knowify-jupiter-2026-07-28"})

    from collections import Counter
    counts = Counter(e["job_type"] for e in entries)
    print(f"{len(entries)} templates from {len(items)} catalog items "
          f"({counts['reroof']} reroof, {counts['repair']} repair, {counts['both']} accent/both)")
    for name, why in skipped:
        print(f"  skipped: {name[:70]} — {why}")
    print("\n  accent items (both modes):")
    for e in sorted(e["name"] for e in entries if e["job_type"] == "both"):
        print(f"    {e}")

    if not args.apply:
        print("\n(dry run — nothing written; pass --apply to commit)")
        return

    from app.models import SessionLocal, Tenant

    s = SessionLocal()
    s.info["tenant_id"] = args.tenant_id
    tenant = s.get(Tenant, args.tenant_id)
    if tenant is None:
        print(f"tenant {args.tenant_id} not found", file=sys.stderr)
        raise SystemExit(1)

    existing = [t for t in ((tenant.settings or {}).get("scope_templates") or [])
                if isinstance(t, dict) and t.get("name")]
    incoming = {e["name"].strip().lower() for e in entries}
    kept = [t for t in existing if t["name"].strip().lower() not in incoming]
    # Reassign, don't mutate — SQLAlchemy only flushes a JSON column on identity change.
    tenant.settings = {**(tenant.settings or {}), "scope_templates": kept + entries}
    s.commit()
    print(f"\nwrote {len(entries)} templates (kept {len(kept)} pre-existing, "
          f"replaced {len(existing) - len(kept)})")
    s.close()


if __name__ == "__main__":
    main()
