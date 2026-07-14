"""Backfill / re-process existing articles.

Re-sanitizes article HTML, optionally runs an LLM refine pass to flesh out
thin content, and syncs the result to WordPress when the article already has a
wp_post_id.  Idempotent — safe to run repeatedly.

Usage:
    # Re-process all articles
    python -m jobs.reprocess_articles

    # Re-process specific slugs
    python -m jobs.reprocess_articles slug-one slug-two
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _run_for_tenant(
    db,
    tenant_id: int,
    slugs: list[str] | None = None,
    *,
    refine: bool = False,
    llm=None,
) -> dict:
    """Per-tenant article reprocessing body. Called by for_each_tenant via run()."""
    from app.models import Article  # noqa: PLC0415
    from jobs.article_job import markdownish_to_html  # noqa: PLC0415

    processed = 0
    updated = 0
    wp_synced = 0
    errors: list[dict] = []

    if slugs:
        rows = [db.get(Article, s) for s in slugs]
        rows = [r for r in rows if r is not None]
    else:
        rows = db.query(Article).all()

    for article in rows:
        processed += 1
        try:
            original = article.content_md or ""

            content = original
            if refine and content:
                try:
                    from jobs.article_job import refine_article_content  # noqa: PLC0415
                    fields = {
                        "title":      article.title or "",
                        "slug":       article.slug,
                        "meta":       article.meta or "",
                        "content_md": content,
                        "faq_json":   list(article.faq_json) if article.faq_json else [],
                    }
                    refined = refine_article_content(fields, article.title or article.slug, llm=llm)
                    content = refined.get("content_md") or content
                except Exception as exc:  # noqa: BLE001
                    logger.warning("refine pass failed for slug=%s (keeping original): %s", article.slug, exc)

            sanitized = markdownish_to_html(content)

            if sanitized != original:
                article.content_md = sanitized
                updated += 1

            if article.wp_post_id:
                wp_creds_present = all(
                    os.environ.get(k) for k in ("WP_URL", "WP_USER", "WP_APP_PWD")
                )
                if wp_creds_present:
                    try:
                        from adapters.wordpress import update  # noqa: PLC0415
                        from jobs.article_job import _markdown_to_html  # noqa: PLC0415
                        update(
                            post_id=article.wp_post_id,
                            title=article.title or "",
                            html=_markdown_to_html(article.content_md or ""),
                            meta_description=article.meta or "",
                            jsonld=list(article.jsonld_json) if article.jsonld_json else [],
                            status=article.status or "draft",
                            focus_keyword=article.focus_keyword,
                        )
                        wp_synced += 1
                        logger.info("wp synced slug=%s post_id=%d", article.slug, article.wp_post_id)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("wp sync failed for slug=%s post_id=%d: %s",
                                       article.slug, article.wp_post_id, exc)
                else:
                    logger.info("wp creds absent — skipping WP sync for slug=%s", article.slug)

        except Exception as exc:  # noqa: BLE001
            logger.error("reprocess failed for slug=%s: %s", article.slug, exc)
            errors.append({"slug": article.slug, "error": str(exc)})

    db.commit()
    return {"processed": processed, "updated": updated, "wp_synced": wp_synced, "errors": errors}


def run(
    slugs: list[str] | None = None,
    *,
    refine: bool = False,
    llm=None,
) -> dict:
    """Iterate active tenants and reprocess articles for each."""
    from app.models import SessionLocal  # noqa: PLC0415
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    totals: dict = {"processed": 0, "updated": 0, "wp_synced": 0, "errors": []}

    def _fn(db, tenant_id: int) -> None:
        r = _run_for_tenant(db, tenant_id, slugs=slugs, refine=refine, llm=llm)
        totals["processed"] += r.get("processed", 0)
        totals["updated"] += r.get("updated", 0)
        totals["wp_synced"] += r.get("wp_synced", 0)
        totals["errors"].extend(r.get("errors", []))

    for_each_tenant(SessionLocal, _fn)
    return totals


if __name__ == "__main__":
    import json
    import sys

    _slugs = sys.argv[1:] or None
    print(json.dumps(run(_slugs), indent=2))
