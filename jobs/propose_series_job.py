"""MiniSeries producer job (I/O orchestration — coverage-omitted).

For each Video in the DB:
  1. Skip if a MiniSeries already exists for that video (idempotent).
  2. Count GraphNode rows → build candidate dict.
  3. rank_candidates → take top N.
  4. Load that video's GraphNode rows (label, start).
  5. propose_parts → INSERT MiniSeries(video_id, title, parts_json, approved=0).

Run:
    .venv/bin/python -m jobs.propose_series_job
"""

from __future__ import annotations

import logging

import core.miniseries as miniseries

logger = logging.getLogger(__name__)

# Maximum number of top-ranked candidate videos to process per run.
_DEFAULT_LIMIT = 20


def run(limit: int | None = None) -> dict:
    """Propose MiniSeries for the top-ranked candidate videos.

    Args:
        limit: Cap on the number of candidates to process.  Defaults to
               ``_DEFAULT_LIMIT`` when None.

    Returns:
        Dict::

            {
                "proposed":  int,  # new MiniSeries rows inserted
                "skipped":   int,  # videos that already had a MiniSeries
                "errored":   int,  # videos where processing raised an exception
            }
    """
    from app.models import GraphNode, MiniSeries, SessionLocal, Video  # noqa: PLC0415

    if limit is None:
        limit = _DEFAULT_LIMIT

    db = SessionLocal()
    try:
        videos = db.query(Video).all()

        # Build candidate list: {video_id, duration, graph_nodes}
        candidates_raw: list[dict] = []
        for v in videos:
            count = (
                db.query(GraphNode)
                .filter(GraphNode.video_id == v.id)
                .count()
            )
            candidates_raw.append({
                "video_id": v.id,
                "duration": float(v.duration or 1),
                "graph_nodes": count,
            })

        ranked = miniseries.rank_candidates(candidates_raw)
        top = ranked[:limit]

    finally:
        db.close()

    proposed = 0
    skipped = 0
    errored = 0

    for candidate in top:
        video_id = candidate["video_id"]
        db = SessionLocal()
        try:
            # Idempotency: skip if MiniSeries already exists for this video
            existing = (
                db.query(MiniSeries)
                .filter(MiniSeries.video_id == video_id)
                .first()
            )
            if existing:
                logger.info("propose_series skipped (already exists): video_id=%s", video_id)
                skipped += 1
                continue

            video = db.get(Video, video_id)
            if video is None:
                logger.warning("propose_series: video_id=%s not found, skipping", video_id)
                skipped += 1
                continue

            # Load GraphNode rows for this video
            nodes = (
                db.query(GraphNode)
                .filter(GraphNode.video_id == video_id)
                .all()
            )
            node_dicts = [{"label": n.label or "", "start": float(n.start or 0)} for n in nodes]

            parts = miniseries.propose_parts(
                video_id,
                float(video.duration or 1),
                node_dicts,
            )

            row = MiniSeries(
                video_id=video_id,
                title=video.title or video_id,
                parts_json=parts,
                approved=0,
            )
            db.add(row)
            db.commit()
            logger.info(
                "propose_series inserted MiniSeries: video_id=%s parts=%d",
                video_id,
                len(parts),
            )
            proposed += 1

        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.error("propose_series error video_id=%s: %s", video_id, exc)
            errored += 1
        finally:
            db.close()

    return {"proposed": proposed, "skipped": skipped, "errored": errored}


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO)
    _limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    print(json.dumps(run(limit=_limit), indent=2))
