"""Video approval routes — admin-only mini-series proposal review and approval.

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto the
main app in api/app.py with ``app.include_router(router)``.

Role requirements (from core.authz):
  - approve_video  → admin only (sales is denied; admin passes via the "*" wildcard)
  - manage_series  → admin only
"""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import MiniSeries, Video

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/video", tags=["video"])


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

class Part(BaseModel):
    title: str
    start: float
    end: float
    # Multi-source (topic-driven) series carry a per-part source video; omitted for
    # classic single-source series (which use the MiniSeries.video_id).
    video_id: str | None = None
    video_title: str | None = None


class ApproveRequest(BaseModel):
    parts: list[Part] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Matches Unicode emoji blocks and variation selectors
_EMOJI_RE = re.compile(
    "[\U00002600-\U000027BF"   # misc symbols
    "\U0001F300-\U0001FAFF"    # emoji / pictographs
    "\U0000FE00-\U0000FE0F"    # variation selectors
    "\U0000200D"               # zero-width joiner (emoji ZWJ sequences)
    "\U00020000-\U0002A6DF"    # CJK extension
    "\U0002A700-\U0002CEAF"    # CJK extension
    "\U0002CEB0-\U0002EBEF"    # CJK extension
    "\U0002F800-\U0002FA1F"    # CJK compatibility
    "]+",
    flags=re.UNICODE,
)

# Leading hashtags / symbols (hash, at, *, •, dashes, etc.)
_LEADING_JUNK_RE = re.compile(r"^[\s#@*•\-–—]+")


def clean_label(text: str) -> str:
    """Strip emojis and leading hashtag/symbol characters; collapse whitespace."""
    cleaned = _EMOJI_RE.sub("", text)
    cleaned = _LEADING_JUNK_RE.sub("", cleaned)
    return " ".join(cleaned.split())


def _series_to_dict(s: MiniSeries, video: "Video | None" = None) -> dict:
    """One proposal as the approval queue sees it.

    Takes the VIDEO, not a duration, so every field sourced from it arrives together. The stored
    description rides along for a reason: without it the queue could WRITE a description and never
    READ one back — the reviewer generates, sees the text, reloads, and the card offers "Generate
    description" again as though none existed, so they regenerate, burn another Vertex call and
    silently overwrite. Passing the row (rather than an optional extra argument three of the four
    call sites would forget) is what makes that impossible to reintroduce.
    """
    return {
        "id": s.id,
        "video_id": s.video_id,
        "title": s.title,
        "parts": s.parts_json or [],
        "approved": s.approved,
        "duration": getattr(video, "duration", None),
        "description": getattr(video, "description", None),
        "description_generated_at": (
            video.description_generated_at.isoformat()
            if video is not None and video.description_generated_at else None
        ),
        "description_model": getattr(video, "description_model", None),
    }


def _videos_for(db, video_ids: list[str]) -> dict:
    """Map video_id -> Video row for the given ids (one query, not one per proposal)."""
    if not video_ids:
        return {}
    rows = db.query(Video).filter(Video.id.in_(set(video_ids))).all()
    return {v.id: v for v in rows}


