#!/usr/bin/env python3
"""Publish Avada Portfolio DRAFTS to WordPress STAGING from portfolio_records.json
(scripts/portfolio_prefill.py output). NEVER touches the live site — WP_URL comes from the
same admin-config resolver as the rest of the app (currently pinned to staging).

Idempotent: skips a project if a draft/any-status avada_portfolio post with the same title
already exists. Creates the 3 taxonomy terms (portfolio_category/portfolio_skills/
portfolio_tags) on first use if missing.

The publish-one-project logic lives in adapters/wordpress.py (publish_portfolio_post) so this
CLI and api/routes/portfolio.py (admin UI, #384) share one implementation.

Usage:
  .venv/bin/python scripts/portfolio_publish.py --records <scratch-dir>/portfolio_records.json [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.wordpress import publish_portfolio_post  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    records = json.loads(Path(args.records).read_text())
    results = [publish_portfolio_post(rec["post"], dry_run=args.dry_run) for rec in records]

    for r in results:
        print(f"  {r['status']:16s} {r['title']} -> {r.get('post_id', '')}")

    created = sum(1 for r in results if r["status"] == "created")
    skipped = sum(1 for r in results if r["status"] == "skipped-exists")
    print(f"\n{created} created, {skipped} skipped (already existed), {len(results)} total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
