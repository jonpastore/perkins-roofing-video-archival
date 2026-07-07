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
        # Commit PER ROW: a failure on one row must not roll back rows already promoted in
        # this run (a single trailing s.commit() + mid-loop s.rollback() would revert every
        # prior row's status, inflate `promoted`, and re-publish them next tick).
        try:
            if r.kind == "reel":
                # Wave-4 social publisher does not exist yet. Move the reel to a distinct
                # terminal-for-now state that core.scheduler.due() does NOT select, so it is
                # NOT re-picked every cron tick (avoids an inflated count + a double-publish
                # trap). The future Wave-4 publisher selects on status == "awaiting_social".
                r.status = "awaiting_social"
                s.add(r)
                s.commit()
                print(
                    f"[promote] scheduled_content {r.id} kind=reel: "
                    "reel ready, moved to awaiting_social (Wave-4 will publish)"
                )
                promoted += 1
                continue

            # article branch — resolve by slug (ref_id == Article.slug)
            article = s.get(Article, r.ref_id) if r.kind == "article" else None
            if article and article.wp_post_id:
                wordpress.update_status(article.wp_post_id, "publish")
            r.status = "published"
            s.add(r)
            s.commit()
            promoted += 1
        except Exception as e:  # noqa: BLE001
            s.rollback()                 # unwinds only THIS row's pending change
            r.status = "error"
            s.add(r)
            s.commit()
            errored += 1
            print(f"[error] scheduled_content {r.id}: {str(e)[:120]}")
    s.close()
    return {"promoted": promoted, "errored": errored}


if __name__ == "__main__":
    print(run())
