"""Clip Studio routes — AI-suggested short-form clips from archived source videos.

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto
the main app in api/app.py with ``app.include_router(router)``.

Role requirements (from core.authz):
  - approve_video  → admin + web_admin (sales is denied)

Endpoints
---------
POST /clips/suggest   — LLM suggests the best clippable moments from a video's transcript.
POST /clips/save      — Upsert a curated MiniSeries (approved=1) from chosen clips.
GET  /clips/renderable — Approved MiniSeries without a SocialPost (ready to render).
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_role
from app.models import GraphNode, MiniSeries, Segment, SessionLocal, SocialPost, Video

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clips", tags=["clips"])

# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class SuggestRequest(BaseModel):
    video_id: str
    count: int = 4


class ClipSuggestion(BaseModel):
    start: float
    end: float
    title: str
    caption: str
    hook: str
    reason: str


class SuggestResponse(BaseModel):
    video_id: str
    video_title: str
    suggestions: list[ClipSuggestion]


class ClipPart(BaseModel):
    title: str
    start: float
    end: float


class SaveRequest(BaseModel):
    video_id: str
    title: str
    parts: list[ClipPart]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _series_to_dict(s: MiniSeries) -> dict:
    return {
        "id": s.id,
        "video_id": s.video_id,
        "title": s.title,
        "parts": s.parts_json or [],
        "approved": s.approved,
    }


def _build_suggest_prompt(
    video_title: str,
    segments: list,
    nodes: list,
    count: int,
) -> str:
    """Build an LLM prompt for clip suggestion grounded in actual transcript timestamps."""
    seg_lines = "\n".join(
        f"  [{s.start:.1f}s-{s.end:.1f}s] {(s.text or '').strip()}"
        for s in segments[:120]  # cap to avoid context overflow
    )
    node_lines = "\n".join(
        f"  [{n.start:.1f}s] {n.kind}: {n.label}"
        for n in nodes[:60]
    )
    return f"""You are a short-form video editor for a roofing company's social media.
Analyse the transcript and content graph below for the video titled "{video_title}".
Identify the {count} BEST moments to clip as standalone Instagram/TikTok reels (20-60 seconds each).

Select moments that are:
- Self-contained (no context needed from outside the clip)
- High-energy hooks, punchy answers, or strong calls to action
- Genuinely useful or surprising for homeowners

TRANSCRIPT SEGMENTS (start_sec-end_sec: text):
{seg_lines}

CONTENT GRAPH NODES (timestamp: kind: label):
{node_lines}

Return ONLY valid JSON — a single object with a "clips" array. Each clip:
{{
  "start": <float seconds, must match a real transcript timestamp>,
  "end":   <float seconds, must match a real transcript timestamp>,
  "title": "<short clip title>",
  "caption": "<Instagram/TikTok caption with hashtags>",
  "hook":  "<opening hook sentence for the clip>",
  "reason": "<why this is a strong clip>"
}}

