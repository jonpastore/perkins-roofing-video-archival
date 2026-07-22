"""Deterministic (no-LLM) pass over EXISTING Article rows to re-standardize them:
  (a) rebuild jsonld_json to FAQ+Video-ONLY scope, reusing
      jobs.article_job._build_article_jsonld (Rank Math already emits
      Article/Organization/BreadcrumbList — those node types are dropped here).
  (b) strip /blog/ from internal links in content_md + jsonld_json, matching the
      canonical_url convention in jobs.article_job (posts are top-level, never /blog/<slug>).

DRY-RUN ONLY from the command line: this entrypoint always previews and never writes.
`run(dry_run=False, ...)` exists as a library call for a future, separately-reviewed
apply step; nothing in this file invokes it. Neither mode ever touches WordPress.

Run (dry-run):
    python -m jobs.restandardize_articles [--slug SLUG]
"""
from __future__ import annotations

import argparse
import logging

from core.article_restandardize import jsonld_types, strip_blog_links, strip_blog_links_deep, video_nodes

logger = logging.getLogger(__name__)


def _preview_for_article(article) -> dict:
    """Read-only preview for one Article row: proposed jsonld + /blog/ occurrence counts."""
    from jobs.article_job import _build_article_jsonld  # noqa: PLC0415

    current_jsonld = article.jsonld_json or []
    proposed_jsonld = _build_article_jsonld(
        {"faq_json": article.faq_json or [], "_video_jsonld": video_nodes(current_jsonld)}, {}
    )
    proposed_jsonld, jsonld_blog_count = strip_blog_links_deep(proposed_jsonld)
    _, content_blog_count = strip_blog_links(article.content_md or "")

    return {
        "slug": article.slug,
        "current_types": jsonld_types(current_jsonld),
        "proposed_types": jsonld_types(proposed_jsonld),
        "proposed_jsonld": proposed_jsonld,
        "content_blog_links": content_blog_count,
        "jsonld_blog_links": jsonld_blog_count,
    }


def run(
    dry_run: bool = True, only_slug: str | None = None, tenant_id: int = 1,
    live_only: bool = True,
) -> list[dict]:
    """Preview (dry_run=True, default) or apply the re-standardization for one tenant.

    live_only=True (default) restricts to articles actually published to WordPress
    (wp_post_id set) — the ones whose schema/links are live for Rank Math and site
    visitors today. dry_run=False writes jsonld_json/content_md to the DB. This
    function never calls WordPress either way — publishing changed schema/links to
    the live site is a separate, explicit step outside this job's scope.
    """
    from app.models import Article  # noqa: PLC0415
    from jobs.article_job import _stamped_session  # noqa: PLC0415

    with _stamped_session(tenant_id) as db:
        q = db.query(Article)
        if live_only:
            q = q.filter(Article.wp_post_id.isnot(None))
        if only_slug:
            q = q.filter(Article.slug == only_slug)
        articles = q.order_by(Article.slug).all()
        previews = [_preview_for_article(a) for a in articles]

        if not dry_run:
            for article, preview in zip(articles, previews):
                article.jsonld_json = preview["proposed_jsonld"]
                article.content_md, _ = strip_blog_links(article.content_md or "")
                db.add(article)
            db.commit()

    return previews


def _print_dry_run(previews: list[dict]) -> None:
    changed = 0
    for p in previews:
        will_change = p["current_types"] != p["proposed_types"] or p["content_blog_links"] or p["jsonld_blog_links"]
        changed += int(bool(will_change))
        print(
            f"{p['slug']}: {p['current_types']} -> {p['proposed_types']} "
            f"| /blog/ occurrences: content={p['content_blog_links']} jsonld={p['jsonld_blog_links']}"
        )
    print(f"\n{changed}/{len(previews)} article(s) would change (dry-run — nothing written)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Preview only, no writes. This is the only mode this "
                             "entrypoint supports.")
    parser.add_argument("--slug", default=None, help="Restrict to one article slug.")
    args = parser.parse_args()
    # HARD RULE: always dry-run from the CLI, regardless of flags — see module docstring.
    _print_dry_run(run(dry_run=True, only_slug=args.slug))
