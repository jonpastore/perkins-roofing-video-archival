#!/usr/bin/env python3
"""Publish Avada Portfolio DRAFTS to WordPress STAGING from portfolio_records.json
(scripts/portfolio_prefill.py output). NEVER touches the live site — WP_URL comes from the
same admin-config resolver as the rest of the app (currently pinned to staging).

Idempotent: skips a project if a draft/any-status avada_portfolio post with the same title
already exists. Creates the 3 taxonomy terms (portfolio_category/portfolio_skills/
portfolio_tags) on first use if missing.

Usage:
  .venv/bin/python scripts/portfolio_publish.py --records <scratch-dir>/portfolio_records.json [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters import wordpress  # noqa: E402

TAXONOMIES = {"category": "portfolio_category", "tags": "portfolio_tags", "skills": "portfolio_skills"}


def _api(path: str) -> str:
    return f"{wordpress._rest_base_url(wordpress.resolved_wp_url())}{path}"  # noqa: SLF001


def _get_or_create_term(taxonomy_rest: str, name: str) -> int:
    """Look up a taxonomy term by exact (case-insensitive) name, creating it if missing."""
    resp = requests.get(_api(f"/wp-json/wp/v2/{taxonomy_rest}"), auth=wordpress._auth(),  # noqa: SLF001
                        params={"search": name, "per_page": 100}, timeout=20)
    resp.raise_for_status()
    for term in resp.json():
        if term["name"].strip().lower() == name.strip().lower():
            return term["id"]
    resp = requests.post(_api(f"/wp-json/wp/v2/{taxonomy_rest}"), auth=wordpress._auth(),  # noqa: SLF001
                          json={"name": name}, timeout=20)
    resp.raise_for_status()
    return resp.json()["id"]


def _existing_post_id(title: str) -> int | None:
    resp = requests.get(_api("/wp-json/wp/v2/avada_portfolio"), auth=wordpress._auth(),  # noqa: SLF001
                         params={"search": title, "status": "any", "per_page": 100}, timeout=20)
    resp.raise_for_status()
    for post in resp.json():
        if post["title"]["rendered"].strip().lower() == title.strip().lower():
            return post["id"]
    return None


def publish_one(post: dict, *, dry_run: bool) -> dict:
    """post = a record's `post` payload: {title, content, status, category, tags[], skills[]}."""
    existing = _existing_post_id(post["title"])
    if existing:
        return {"title": post["title"], "status": "skipped-exists", "post_id": existing}

    if dry_run:
        return {"title": post["title"], "status": "dry-run", "category": post["category"],
                 "tags": post["tags"], "skills": post["skills"]}

    term_ids = {"portfolio_category": [_get_or_create_term(TAXONOMIES["category"], post["category"])]}
    if post["tags"]:
        term_ids["portfolio_tags"] = [_get_or_create_term(TAXONOMIES["tags"], t) for t in post["tags"]]
    if post["skills"]:
        term_ids["portfolio_skills"] = [_get_or_create_term(TAXONOMIES["skills"], s) for s in post["skills"]]

    payload = {"title": post["title"], "content": post["content"], "status": post["status"], **term_ids}
    resp = requests.post(_api("/wp-json/wp/v2/avada_portfolio"), auth=wordpress._auth(),  # noqa: SLF001
                          json=payload, timeout=30)
    resp.raise_for_status()
    return {"title": post["title"], "status": "created", "post_id": resp.json()["id"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    records = json.loads(Path(args.records).read_text())
    results = [publish_one(rec["post"], dry_run=args.dry_run) for rec in records]

    for r in results:
        print(f"  {r['status']:16s} {r['title']} -> {r.get('post_id', '')}")

    created = sum(1 for r in results if r["status"] == "created")
    skipped = sum(1 for r in results if r["status"] == "skipped-exists")
    print(f"\n{created} created, {skipped} skipped (already existed), {len(results)} total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
