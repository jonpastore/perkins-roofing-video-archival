"""MiniSeries producer job (I/O orchestration — coverage-omitted).

For each Video in the DB:
  1. Skip if a MiniSeries already exists for that video (idempotent).
  2. Count GraphNode rows → build candidate dict.
  3. rank_candidates → take top N.
  4. Load that video's GraphNode rows (kind, label, start).
  5. build_parts (content-driven, REAL second offsets) → INSERT
     MiniSeries(video_id, title, parts_json, approved=0).

Parts come from actual content moments (LLM over transcript + content graph, same
approach as POST /clips/suggest) with a deterministic content-graph fallback —
NOT from equal quarters of a bogus duration. See build_parts() below.

FUTURE WORK: topic-driven MULTI-source series (one series pulling the best clips
across several source videos) is a larger step; this job builds correct
single-source parts only.

Run:
    .venv/bin/python -m jobs.propose_series_job
"""

from __future__ import annotations

import logging

import core.miniseries as miniseries

logger = logging.getLogger(__name__)

# Maximum number of top-ranked candidate videos to process per run.
_DEFAULT_LIMIT = 20


def build_parts(
    video_title: str | None,
    duration: float,
    segments: list[dict],
    graph_nodes: list[dict],
    *,
    max_clips: int = 5,
) -> list[dict]:
    """Content-driven parts with REAL second offsets and cleaned titles.

    Tries the LLM (grounded in transcript + content graph, like /clips/suggest);
    on any failure or unusable output, falls back to the deterministic
    ``core.miniseries.propose_clips`` selection over content-graph anchors.

    Returns [{title, start, end}] with real second offsets into the source video.
    """
    name = miniseries.clean_title(video_title)
    llm_parts = _llm_parts(name, duration, segments, graph_nodes, max_clips)
    if llm_parts:
        return llm_parts
    return miniseries.propose_clips(video_title, duration, graph_nodes, max_clips=max_clips)


