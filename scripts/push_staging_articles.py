"""Publish DB articles that have no wp_post_id onto the current staging WP.

Uses adapters.wordpress.publish (create, not update). Skips empty bodies.
    PYTHONPATH=. PERKINS_ENV=prod EMBED_BACKEND=vertex LLM_BACKEND=vertex \\
      DB_URL=... WP_USER=jon WP_APP_PWD=... .venv/bin/python -u scripts/push_staging_articles.py
"""
from __future__ import annotations

import logging
import os
import sys
import time

log = logging.getLogger("push_staging")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    limit = int(os.getenv("PUSH_LIMIT", "0") or 0)
    delay = float(os.getenv("PUSH_DELAY", "1.5"))

    from app.models import Article, SessionLocal
    from jobs.batch_article_job import _publish_fields

    db = SessionLocal()
    db.info["tenant_id"] = 1
    try:
        q = (
            db.query(Article)
            .filter(Article.wp_post_id.is_(None))
            .filter(Article.content_md.isnot(None))
            .filter(Article.content_md != "")
            .order_by(Article.generated_at.asc().nullsfirst())
        )
        rows = q.all()
    finally:
        db.close()

    if limit:
        rows = rows[:limit]
    log.info("to_publish=%d", len(rows))
    ok = fail = skip = 0
    for i, row in enumerate(rows, 1):
        if not (row.content_md or "").strip():
            skip += 1
            continue
        fields = {
            "slug": row.slug,
            "title": row.title,
            "meta": row.meta,
            "content_md": row.content_md,
            "faq_json": row.faq_json,
            "jsonld_json": row.jsonld_json or [],
        }
        ctx = {"role": row.role, "pillar_slug": row.pillar_slug}
        try:
            out = _publish_fields(fields, ctx, row.focus_keyword or row.slug, "publish")
            ok += 1
            log.info("%d/%d ok slug=%s wp_post_id=%s", i, len(rows), row.slug, out.get("wp_post_id"))
        except Exception as exc:  # noqa: BLE001
            fail += 1
            log.error("%d/%d FAIL slug=%s %s: %s", i, len(rows), row.slug, type(exc).__name__, str(exc)[:240])
        time.sleep(delay)
    log.info("done ok=%d fail=%d skip=%d", ok, fail, skip)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
