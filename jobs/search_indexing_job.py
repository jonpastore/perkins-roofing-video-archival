"""Cloud Scheduler target (daily, via /internal/search-indexing — or run directly):
re-submit the site root + recently-published article URLs to IndexNow + the Google
Indexing API. This is the safety-net sweep — the primary submission path is the
on-publish hook in jobs/promote_job.py; this job only re-covers the catch-up
window in case that hook's submission failed (transient API outage, etc).

Run: .venv/bin/python -m jobs.search_indexing_job
"""
from datetime import datetime, timedelta, timezone

import adapters.search_indexing as search_indexing
import adapters.wordpress as wordpress
from app.models import Article, SessionLocal
from core.search_indexing import urls_for_articles

# Covers a missed on-publish submission across a weekend-length outage without
# resubmitting the whole catalog every day (rate-limit awareness).
CATCHUP_WINDOW_DAYS = 2
MAX_CATCHUP_ARTICLES = 100


def _run_for_tenant(db, tenant_id: int, now=None) -> dict:
    """Per-tenant catch-up body. Called by for_each_tenant via run()."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(days=CATCHUP_WINDOW_DAYS)
    rows = (
        db.query(Article.slug)
        .filter(Article.status == "published", Article.updated_at >= cutoff)
        .order_by(Article.updated_at.desc())
        .limit(MAX_CATCHUP_ARTICLES)
        .all()
    )
    slugs = [r[0] for r in rows]
    # Admin-config WP_URL (resolved_wp_url), NOT env — .env is never a runtime config source.
    urls = urls_for_articles(wordpress.resolved_wp_url(), slugs)
    result = search_indexing.submit_urls(urls)
    return {"submitted": len(urls), "result": result}


def run(now=None):
    """Iterate active tenants and re-submit each one's recently-published articles."""
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    totals = {"submitted": 0}

    def _fn(db, tenant_id: int) -> None:
        r = _run_for_tenant(db, tenant_id, now=now)
        totals["submitted"] += r["submitted"]

    for_each_tenant(SessionLocal, _fn)
    return totals


if __name__ == "__main__":
    print(run())
