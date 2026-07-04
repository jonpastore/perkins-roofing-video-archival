"""Cloud Scheduler target (via the api /internal/promote route, or run directly): promote due
scheduled_content. Wave-2 marks due articles published; reels are handed to the Wave-4 social
publisher. The WP future->publish flip is wired through adapters.wordpress at integration.

Run: .venv/bin/python -m jobs.promote_job
"""
from datetime import datetime, timezone

import adapters.wordpress as wordpress
from app.models import Article, ScheduledContent, SessionLocal
from core.scheduler import due


def run(now=None):
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    s = SessionLocal()
    rows = s.query(ScheduledContent).all()
    promoted, errored = 0, 0
    for r in due(rows, now):
        try:
            # Resolve Article by slug (ref_id == Article.slug)
            article = s.get(Article, r.ref_id) if r.kind == "article" else None
            if article and article.wp_post_id:
                wordpress.update_status(article.wp_post_id, "publish")
            r.status = "published"
            s.add(r)
            promoted += 1
        except Exception as e:  # noqa: BLE001
            s.rollback()
            r.status = "error"
            s.add(r)
            errored += 1
            print(f"[error] scheduled_content {r.id}: {str(e)[:120]}")
    s.commit()
    s.close()
    return {"promoted": promoted, "errored": errored}


if __name__ == "__main__":
    print(run())
