"""Cloud Scheduler target (via the api /internal/promote route, or run directly): promote due
scheduled_content. Wave-2 marks due articles published; reels are handed to the Wave-4 social
publisher. The WP future->publish flip is wired through adapters.wordpress at integration.

Run: .venv/bin/python -m jobs.promote_job
"""
from datetime import datetime, timezone

import adapters.search_indexing as search_indexing
import adapters.wordpress as wordpress
from app.config import settings
from app.models import Article, ScheduledContent, SessionLocal
from core.scheduler import due
from core.search_indexing import urls_for_articles


def _submit_for_indexing(slug: str) -> None:
    """Best-effort IndexNow + Google Indexing API submission for a newly-published
    article (site root + the article's own URL — see core.search_indexing).
    Never raises: a submission failure must not abort promotion, the article is
    correctly published to WordPress either way. See jobs/search_indexing_job.py
    for the daily catch-up sweep that covers a failure here."""
    try:
        urls = urls_for_articles(settings.WP_URL, [slug])
        search_indexing.submit_urls(urls)
    except Exception as e:  # noqa: BLE001
        print(f"[search_indexing] submit failed for slug={slug}: {str(e)[:120]}")


def _run_for_tenant(db, tenant_id: int, now=None) -> dict:
    """Per-tenant promotion body. Called by for_each_tenant via run()."""
    rows = db.query(ScheduledContent).all()
    promoted, errored = 0, 0
    for r in due(rows, now):
        try:
            # Atomically claim the row so two overlapping cron runs can't both promote it
            # (double-publish guard). The conditional UPDATE is row-locked by the DB; a
            # concurrent run sees 0 rows affected and skips. Portable across PG and SQLite.
            claimed = (
                db.query(ScheduledContent)
                .filter(ScheduledContent.id == r.id, ScheduledContent.status == "scheduled")
                .update({"status": "promoting"}, synchronize_session=False)
            )
            db.commit()
            if not claimed:
                continue

            if r.kind == "reel":
                r.status = "awaiting_social"
                db.add(r)
                db.commit()
                print(
                    f"[promote] scheduled_content {r.id} kind=reel: "
                    "reel ready, moved to awaiting_social (Wave-4 will publish)"
                )
                promoted += 1
                continue

            article = db.get(Article, r.ref_id) if r.kind == "article" else None
            if article and article.wp_post_id:
                wordpress.update_status(article.wp_post_id, "publish")
                _submit_for_indexing(article.slug)
            # Keep Article.status in sync with the ScheduledContent row. Without this the article
            # stays status="scheduled" after promotion, and a later regen (which sets WP status
            # from Article.status) silently reverts a live post back to draft — the desync that
            # left 9 promoted articles showing "draft" on WordPress.
            if article and article.status != "published":
                article.status = "published"
                db.add(article)
            r.status = "published"
            db.add(r)
            db.commit()
            promoted += 1
        except Exception as e:  # noqa: BLE001
            db.rollback()
            r.status = "error"
            db.add(r)
            db.commit()
            errored += 1
            print(f"[error] scheduled_content {r.id}: {str(e)[:120]}")
    return {"promoted": promoted, "errored": errored}


def run(now=None):
    """Iterate active tenants and promote due scheduled content for each."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    totals = {"promoted": 0, "errored": 0}

    def _fn(db, tenant_id: int) -> None:
        r = _run_for_tenant(db, tenant_id, now=now)
        totals["promoted"] += r["promoted"]
        totals["errored"] += r["errored"]

    for_each_tenant(SessionLocal, _fn)
    return totals


if __name__ == "__main__":
    print(run())
