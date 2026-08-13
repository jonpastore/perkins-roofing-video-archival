"""Cloud Scheduler target (via the api /internal/promote route, or run directly): promote due
scheduled_content. Wave-2 marks due articles published; reels are handed to the Wave-4 social
publisher. The WP future->publish flip is wired through adapters.wordpress at integration.

Run: .venv/bin/python -m jobs.promote_job
"""
from datetime import datetime, timezone

import adapters.search_indexing as search_indexing
import adapters.wordpress as wordpress
from app.models import Article, ScheduledContent, SessionLocal
from core.scheduler import CLAIMABLE, PROMOTE_MAX_ATTEMPTS, due
from core.search_indexing import urls_for_articles


def _submit_for_indexing(slug: str) -> None:
    """Best-effort IndexNow + Google Indexing API submission for a newly-published
    article (site root + the article's own URL — see core.search_indexing).
    Never raises: a submission failure must not abort promotion, the article is
    correctly published to WordPress either way. See jobs/search_indexing_job.py
    for the daily catch-up sweep that covers a failure here."""
    try:
        # Admin-config WP_URL (resolved_wp_url), NOT env — .env is never a runtime config source.
        urls = urls_for_articles(wordpress.resolved_wp_url(), [slug])
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
            # ⚠️ KNOWN GAP, NOT FIXED HERE — "promoting" is an ORPHAN STATE on process death.
            # core.scheduler.CLAIMABLE is ("scheduled", "error"), so nothing ever picks a row
            # back up out of "promoting": one writer (below), no reader, no reaper, no release.
            # The `except` further down covers EXCEPTIONS (it sets status="error" and increments
            # attempts), so the exposed case is the process dying between this claim's commit and
            # the final one — OOM, a Cloud Run revision swap, or the /internal/promote request
            # outliving its timeout. The row then becomes invisible to every future run with
            # attempts never incremented, and the job still reports success. That is the
            # 277-stranded-rows incident (see core/scheduler.py) one state further along.
            #
            # Not fixed in place because both viable fixes are bigger than a patch and one of them
            # is a schema change to a live table:
            #   (a) add a `claimed_at` column and reap stale claims — correct, needs a migration,
            #       and this repo's migration runner has a known ledger defect;
            #   (b) claim by setting "error" + incrementing attempts BEFORE the work, so a death
            #       leaves the row claimable and bounded by PROMOTE_MAX_ATTEMPTS — no migration,
            #       but it changes the meaning of `attempts` and the "published after N earlier
            #       failure(s)" line, i.e. a state-machine change on the publish path.
            # Deciding between them is Jon's call. Until then: a row stuck in "promoting" is
            # stranded and must be reset by hand.
            claimed = (
                db.query(ScheduledContent)
                .filter(ScheduledContent.id == r.id,
                        ScheduledContent.status.in_(CLAIMABLE))
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
            if r.attempts:
                print(f"[promote] scheduled_content {r.id} published after "
                      f"{r.attempts} earlier failure(s)")
        except Exception as e:  # noqa: BLE001
            db.rollback()
            r.status = "error"
            # COUNT the failure. Without this `error` is terminal and one transient WordPress
            # 403 parks the article forever on a job that still reports success — which is
            # exactly what happened to 277 rows between 2026-07-27 and 08-07. The next run
            # retries until PROMOTE_MAX_ATTEMPTS, then leaves it alone.
            r.attempts = (r.attempts or 0) + 1
            db.add(r)
            db.commit()
            errored += 1
            give_up = r.attempts >= PROMOTE_MAX_ATTEMPTS
            print(f"[error] scheduled_content {r.id} attempt {r.attempts}"
                  f"{'/GIVING UP' if give_up else ''}: {str(e)[:120]}")
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

    if totals["promoted"]:
        # Best-effort llms.txt refresh so the AI-crawler manifest tracks the live article
        # index. Never blocks promotion (the job is fail-safe internally, but belt+braces).
        try:
            from jobs.llms_txt_job import run as refresh_llms_txt  # noqa: PLC0415
            print(f"[llms_txt] {refresh_llms_txt()}")
        except Exception as e:  # noqa: BLE001
            print(f"[llms_txt] refresh failed: {str(e)[:120]}")

    return totals


if __name__ == "__main__":
    print(run())