Rules:
- start and end must be real timestamps from the transcript above (do NOT invent times)
- end - start must be between 20 and 60 seconds
- do not overlap clips
- return exactly {count} clips
- return ONLY the JSON object, no markdown fences
"""


def _llm_suggestions(
    video_title: str,
    segments: list,
    nodes: list,
    count: int,
) -> list[dict]:
    """Call the LLM to get clip suggestions; fall back to propose_parts on failure."""
    from app.llm import chat  # noqa: PLC0415

    prompt = _build_suggest_prompt(video_title, segments, nodes, count)
    try:
        result = chat(prompt, want_json=True)
        clips = result.get("clips") if isinstance(result, dict) else None
        if clips and isinstance(clips, list) and len(clips) > 0:
            validated: list[dict] = []
            for c in clips:
                if not all(k in c for k in ("start", "end", "title")):
                    continue
                validated.append({
                    "start": float(c["start"]),
                    "end": float(c["end"]),
                    "title": str(c.get("title", "")),
                    "caption": str(c.get("caption", "")),
                    "hook": str(c.get("hook", "")),
                    "reason": str(c.get("reason", "")),
                })
            if validated:
                return validated[:count]
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM clip suggestion failed, falling back to propose_parts: %s", exc)

    # Fallback: derive clips from propose_parts
    return _fallback_suggestions(segments, nodes, count)


def _fallback_suggestions(segments: list, nodes: list, count: int) -> list[dict]:
    """Derive clip suggestions from propose_parts when LLM is unavailable."""
    import core.miniseries as miniseries  # noqa: PLC0415

    if not segments:
        return []

    duration = max((s.end for s in segments if s.end), default=60.0)
    node_dicts = [{"label": n.label or "", "start": float(n.start or 0)} for n in nodes]

    parts = miniseries.propose_parts(
        "fallback",
        duration,
        node_dicts,
        min_parts=min(count, 4),
        max_parts=count,
    )
    return [
        {
            "start": p["start"],
            "end": p["end"],
            "title": p["title"],
            "caption": "",
            "hook": "",
            "reason": "auto-derived from content graph",
        }
        for p in parts
    ]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/suggest", response_model=SuggestResponse)
def suggest_clips(
    body: SuggestRequest,
    claims=Depends(require_role("approve_video")),
):
    """AI-suggest the best clippable moments from a video's transcript.

    Grounds suggestions in actual transcript timestamps.  Falls back to
    propose_parts logic when the LLM is unavailable or returns unusable output.
    Returns 404 when the video has no transcript segments.
    """
    with SessionLocal() as db:
        video = db.get(Video, body.video_id)
        if video is None:
            raise HTTPException(status_code=404, detail="video not found")

        segments = (
            db.query(Segment)
            .filter(Segment.video_id == body.video_id)
            .order_by(Segment.start)
            .all()
        )
        if not segments:
            raise HTTPException(
                status_code=404,
                detail="video has no transcript — cannot suggest clips",
            )

        nodes = (
            db.query(GraphNode)
            .filter(GraphNode.video_id == body.video_id)
            .order_by(GraphNode.start)
            .all()
        )

        video_title = video.title or body.video_id

    suggestions_raw = _llm_suggestions(video_title, segments, nodes, body.count)

    suggestions = [ClipSuggestion(**s) for s in suggestions_raw]
    return SuggestResponse(
        video_id=body.video_id,
        video_title=video_title,
        suggestions=suggestions,
    )


@router.post("/save")
def save_clips(
    body: SaveRequest,
    claims=Depends(require_role("approve_video")),
):
    """Upsert a curated MiniSeries (approved=1) from admin-chosen clip boundaries.

    If a MiniSeries already exists for this video_id it is updated in-place;
    otherwise a new row is inserted.  The series is always set to approved=1
    so the existing render pipeline can process it immediately.
    """
    if not body.parts:
        raise HTTPException(status_code=422, detail="parts must not be empty")

    parts_json = [p.model_dump() for p in body.parts]

    with SessionLocal() as db:
        video = db.get(Video, body.video_id)
        if video is None:
            raise HTTPException(status_code=404, detail="video not found")

        existing = (
            db.query(MiniSeries)
            .filter(MiniSeries.video_id == body.video_id)
            .first()
        )
        if existing:
            existing.title = body.title
            existing.parts_json = parts_json
            existing.approved = 1
            db.commit()
            db.refresh(existing)
            return _series_to_dict(existing)

        series = MiniSeries(
            video_id=body.video_id,
            title=body.title,
            parts_json=parts_json,
            approved=1,
        )
        db.add(series)
        db.commit()
        db.refresh(series)
        return _series_to_dict(series)


@router.get("/renderable")
def list_renderable(
    claims=Depends(require_role("approve_video")),
):
    """Return approved MiniSeries that have not yet been rendered (no SocialPost row).

    A series is considered rendered when at least one SocialPost with a non-null
    gcs_url exists for it — matching the idempotency logic in render_job.
    """
    with SessionLocal() as db:
        approved = (
            db.query(MiniSeries)
            .filter(MiniSeries.approved == 1)
            .order_by(MiniSeries.id.desc())
            .all()
        )

        rendered_ids = {
            row.series_id
            for row in db.query(SocialPost.series_id)
            .filter(SocialPost.gcs_url.isnot(None))
            .all()
        }

        result = []
        for s in approved:
            if s.id not in rendered_ids:
                result.append({
                    **_series_to_dict(s),
                    "parts_count": len(s.parts_json or []),
                })
        return result
