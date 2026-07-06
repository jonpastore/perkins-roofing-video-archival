"""Topic-driven MULTI-source mini-series proposer (I/O orchestration).

For the top aggregated topics, assembles ONE reel series per topic whose parts are
the single best on-topic moment pulled from SEVERAL different source videos — the
multi-source counterpart to jobs/propose_series_job (which is single-source).

Uses only Content-Graph data already primed in the DB (no LLM call here; the graph
was built via the Vertex pipeline). Idempotent: skips a topic that already has a
multi-source series.

Run (Cloud SQL proxy up):
    python -m jobs.propose_topic_series --topics 15
"""
from __future__ import annotations

import argparse
import json
import logging

import core.miniseries as miniseries

logger = logging.getLogger(__name__)

# Suffix that marks a series as topic-driven multi-source (used for idempotency).
_SERIES_SUFFIX = "— Topic Reel"
_MIN_SOURCES = 2  # a multi-source series needs at least two distinct source videos


def _sources_for_topic(db, video_ids: list[str]) -> list[dict]:
    """Load {video_id, video_title, duration, graph_nodes} for each topic video."""
    from app.models import GraphNode, Video  # noqa: PLC0415

    vids = db.query(Video).filter(Video.id.in_(video_ids)).all()
    nodes_by_video: dict[str, list[dict]] = {}
    node_rows = (
        db.query(GraphNode)
        .filter(GraphNode.video_id.in_(video_ids), GraphNode.start.isnot(None))
        .all()
    )
    for n in node_rows:
        nodes_by_video.setdefault(n.video_id, []).append(
            {"label": n.label or "", "start": float(n.start or 0.0), "kind": n.kind or "topics"}
        )
    return [
        {
            "video_id": v.id,
            "video_title": v.title or v.id,
            "duration": float(v.duration or 0.0),
            "graph_nodes": nodes_by_video.get(v.id, []),
        }
        for v in vids
    ]


def run(top_n: int = 15, max_clips: int = 5) -> dict:
    from app.models import AggregatedTopic, MiniSeries, SessionLocal  # noqa: PLC0415

    with SessionLocal() as db:
        topics = (
            db.query(AggregatedTopic)
            .order_by(AggregatedTopic.num_videos.desc())
            .limit(top_n * 2)
            .all()
        )
        existing = {
            s.title for s in db.query(MiniSeries).filter(MiniSeries.title.like(f"%{_SERIES_SUFFIX}%")).all()
        }

        proposed, skipped = 0, 0
        for t in topics:
            if proposed >= top_n:
                break
            label = miniseries.clean_title(t.canonical_label) or t.canonical_label
            title = f"{label} {_SERIES_SUFFIX}"
            if title in existing:
                skipped += 1
                continue

            video_ids = list(t.video_ids or [])
            if len(video_ids) < _MIN_SOURCES:
                skipped += 1
                continue

            sources = _sources_for_topic(db, video_ids)
            parts = miniseries.propose_topic_clips(t.canonical_label, sources, max_clips=max_clips)
            # Require genuinely multi-source output (≥2 distinct videos).
            if len({p["video_id"] for p in parts}) < _MIN_SOURCES:
                skipped += 1
                continue

            db.add(MiniSeries(
                video_id=parts[0]["video_id"],   # primary source (back-compat field)
                title=title,
                parts_json=parts,
                approved=0,
            ))
            existing.add(title)
            proposed += 1
            logger.info("topic series %r: %d parts across %d videos",
                        title, len(parts), len({p["video_id"] for p in parts}))
        db.commit()

    return {"proposed": proposed, "skipped": skipped}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--topics", type=int, default=15)
    ap.add_argument("--max-clips", type=int, default=5)
    a = ap.parse_args()
    print(json.dumps(run(top_n=a.topics, max_clips=a.max_clips), indent=2))