def _build_series_label(series: list[MiniSeries]) -> dict[int, str]:
    """Return {series_id: display_label} with de-duplicated, cleaned labels."""
    # First pass: clean each title
    raw_labels: list[tuple[int, str, str]] = [
        (s.id, s.video_id, clean_label(s.title)) for s in series
    ]

    # Count occurrences of each cleaned label
    label_counts: dict[str, int] = {}
    for _, _, label in raw_labels:
        label_counts[label] = label_counts.get(label, 0) + 1

    result: dict[int, str] = {}
    seen: dict[str, int] = {}  # tracks how many times we've emitted a label
    for s_id, video_id, label in raw_labels:
        if not label or label_counts[label] > 1:
            # Disambiguate: append cleaned video_id or series id
            suffix = clean_label(video_id) if video_id else str(s_id)
            disambig = f"{label} ({suffix})" if label else f"Series {s_id}"
        else:
            disambig = label
        seen[disambig] = seen.get(disambig, 0) + 1
        if seen[disambig] > 1:
            disambig = f"{disambig} [{s_id}]"
        result[s_id] = disambig
    return result


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/proposals")
def list_proposals(
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """Return all pending MiniSeries (approved==0)."""
    rows = db.query(MiniSeries).filter(MiniSeries.approved == 0).all()
    videos = _videos_for(db, [r.video_id for r in rows])
    return [_series_to_dict(r, videos.get(r.video_id)) for r in rows]


@router.post("/{video_id}/description")
def generate_description(
    video_id: str,
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """Generate a description for a video from its transcript and STORE it on the video.

    Reads the operator's VIDEO_DESCRIPTION_PROMPT from platform_config (Admin Config -> Platform
    Settings), renders it against the transcript already in `segments`, and calls the configured
    LLM — Vertex in prod, per LLM_BACKEND.

    The result is persisted to videos.description rather than returned and forgotten, so a
    reviewer who generates on Monday still has it on Tuesday and a later publish step can read it.
    Regenerating overwrites: the prompt is the thing being iterated on, so the newest run wins.

    Returns 400 when the video has no transcript yet — that is a state the reviewer can act on
    (wait for ingestion), not a server error.
    """
    from datetime import datetime, timezone  # noqa: PLC0415

    from app.llm import chat  # noqa: PLC0415
    from app.models import PlatformConfig, PlatformSessionLocal, Segment  # noqa: PLC0415
    from core.video_description import (  # noqa: PLC0415
        DescriptionError,
        clean,
        render_prompt,
        transcript_text,
    )

    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="video not found")

    segments = db.query(Segment).filter(Segment.video_id == video_id).order_by(Segment.start).all()

    # The prompt is PLATFORM-level config (no tenant_id), so it needs the platform session and
    # scope flag — the tenant-scoped `db` cannot see that table's rows.
    with PlatformSessionLocal() as pdb:
        pdb.info["platform_scope"] = True
        row = pdb.get(PlatformConfig, "VIDEO_DESCRIPTION_PROMPT")
        template = (row.value if row else "") or ""

    try:
        rendered = render_prompt(
            template,
            title=video.title,
            duration=video.duration,
            transcript=transcript_text(segments),
        )
    except DescriptionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        raw = chat(rendered.prompt, want_json=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Description generation failed for %s", video_id)
        raise HTTPException(status_code=502, detail=f"description generation failed: {exc}") from exc

    try:
        description = clean(raw)
    except DescriptionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    from app.config import settings  # noqa: PLC0415

    video.description = description
    video.description_generated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    video.description_model = getattr(settings, "LLM_MODEL", None) or "unknown"
    db.commit()

    logger.info(
        "Description generated for %s by %s (%d transcript chars%s)",
        video_id, claims.get("email", "unknown"), rendered.transcript_chars,
        ", truncated" if rendered.truncated else "",
    )
    return {
        "video_id": video_id,
        "description": description,
        "generated_at": video.description_generated_at.isoformat(),
        "model": video.description_model,
        "transcript_chars": rendered.transcript_chars,
        "truncated": rendered.truncated,
    }


class ProposeTopicSeriesRequest(BaseModel):
    topics: int = 10


@router.post("/propose-topic-series")
def propose_topic_series(
    body: ProposeTopicSeriesRequest = ProposeTopicSeriesRequest(),
    claims=Depends(require_role("manage_series")),
):
    """Generate topic-driven MULTI-source reel proposals across the top aggregated
    topics — each series pulls the best on-topic clip from several source videos.
    Returns {proposed, skipped}. Idempotent (skips topics already turned into a series).
    """
    from jobs.propose_topic_series import run as run_topic_series  # noqa: PLC0415

    topics = max(1, min(body.topics, 30))
    return run_topic_series(top_n=topics)


@router.get("/series")
def list_series(
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """Return ALL MiniSeries (approved and unapproved), ordered by id desc.

    Each item includes a ``label`` field: cleaned, de-duplicated display name
    suitable for dropdowns (no raw emojis or hashtag-only names).
    """
    rows = db.query(MiniSeries).order_by(MiniSeries.id.desc()).all()
    labels = _build_series_label(rows)
    return [
        {
            "id": s.id,
            "video_id": s.video_id,
            "title": s.title,
            "approved": s.approved,
            "label": labels[s.id],
        }
        for s in rows
    ]


@router.get("/{series_id}")
def get_series(
    series_id: int,
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """Return one MiniSeries by id (any approval state)."""
    row = db.get(MiniSeries, series_id)
    if row is None:
        raise HTTPException(status_code=404, detail="series not found")
    return _series_to_dict(row, _videos_for(db, [row.video_id]).get(row.video_id))


@router.post("/{series_id}/repropose")
def repropose_series(
    series_id: int,
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """Recompute a MiniSeries' parts with the content-driven selection logic.

    Regenerates ``title`` (cleaned, emoji/hashtag-stripped) and ``parts_json``
    (real second offsets from actual content moments) for an existing series so
    old bad proposals — e.g. the degenerate 0/.25/.5/.75 equal-quarter parts — can
    be fixed in place without a full batch run. Resets ``approved`` to 0 so the
    refreshed proposal is re-reviewed.

    Returns 404 if the series (or its source video) is missing.

    FUTURE WORK: topic-driven MULTI-source series (clips pulled from several
    videos into one series) is a larger step; this only re-derives single-source
    parts for the series' own video.
    """
    from jobs.propose_series_job import compute_series  # noqa: PLC0415

    row = db.get(MiniSeries, series_id)
    if row is None:
        raise HTTPException(status_code=404, detail="series not found")
    try:
        title, parts = compute_series(db, row.video_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    row.title = title
    row.parts_json = parts
    row.approved = 0
    db.flush()
    db.refresh(row)
    return _series_to_dict(row, _videos_for(db, [row.video_id]).get(row.video_id))


@router.post("/{series_id}/approve")
def approve_series(
    series_id: int,
    body: ApproveRequest,
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """Approve a MiniSeries; optionally edit parts in/out points before approval."""
    row = db.get(MiniSeries, series_id)
    if row is None:
        raise HTTPException(status_code=404, detail="series not found")
    if body.parts is not None:
        row.parts_json = [p.model_dump() for p in body.parts]
    row.approved = 1
    db.flush()
    db.refresh(row)
    return _series_to_dict(row, _videos_for(db, [row.video_id]).get(row.video_id))
