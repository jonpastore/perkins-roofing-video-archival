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

SELECTION. The highest-grounding ungenerated topic wins: content_graph topic labels ordered by
total seconds of source video, skipping anything already generated. Grounding depth is the
right ranking because this pipeline's failure mode is invention — core/article_grounding exists
because articles were once ~90% invented — so the topic with the most real transcript behind it
is the one most likely to survive the gate.

Reads content_graph live. aggregated_topics is a snapshot nothing refreshes, so ranking from
it would pick yesterday's catalogue forever. The Topics UI still falls back to the same live
scan when that table is empty.
"""
from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)

# THIS JOB'S OUTPUT IS ITS PRODUCT, and by default none of it reached Cloud Logging.
#
# The API service calls no logging.basicConfig, so the ROOT LOGGER HAS NO HANDLERS AT ALL. A
# record that reaches an empty handler chain falls through to logging.lastResort, which emits at
# WARNING and above — so jobs/social_job's logger.warning appears in prod every 15 minutes while
# every logger.info is silently dropped. Both verified against real prod logs.
#
# Setting the level alone was NOT enough (measured: the first attempt still produced nothing);
# the level decides whether a RECORD is created, a handler decides whether anything is EMITTED.
# So this attaches an explicit stdout handler, which is what Cloud Run captures.
#
# Scoped to this module's logger and propagate=False, so it neither turns on INFO for every
# library in the container nor double-prints if the service later adds real logging config. The
# _configured guard keeps a module re-import from stacking handlers.
def _ensure_stdout_logging() -> None:
    if getattr(logger, "_perkins_stdout_configured", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger._perkins_stdout_configured = True


_ensure_stdout_logging()

#: Clusters generated alongside the pillar. Small on purpose: one campaign a day is a publishing
#: cadence, not a backfill, and every article costs tokens and a compliance loop.
CLUSTERS_PER_RUN = int(os.getenv("DAILY_ARTICLE_CLUSTERS", "2"))

#: Paced go-live rate handed to ScheduledContent. One a day matches the cron's own cadence, so
#: the queue drains at the rate it fills instead of bunching (a bulk release reads as spam).
PER_DAY = int(os.getenv("DAILY_ARTICLE_PER_DAY", "1"))

#: Advisory-lock key — distinct from ingest (8274123), knowify sync (8274124), tokens (8274125),
#: companycam (8274126) and the render range (8300000+).
_LOCK_KEY = 8274127


def next_topic(db, extra_done: set[str] | None = None) -> dict | None:
    """Best ungenerated topic: uncovered, not internal, diversity-weighted opportunity.

    Coverage is keyword/title/slug/pillar — not slug-only — so a SEO-titled article
    still blocks a second pillar on the same subject. Internal genres never publish.
    Opportunity blends YouTube engagement, grounding depth, named-entity AIO boost,
    and a penalty for genres we already over-serve.

    Source is content_graph, not aggregated_topics (that snapshot is stale).
    """
    from app.models import Article, GraphNode, Video  # noqa: PLC0415
    from core.topic_graph import (  # noqa: PLC0415
        classify_label,
        coverage_from_articles,
        pick_next_label,
        slugify,
    )

    cov = coverage_from_articles(
        db.query(Article.slug, Article.pillar_slug, Article.title, Article.focus_keyword).all()
    )
    if extra_done:
        cov = {
            "slugs": set(cov["slugs"]) | extra_done,
            "pillars": set(cov["pillars"]) | extra_done,
            "titles": cov["titles"],
            "keywords": cov["keywords"],
        }

    groups: dict[str, dict] = {}
    for row in db.query(GraphNode).filter(GraphNode.kind == "topics").all():
        label = (row.label or "").strip()
        if not label:
            continue
        key = label.casefold()
        bucket = groups.setdefault(key, {"label": label, "video_ids": set()})
        if row.video_id:
            bucket["video_ids"].add(row.video_id)

    if not groups:
        return None

    video_ids = {vid for g in groups.values() for vid in g["video_ids"]}
    duration_map: dict[str, float] = {}
    views_map: dict[str, tuple[int, int, int]] = {}
    derived: set[str] = set()
    if video_ids:
        from core.video_lineage import derived_video_ids  # noqa: PLC0415
        videos = db.query(Video).filter(Video.id.in_(list(video_ids))).all()
        derived = derived_video_ids(videos)
        for video in videos:
            duration_map[video.id] = video.duration or 0.0
            views_map[video.id] = (
                int(getattr(video, "views", 0) or 0),
                int(getattr(video, "likes", 0) or 0),
                int(getattr(video, "comments", 0) or 0),
            )

    candidates = []
    published_per_genre: dict[str, int] = {}
    for g in groups.values():
        source_ids = {vid for vid in g["video_ids"] if vid not in derived}
        if not source_ids:
            continue
        seconds = sum(duration_map.get(vid, 0.0) for vid in source_ids)
        views = likes = comments = 0
        for vid in source_ids:
            v_ct, like_ct, cmt_ct = views_map.get(vid, (0, 0, 0))
            views += v_ct
            likes += like_ct
            comments += cmt_ct
        gid, _, pub = classify_label(g["label"])
        sl = slugify(g["label"])
        covered = sl in cov["slugs"] or sl in cov["pillars"]
        if covered or not pub:
            published_per_genre[gid] = published_per_genre.get(gid, 0) + 1
        candidates.append({
            "label": g["label"],
            "slug": sl,
            "num_videos": len(source_ids),
            "total_seconds": seconds,
            "views": views,
            "likes": likes,
            "comments": comments,
        })

    picked = pick_next_label(candidates, cov, published_per_genre)
    if picked is None:
        return None
    return {
        "label": picked["label"],
        "slug": picked.get("slug") or slugify(picked["label"]),
        "num_videos": picked["num_videos"],
        "total_seconds": picked["total_seconds"],
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


def _run_dump(db, tenant_id: int, cfg: dict) -> dict:
    """New pillars + supporting clusters. One campaign per call; the cron loops."""
    topic = next_topic(db)
    if topic is None:
        logger.info("daily_content: tenant %s has no ungenerated topics left", tenant_id)
        return {"tenant_id": tenant_id, "skipped": "no ungenerated topics"}

    n_clusters = int(cfg.get("dump_clusters") or CLUSTERS_PER_RUN)
    clusters = _clusters_for(topic["label"], db)[:n_clusters]
    logger.info("daily_content dump: tenant %s topic=%r clusters=%s",
                tenant_id, topic["label"], clusters)

    from jobs.batch_article_job import run_batch  # noqa: PLC0415

    result = run_batch(
        [{"pillar": topic["label"], "clusters": clusters}],
        workers=1,
        critique=True,
        mode="persist",
        status="draft",
        per_day=PER_DAY,
    )
    return {"tenant_id": tenant_id, "mode": "dump", "topic": topic["label"],
            "clusters": clusters, "report": result.get("report") or {}}


def _run_for_tenant(db, tenant_id: int) -> dict:
    """Generate according to CONTENT_GEN_MODE. Returns a summary dict."""
    from core.content_cadence import cadence  # noqa: PLC0415

    cfg = cadence()
    mode = cfg["mode"]
    if mode != "dump":
        return {"tenant_id": tenant_id, "skipped": "content gen off"}
    return _run_dump(db, tenant_id, cfg)


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