def _llm_parts(
    name: str,
    duration: float,
    segments: list[dict],
    graph_nodes: list[dict],
    max_clips: int,
) -> list[dict]:
    """LLM-selected clip windows; [] on any failure so the caller can fall back."""
    if not segments:
        return []
    try:
        from app.llm import chat  # noqa: PLC0415
    except Exception:  # noqa: BLE001  # pragma: no cover
        return []

    prompt = _build_prompt(name, segments, graph_nodes, max_clips)
    try:
        result = chat(prompt, want_json=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("propose_series LLM failed, using content-graph fallback: %s", exc)
        return []

    clips = result.get("clips") if isinstance(result, dict) else None
    if not clips or not isinstance(clips, list):
        return []

    dur = float(duration or 0.0)
    parts: list[dict] = []
    for c in clips:
        if not isinstance(c, dict) or "start" not in c or "end" not in c:
            continue
        try:
            start = float(c["start"])
            end = float(c["end"])
        except (TypeError, ValueError):
            continue
        if end <= start or start < 0:
            continue
        if dur > 0:
            start = min(start, dur)
            end = min(end, dur)
            if end <= start:
                continue
        topic = str(c.get("title") or c.get("hook") or "")
        parts.append({
            "title": miniseries._part_title(name, topic, len(parts) + 1),
            "start": round(start, 3),
            "end": round(end, 3),
        })
        if len(parts) >= max_clips:
            break
    return parts


def _build_prompt(name: str, segments: list[dict], graph_nodes: list[dict], count: int) -> str:
    """Grounded clip-selection prompt (mirrors api/routes/clips._build_suggest_prompt)."""
    seg_lines = "\n".join(
        f"  [{float(s.get('start') or 0):.1f}s-{float(s.get('end') or 0):.1f}s] {(s.get('text') or '').strip()}"
        for s in segments[:120]
    )
    node_lines = "\n".join(
        f"  [{float(n.get('start') or 0):.1f}s] {n.get('kind', 'topic')}: {n.get('label', '')}"
        for n in graph_nodes[:60]
    )
    return f"""You are a short-form video editor for a roofing company's social media.
Analyse the transcript and content graph below for the video titled "{name}".
Identify the {count} BEST moments to clip as standalone Instagram/TikTok reels (20-60 seconds each).

Select moments that are self-contained, high-energy, and useful for homeowners.

TRANSCRIPT SEGMENTS (start_sec-end_sec: text):
{seg_lines}

CONTENT GRAPH NODES (timestamp: kind: label):
{node_lines}

Return ONLY valid JSON — a single object with a "clips" array. Each clip:
{{"start": <float seconds from transcript>, "end": <float seconds from transcript>, "title": "<short topic/hook>"}}

Rules:
- start and end must be real timestamps from the transcript above (do NOT invent times)
- end - start must be between 20 and 60 seconds
- do not overlap clips
- return exactly {count} clips
- return ONLY the JSON object, no markdown fences
"""


def compute_series(db, video_id: str, *, max_clips: int = 5) -> tuple[str, list[dict]]:
    """Compute (clean_title, content-driven parts) for one video using an open session.

    Loads the Video, its transcript Segments, and Content-Graph nodes, then builds
    content-driven parts with REAL second offsets. Shared by the batch ``run`` job
    and the POST /video/{series_id}/repropose endpoint so both stay in sync.
    """
    from app.models import GraphNode, Segment, Video  # noqa: PLC0415

    video = db.get(Video, video_id)
    if video is None:
        raise ValueError(f"video_id={video_id} not found")

    segments = (
        db.query(Segment)
        .filter(Segment.video_id == video_id)
        .order_by(Segment.start)
        .all()
    )
    seg_dicts = [
        {"text": s.text or "", "start": float(s.start or 0), "end": float(s.end or 0)}
        for s in segments
    ]

    nodes = (
        db.query(GraphNode)
        .filter(GraphNode.video_id == video_id)
        .order_by(GraphNode.start)
        .all()
    )
    node_dicts = [
        {"kind": n.kind or "topics", "label": n.label or "", "start": float(n.start or 0)}
        for n in nodes
    ]

    # When the video title is all hashtags/emojis (clean_title returns ""), fall back
    # to "Perkins Roofing" rather than exposing the raw YouTube video_id in the UI.
    title = miniseries.clean_title(video.title) or "Perkins Roofing"
    parts = build_parts(
        video.title,
        float(video.duration or 0.0),
        seg_dicts,
        node_dicts,
        max_clips=max_clips,
    )
    return title, parts


def _run_for_tenant(db, tenant_id: int, limit: int | None = None) -> dict:
    """Per-tenant series proposal body. Called by for_each_tenant via run()."""
    from app.models import GraphNode, MiniSeries, Video  # noqa: PLC0415

    if limit is None:
        limit = _DEFAULT_LIMIT

    videos = db.query(Video).all()

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

    proposed = 0
    skipped = 0
    errored = 0

    for candidate in top:
        video_id = candidate["video_id"]
        try:
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

            title, parts = compute_series(db, video_id)

            row = MiniSeries(
                video_id=video_id,
                title=title,
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

    return {"proposed": proposed, "skipped": skipped, "errored": errored}


def run(limit: int | None = None) -> dict:
    """Iterate active tenants and propose MiniSeries for each."""
    from app.models import SessionLocal  # noqa: PLC0415
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    totals: dict = {"proposed": 0, "skipped": 0, "errored": 0}

    def _fn(db, tenant_id: int) -> None:
        r = _run_for_tenant(db, tenant_id, limit=limit)
        for k in totals:
            totals[k] += r.get(k, 0)

    for_each_tenant(SessionLocal, _fn)
    return totals


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO)
    _limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    print(json.dumps(run(limit=_limit), indent=2))
