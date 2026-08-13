"""Daily content cron — pick a topic, generate ONE article campaign, schedule its go-live.

WHY THIS EXISTS. There are fourteen Cloud Scheduler jobs and none of them creates content:
`promote-scheduled-content` and `publish-awaiting-social` only MOVE content that already exists.
Article generation has always been admin-driven through the /topics API, which is why the
catalogue sat at 473 articles with nothing new (Jon, 2026-08-13: "we should be publishing daily").

The generation engine already existed and is reused unchanged — jobs.batch_article_job.run_batch
in `publish` mode, which runs the same core.article_criteria compliance gate the admin path uses
and NEVER publishes a non-compliant article. The only thing missing was autonomous topic choice,
which is all this module adds.

WHAT IT DOES NOT DO. It does not publish live. run_batch(status="draft") pushes a WordPress DRAFT
and schedules a paced go-live via ScheduledContent, so the existing promote cron does the
releasing. That keeps ONE publish path (the one with 427 successful releases behind it) rather
than adding a second, and it means a bad run leaves drafts rather than live pages.

SELECTION. The highest-grounding ungenerated topic wins: aggregated_topics ordered by total
seconds of source video, skipping anything already generated. Grounding depth is the right
ranking because this pipeline's failure mode is invention — core/article_grounding exists because
articles were once ~90% invented — so the topic with the most real transcript behind it is the
one most likely to survive the gate.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# INFO is OFF by default in the API service — there is no basicConfig there, so the root logger
# sits at WARNING and everything below it is discarded. These jobs run inside that service (via
# /internal/*), and their OUTPUT IS THE PRODUCT: a daily scan whose findings never reach Cloud
# Logging has run and told nobody, which is the same "correct thing nothing can reach" defect this
# codebase keeps producing. Verified empirically: a logger.warning from jobs/social_job appears in
# prod logs, a logger.info does not.
#
# Set on THIS module's logger only, so the fix does not turn on INFO for every library in the
# process. Records still propagate to uvicorn's root handler, which emits them.
logger.setLevel(logging.INFO)

#: Clusters generated alongside the pillar. Small on purpose: one campaign a day is a publishing
#: cadence, not a backfill, and every article costs tokens and a compliance loop.
CLUSTERS_PER_RUN = int(os.getenv("DAILY_ARTICLE_CLUSTERS", "2"))

#: Paced go-live rate handed to ScheduledContent. One a day matches the cron's own cadence, so
#: the queue drains at the rate it fills instead of bunching (a bulk release reads as spam).
PER_DAY = int(os.getenv("DAILY_ARTICLE_PER_DAY", "1"))

#: Advisory-lock key — distinct from ingest (8274123), knowify sync (8274124), tokens (8274125),
#: companycam (8274126) and the render range (8300000+).
_LOCK_KEY = 8274127


def _generated_slugs(db) -> set[str]:
    """Slugs that already have an article, pillar or cluster.

    Mirrors api.routes.topics._build_generated_set rather than importing it: that module is a
    FastAPI route file, and a cron importing a route module drags the whole API surface into the
    job container for one set comprehension.
    """
    from app.models import Article  # noqa: PLC0415

    out: set[str] = set()
    for slug, pillar_slug in db.query(Article.slug, Article.pillar_slug).all():
        if slug:
            out.add(slug)
        if pillar_slug:
            out.add(pillar_slug)
    return out


def next_topic(db) -> dict | None:
    """The best ungenerated topic, or None when the catalogue is exhausted.

    Ranked by total_seconds — how much real transcript backs the topic — because this pipeline's
    characteristic failure is inventing content, and the compliance gate rejects what it cannot
    ground. Ranking by num_videos instead would favour a topic mentioned briefly in many clips
    over one covered in depth.
    """
    from api.routes.articles import _slugify  # noqa: PLC0415
    from app.models import AggregatedTopic  # noqa: PLC0415

    done = _generated_slugs(db)
    best = None
    for row in db.query(AggregatedTopic).all():
        label = (row.canonical_label or "").strip()
        if not label or _slugify(label) in done:
            continue
        if best is None or (row.total_seconds or 0) > (best.total_seconds or 0):
            best = row
    if best is None:
        return None
    return {
        "label": best.canonical_label,
        "slug": _slugify(best.canonical_label),
        "num_videos": best.num_videos,
        "total_seconds": best.total_seconds,
    }


def _clusters_for(topic_label: str, db) -> list[str]:
    """Cluster keywords under the pillar. Falls back to the pillar alone.

    Subtopic derivation lives in the topics route and is LLM-backed; a failure there must not
    cost the day's article, so the campaign degrades to a pillar-only run rather than aborting.
    """
    try:
        from api.routes.topics import _derive_subtopics  # noqa: PLC0415

        subs = _derive_subtopics(topic_label, "", db) or []
        return [s for s in subs if s and s.strip()][:CLUSTERS_PER_RUN]
    except Exception as exc:  # noqa: BLE001
        logger.warning("daily_content: subtopic derivation failed for %r (%s) — "
                       "running pillar-only", topic_label, exc)
        return []


def _run_for_tenant(db, tenant_id: int) -> dict:
    """Generate one campaign for this tenant. Returns a summary dict."""
    topic = next_topic(db)
    if topic is None:
        logger.info("daily_content: tenant %s has no ungenerated topics left", tenant_id)
        return {"tenant_id": tenant_id, "skipped": "no ungenerated topics"}

    clusters = _clusters_for(topic["label"], db)
    logger.info("daily_content: tenant %s topic=%r (%.0fs of source across %s videos) clusters=%s",
                tenant_id, topic["label"], topic["total_seconds"] or 0,
                topic["num_videos"], clusters)

    from jobs.batch_article_job import run_batch  # noqa: PLC0415

    result = run_batch(
        [{"pillar": topic["label"], "clusters": clusters}],
        workers=1,              # one campaign; concurrency here only fights the compliance loop
        critique=True,          # the gate is the whole point — never generate ungated
        mode="publish",         # push COMPLIANT articles to WP; non-compliant are skipped
        status="draft",         # draft + ScheduledContent; promote-scheduled-content releases it
        per_day=PER_DAY,
    )
    report = result.get("report") or {}
    logger.info("daily_content: tenant %s done topic=%r %s", tenant_id, topic["label"], report)
    return {"tenant_id": tenant_id, "topic": topic["label"],
            "clusters": clusters, "report": report}


def run() -> dict:
    """Cron entrypoint. Single-flight, one campaign per tenant per run."""
    from app.models import SessionLocal  # noqa: PLC0415
    from core.single_flight import single_flight  # noqa: PLC0415
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    with single_flight(SessionLocal, _LOCK_KEY) as ok:
        if not ok:
            # A previous day's run still going is the case that matters: article generation loops
            # against the compliance gate and can outlast an hour. Overlapping runs would pick
            # the same topic (nothing is written until an article persists) and generate it twice.
            logger.warning("daily_content: another run holds the lock — skipping")
            return {"skipped": "already running"}

        results: list[dict] = []

        def _fn(db, tenant_id: int) -> None:
            results.append(_run_for_tenant(db, tenant_id))

        for_each_tenant(SessionLocal, _fn)
        return {"tenants": results}


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(run(), indent=2, default=str))
