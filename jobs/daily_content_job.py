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


def next_topic(db, extra_done: set[str] | None = None) -> dict | None:
    """The best ungenerated topic, or None when the catalogue is exhausted.

    Ranked by total_seconds — how much real transcript backs the topic — because this pipeline's
    characteristic failure is inventing content, and the compliance gate rejects what it cannot
    ground. Ranking by num_videos instead would favour a topic mentioned briefly in many clips
    over one covered in depth.

    Source is content_graph, not aggregated_topics. The aggregate table is a snapshot
    nothing currently refreshes; a cron that ranked it would keep picking from a stale
    catalogue after every ingest.
    """
    from api.routes.articles import _slugify  # noqa: PLC0415
    from app.models import GraphNode, Video  # noqa: PLC0415

    done = _generated_slugs(db)
    if extra_done:
        done |= extra_done
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
    derived: set[str] = set()
    if video_ids:
        from core.video_lineage import derived_video_ids  # noqa: PLC0415
        videos = db.query(Video).filter(Video.id.in_(list(video_ids))).all()
        derived = derived_video_ids(videos)
        for video in videos:
            duration_map[video.id] = video.duration or 0.0

    best = None
    for g in groups.values():
        slug = _slugify(g["label"])
        if slug in done:
            continue
        source_ids = {vid for vid in g["video_ids"] if vid not in derived}
        if not source_ids:
            continue
        seconds = sum(duration_map.get(vid, 0.0) for vid in source_ids)
        candidate = {
            "label": g["label"],
            "slug": slug,
            "num_videos": len(source_ids),
            "total_seconds": seconds,
        }
        if best is None or seconds > best["total_seconds"]:
            best = candidate
    return best


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
