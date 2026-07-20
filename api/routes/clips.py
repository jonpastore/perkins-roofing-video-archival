"""Clip Studio routes — AI-suggested short-form clips from archived source videos.

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto
the main app in api/app.py with ``app.include_router(router)``.

Role requirements (from core.authz):
  - approve_video  → admin + web_admin (sales is denied)

Endpoints
---------
POST /clips/suggest              — LLM suggests the best clippable moments from a video's transcript.
POST /clips/search               — Natural-language clip search across the whole video corpus.
POST /clips/save                 — Upsert a curated MiniSeries (approved=1) from chosen clips.
GET  /clips/renderable           — Approved MiniSeries without a SocialPost (ready to render).
POST /clips/{series_id}/render   — Trigger the Cloud Run render JOB for a single series.
GET  /clips/{series_id}/render-status — Poll rendered/total part counts for a series.

IAM note: the api-run-sa service account must have:
  - roles/run.developer (or the custom run.jobs.run permission) on the render job
  - roles/iam.serviceAccountUser (actAs) on jobs-sa@{project}.iam.gserviceaccount.com
  A parent/operator must grant those before the trigger endpoint will work in prod.
"""
from __future__ import annotations

import logging
import os
import tempfile

import google.auth
import google.auth.transport.requests
import requests as _requests
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import GraphNode, MiniSeries, PlatformConfig, PlatformSessionLocal, Segment, SocialPost, Video
from core.clip_search import search_to_clips
from core.platform_specs import PLATFORM_PRESETS, PLATFORM_SPECS
from core.platform_specs import validate as validate_platform
from core.render_spec import ClipRenderSpec, get_clips, get_render_spec, set_render_spec
from core.scene_detect import scene_boundaries

# GCP coordinates — read from env so deploy.sh / Terraform own the values.
_GCP_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "video-archival-and-content-gen")
_GCP_REGION = os.getenv("GCP_REGION", "us-central1")
_RENDER_JOB_NAME = "render"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clips", tags=["clips"])

# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class SuggestRequest(BaseModel):
    video_id: str
    count: int = 4
    platform: str | None = None  # tune suggestions to a target platform's preset


class ViralityScore(BaseModel):
    """Per-clip heuristic virality score returned by the LLM.

    Each dimension scores 0–25; total is the sum (0–100).
    Labelled "Heuristic score" in the UI — honest until we have real engagement data.
    """
    hook_strength: int = 0
    emotion: int = 0
    pacing: int = 0
    value: int = 0
    total: int = 0
    rationale: str = ""


class ClipSuggestion(BaseModel):
    start: float
    end: float
    title: str
    caption: str
    hook: str
    reason: str
    summary: str = ""
    virality: ViralityScore = ViralityScore()


class SuggestResponse(BaseModel):
    video_id: str
    video_title: str
    suggestions: list[ClipSuggestion]


class ClipSearchRequest(BaseModel):
    prompt: str
    k: int = Field(default=8, ge=1, le=20)


class ClipPart(BaseModel):
    title: str
    start: float
    end: float
    hook: str = ""


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
        "parts": get_clips(s.parts_json),
        "approved": s.approved,
    }


def _reels_bucket() -> str:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT env var is required")
    return f"{project}-reels"


# Hard cap on brand-scene upload size (10 MiB).
_BRAND_UPLOAD_MAX_BYTES = 10 * 1024 * 1024

# Hard cap on brand video upload size (200 MiB).
_BRAND_VIDEO_MAX_BYTES = 200 * 1024 * 1024

# Magic-byte signatures for accepted image formats.
# Each entry: (content_type, prefix_bytes_to_match)
_IMAGE_MAGIC: list[tuple[str, bytes]] = [
    ("image/png",  b"\x89PNG\r\n"),
    ("image/jpeg", b"\xff\xd8\xff"),
    # WEBP: "RIFF" at 0, "WEBP" at 8
    ("image/webp", b"RIFF"),
]


def _sniff_image_type(data: bytes) -> str | None:
    """Return the sniffed MIME type for *data*, or None if not a recognised image."""
    if data[:6] == b"\x89PNG\r\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image/webp"
    return None


_MIME_TO_EXT = {
    "image/png":  "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


def _sniff_mp4(data: bytes) -> bool:
    """Return True if *data* looks like an MP4/MOV container.

    Checks for the ftyp ISO Base Media File Format box which is present in
    virtually all MP4/M4V/MOV files.  The box starts at byte 4 with the ASCII
    tag ``ftyp``; major brands checked include ``isom``, ``mp41``, ``mp42``,
    ``M4V ``, ``M4A ``, ``qt  `` (QuickTime).  We accept any brand because
    ffmpeg can transcode non-standard flavours.
    """
    if len(data) < 12:
        return False
    # ftyp box: bytes 4-7 == b"ftyp"
    if data[4:8] == b"ftyp":
        return True
    # Some files have a free/skip/wide box before ftyp; scan the first 64 bytes.
    for offset in range(0, min(64, len(data) - 8)):
        if data[offset:offset + 4] == b"ftyp":
            return True
    return False


@router.post("/upload-brand-scene")
def upload_brand_scene(
    scene: str,
    file: UploadFile = File(...),
    claims=Depends(require_role("approve_video")),
):
    """Upload a title or closing brand-scene image and persist its GCS path.

    ``scene`` must be ``"title"`` or ``"closing"``.

    Stores the image in the reels GCS bucket under ``brand/{scene}_scene.<ext>``
    and writes the resulting ``gs://`` path to the platform_config key
    ``REEL_TITLE_IMG`` or ``REEL_CLOSING_IMG`` respectively.

    Security hardening:
    - Reads in bounded chunks; rejects files exceeding 10 MiB.
    - Sniffs magic bytes to verify the file is PNG/JPEG/WEBP; rejects anything
      that doesn't match regardless of the client-supplied Content-Type.
    - Sets the GCS content_type from the sniffed type, not the client header.

    Returns: {key, gcs_path}
    """
    if scene not in ("title", "closing"):
        raise HTTPException(status_code=422, detail="scene must be 'title' or 'closing'")

    # Read in bounded chunks — hard cap at _BRAND_UPLOAD_MAX_BYTES.
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = file.file.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _BRAND_UPLOAD_MAX_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"file exceeds maximum allowed size of {_BRAND_UPLOAD_MAX_BYTES // (1024*1024)} MiB",
                )
            chunks.append(chunk)
    finally:
        file.file.close()

    data = b"".join(chunks)

    # Sniff magic bytes — reject non-images regardless of client Content-Type.
    sniffed_type = _sniff_image_type(data)
    if sniffed_type is None:
        raise HTTPException(status_code=422, detail="file must be a valid PNG, JPEG, or WEBP image")

    ext = _MIME_TO_EXT[sniffed_type]
    config_key = "REEL_TITLE_IMG" if scene == "title" else "REEL_CLOSING_IMG"
    object_key = f"brand/{scene}_scene.{ext}"

    try:
        bucket_name = _reels_bucket()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        from google.cloud import storage as gcs_storage  # noqa: PLC0415
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="google-cloud-storage not installed",
        ) from exc

    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
        tmp_path = tmp.name
        tmp.write(data)

    try:
        client = gcs_storage.Client()
        blob = client.bucket(bucket_name).blob(object_key)
        # Use sniffed content_type — never trust the client header.
        blob.upload_from_filename(tmp_path, content_type=sniffed_type)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"GCS upload failed: {exc}") from exc
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    gcs_path = f"gs://{bucket_name}/{object_key}"

    # Persist to platform_config (platform-level table, no tenant_id — use PlatformSessionLocal)
    from datetime import datetime, timezone  # noqa: PLC0415

    email = claims.get("email", "unknown")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with PlatformSessionLocal() as db:
        db.info["platform_scope"] = True
        row = db.get(PlatformConfig, config_key)
        if row is None:
            row = PlatformConfig(key=config_key, value=gcs_path, updated_at=now, updated_by=email)
            db.add(row)
        else:
            row.value = gcs_path
            row.updated_at = now
            row.updated_by = email
        db.commit()

    logger.info("Brand scene uploaded: %s -> %s", config_key, gcs_path)
    return {"key": config_key, "gcs_path": gcs_path}


@router.post("/upload-brand-video")
def upload_brand_video(
    scene: str,
    file: UploadFile = File(...),
    claims=Depends(require_role("approve_video")),
):
    """Upload a brand intro or outro VIDEO and persist its GCS path to platform config.

    ``scene`` must be ``"intro"`` or ``"outro"``.

    Stores the file in the reels GCS bucket under ``brand/{scene}_video.mp4``
    and writes the resulting ``gs://`` path to ``BRAND_INTRO_VIDEO`` or
    ``BRAND_OUTRO_VIDEO`` in platform_config so render_job picks it up.

    Security hardening:
    - Reads in bounded chunks; rejects files exceeding 200 MiB.
    - Sniffs the ftyp ISO Base Media box to verify the file is MP4; rejects
      anything that doesn't match regardless of client-supplied Content-Type.

    Returns: {key, gcs_path}
    """
    if scene not in ("intro", "outro"):
        raise HTTPException(status_code=422, detail="scene must be 'intro' or 'outro'")

    # Read first chunk to sniff magic bytes, then continue bounded read.
    chunks: list[bytes] = []
    total = 0
    first_chunk: bytes = b""
    try:
        while True:
            chunk = file.file.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _BRAND_VIDEO_MAX_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"file exceeds maximum allowed size of {_BRAND_VIDEO_MAX_BYTES // (1024 * 1024)} MiB",
                )
            chunks.append(chunk)
            if not first_chunk:
                first_chunk = chunk
    finally:
        file.file.close()

    # Sniff magic bytes — reject non-MP4 regardless of client Content-Type.
    if not _sniff_mp4(first_chunk):
        raise HTTPException(status_code=422, detail="file must be a valid MP4 video")

    config_key = "BRAND_INTRO_VIDEO" if scene == "intro" else "BRAND_OUTRO_VIDEO"
    object_key = f"brand/{scene}_video.mp4"

    try:
        bucket_name = _reels_bucket()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        from google.cloud import storage as gcs_storage  # noqa: PLC0415
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="google-cloud-storage not installed",
        ) from exc

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
        tmp_path = tmp.name
        for chunk in chunks:
            tmp.write(chunk)

    try:
        client = gcs_storage.Client()
        blob = client.bucket(bucket_name).blob(object_key)
        blob.upload_from_filename(tmp_path, content_type="video/mp4")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"GCS upload failed: {exc}") from exc
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    gcs_path = f"gs://{bucket_name}/{object_key}"

    # Persist to platform_config (platform-level table, no tenant_id — use PlatformSessionLocal)
    from datetime import datetime, timezone  # noqa: PLC0415

    email = claims.get("email", "unknown")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with PlatformSessionLocal() as db:
        db.info["platform_scope"] = True
        row = db.get(PlatformConfig, config_key)
        if row is None:
            row = PlatformConfig(key=config_key, value=gcs_path, updated_at=now, updated_by=email)
            db.add(row)
        else:
            row.value = gcs_path
            row.updated_at = now
            row.updated_by = email
        db.commit()

    logger.info("Brand video uploaded: %s -> %s", config_key, gcs_path)
    return {"key": config_key, "gcs_path": gcs_path}


def _platform_guidance(platform: str | None) -> str:
    """One-line platform tuning drawn from PLATFORM_PRESETS/PLATFORM_SPECS, or "" when
    no (known) platform is given. Augments the suggestion prompt — it never replaces
    the content-driven selection."""
    if not platform or platform not in PLATFORM_PRESETS:
        return ""
    p = PLATFORM_PRESETS[platform]
    spec = PLATFORM_SPECS.get(platform)
    cap = f" Keep each clip under {spec.max_length_seconds}s." if spec else ""
    return (
        f"\nTarget platform: {platform}. Tune for it — open with a ~{p['hook_seconds']}s hook, "
        f"{p['caption_style']} captions, ~{p['hashtag_count']} hashtags, {p['text_cadence']} pacing.{cap}"
    )


def _build_suggest_prompt(
    video_title: str,
    segments: list,
    nodes: list,
    count: int,
    platform: str | None = None,
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
Identify the {count} BEST moments to clip as standalone Instagram/TikTok reels (20-60 seconds each).{_platform_guidance(platform)}

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
  "hook":  "<the actual opening line/sentence spoken in the clip that works as a scroll-stopping hook — quote or closely paraphrase the transcript>",
  "summary": "<2-3 sentence plain-English summary of what happens in this specific clip, grounded in the transcript text for that timespan>",
  "reason": "<why this specific moment is a strong clip — reference the content, not a generic explanation>",
  "virality": {{
    "hook_strength": <int 0-25, how scroll-stopping the opening hook is>,
    "emotion":       <int 0-25, emotional resonance / relatability for homeowners>,
    "pacing":        <int 0-25, energy and momentum — tight editing potential, no dead air>,
    "value":         <int 0-25, practical value or insight delivered for the viewer>,
    "total":         <int 0-100, sum of the four dimensions above>,
    "rationale":     "<one sentence explaining the total score — be specific to this clip>"
  }}
}}

Rules:
- start and end must be real timestamps from the transcript above (do NOT invent times)
- end - start must be between 20 and 60 seconds
- do not overlap clips
- hook must be specific to this clip's content — never a generic phrase like "Did you know?" or "Watch this"
- summary must describe what is actually said/shown in this clip's timespan
- virality.total must equal hook_strength + emotion + pacing + value
- return exactly {count} clips
- return ONLY the JSON object, no markdown fences
"""


def _parse_virality(raw: object) -> dict:
    """Defensively parse a virality dict from LLM output.

    Accepts any input shape; clamps ints to [0, 25] per dimension and
    recomputes total from the four dimensions so the UI always sees a
    consistent sum.  Returns all-zero defaults on any parse failure.
    """
    defaults: dict = {
        "hook_strength": 0,
        "emotion": 0,
        "pacing": 0,
        "value": 0,
        "total": 0,
        "rationale": "",
    }
    if not isinstance(raw, dict):
        return defaults

    def _clamp(key: str) -> int:
        try:
            v = int(raw.get(key, 0) or 0)
        except (TypeError, ValueError):
            v = 0
        return max(0, min(25, v))

    hook_strength = _clamp("hook_strength")
    emotion = _clamp("emotion")
    pacing = _clamp("pacing")
    value = _clamp("value")
    total = hook_strength + emotion + pacing + value

    rationale = str(raw.get("rationale", "") or "")[:300]

    return {
        "hook_strength": hook_strength,
        "emotion": emotion,
        "pacing": pacing,
        "value": value,
        "total": total,
        "rationale": rationale,
    }


def _llm_suggestions(
    video_title: str,
    segments: list,
    nodes: list,
    count: int,
    platform: str | None = None,
) -> list[dict]:
    """Call the LLM to get clip suggestions; fall back to propose_parts on failure."""
    from app.llm import chat  # noqa: PLC0415

    prompt = _build_suggest_prompt(video_title, segments, nodes, count, platform=platform)
    try:
        result = chat(prompt, want_json=True)
        clips = result.get("clips") if isinstance(result, dict) else None
        if clips and isinstance(clips, list) and len(clips) > 0:
            validated: list[dict] = []
            for c in clips:
                if not all(k in c for k in ("start", "end", "title")):
                    continue
                virality = _parse_virality(c.get("virality"))
                validated.append({
                    "start": float(c["start"]),
                    "end": float(c["end"]),
                    "title": str(c.get("title", "")),
                    "caption": str(c.get("caption", "")),
                    "hook": str(c.get("hook", "")),
                    "reason": str(c.get("reason", "")),
                    "summary": str(c.get("summary", "")),
                    "virality": virality,
                })
            if validated:
                return validated[:count]
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM clip suggestion failed, falling back to propose_parts: %s", exc)

    # Fallback: derive clips from propose_parts
    return _fallback_suggestions(segments, nodes, count)


def _segments_in_range(segments: list, start: float, end: float) -> str:
    """Return transcript text for segments overlapping [start, end]."""
    texts = [
        (s.text or "").strip()
        for s in segments
        if s.end > start and s.start < end and (s.text or "").strip()
    ]
    return " ".join(texts)


def _fallback_suggestions(segments: list, nodes: list, count: int) -> list[dict]:
    """Derive clip suggestions from propose_parts when LLM is unavailable.

    Unlike the old version, this populates hook and summary from the actual
    transcript text for each clip's timespan so the fallback output is not
    generic boilerplate.
    """
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
    results = []
    for p in parts:
        transcript_text = _segments_in_range(segments, p["start"], p["end"])
        # Hook: first ~100 chars of transcript text, trimmed to a sentence boundary.
        hook = ""
        if transcript_text:
            hook_raw = transcript_text[:120].strip()
            # Trim to last complete word if cut mid-word
            if len(transcript_text) > 120 and " " in hook_raw:
                hook_raw = hook_raw.rsplit(" ", 1)[0]
            hook = hook_raw.rstrip(",;") + ("…" if len(transcript_text) > 120 else "")
        # Summary: up to 300 chars of the transcript window, describing the clip content.
        summary = transcript_text[:300].rstrip() + ("…" if len(transcript_text) > 300 else "")
        results.append({
            "start": p["start"],
            "end": p["end"],
            "title": p["title"],
            "caption": "",
            "hook": hook,
            "summary": summary,
            "reason": f"Content graph segment: {p['title']}",
            "virality": _parse_virality(None),
        })
    return results


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/suggest", response_model=SuggestResponse)
def suggest_clips(
    body: SuggestRequest,
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """AI-suggest the best clippable moments from a video's transcript.

    Grounds suggestions in actual transcript timestamps.  Falls back to
    propose_parts logic when the LLM is unavailable or returns unusable output.
    Returns 404 when the video has no transcript segments.
    """
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

    suggestions_raw = _llm_suggestions(video_title, segments, nodes, body.count, platform=body.platform)

    suggestions = [ClipSuggestion(**s) for s in suggestions_raw]
    return SuggestResponse(
        video_id=body.video_id,
        video_title=video_title,
        suggestions=suggestions,
    )


@router.post("/search")
def search_clips(
    body: ClipSearchRequest,
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """Natural-language clip search across the whole video corpus (cross-video ClipAnything).

    Retrieves candidate transcript chunks via app.retrieval.hybrid_search (over-fetching
    3x the requested count so windowing/dedup has room to work with), converts them into
    clip-length candidate windows, then LLM-ranks them against the viral-moment rubric —
    falling back to plain retrieval-score ordering if the LLM call fails or is unavailable.

    Returns: {"results": [{video_id, start, end, score, reason, text}, ...]}
    """
    from app.retrieval import hybrid_search  # noqa: PLC0415

    hits = hybrid_search(body.prompt, k=max(body.k * 3, 24), db=db)
    chunks = [
        {
            "video_id": ch.video_id,
            "start": ch.start,
            "end": ch.end,
            "text": ch.text or "",
            "score": score,
        }
        for ch, score in hits.get("chunks", [])
    ]

    def _score_fn(prompt: str) -> str:
        from app.llm import chat  # noqa: PLC0415
        return chat(prompt, want_json=False)

    results = search_to_clips(body.prompt, chunks, score_fn=_score_fn)
    return {"results": results[:body.k]}


@router.post("/save")
def save_clips(
    body: SaveRequest,
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """Upsert a curated MiniSeries (approved=1) from admin-chosen clip boundaries.

    If a MiniSeries already exists for this video_id it is updated in-place;
    otherwise a new row is inserted.  The series is always set to approved=1
    so the existing render pipeline can process it immediately.
    """
    if not body.parts:
        raise HTTPException(status_code=422, detail="parts must not be empty")

    parts_json = [p.model_dump() for p in body.parts]

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
        db.flush()
        db.refresh(existing)
        return _series_to_dict(existing)

    series = MiniSeries(
        video_id=body.video_id,
        title=body.title,
        parts_json=parts_json,
        approved=1,
        tenant_id=db.info["tenant_id"],
    )
    db.add(series)
    db.flush()
    db.refresh(series)
    return _series_to_dict(series)


@router.get("/renderable")
def list_renderable(
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """Return approved MiniSeries that have not yet been rendered (no SocialPost row).

    A series is considered rendered when at least one SocialPost with a non-null
    gcs_url exists for it — matching the idempotency logic in render_job.
    """
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
                "parts_count": len(get_clips(s.parts_json)),
            })
    return result


@router.get("/transcript")
def clip_transcript(
    video_id: str,
    start: float,
    end: float,
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """Return transcript segments that overlap the given [start, end] window.

    Response::

        {
            "video_id": str,
            "start": float,
            "end": float,
            "text": str,           # all matching segment text joined by space
            "segments": [          # individual segments for fine-grained display
                {"start": float, "end": float, "text": str}
            ]
        }

    Returns 404 if the video does not exist.
    Returns an empty segments list (not 404) if the video has no transcript in range.
    """
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="video not found")

    segs = (
        db.query(Segment)
        .filter(
            Segment.video_id == video_id,
            Segment.end > start,
            Segment.start < end,
        )
        .order_by(Segment.start)
        .all()
    )

    segments_out = [
        {"start": s.start, "end": s.end, "text": (s.text or "").strip()}
        for s in segs
        if (s.text or "").strip()
    ]

    return {
        "video_id": video_id,
        "start": start,
        "end": end,
        "text": " ".join(s["text"] for s in segments_out),
        "segments": segments_out,
    }


def _cloud_run_bearer_token() -> str:
    """Return a fresh Bearer token using the service's own ADC credentials."""
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


class RenderSpecRequest(BaseModel):
    """Body for PUT /clips/{series_id}/render_spec."""
    reframe: bool = False
    speaker_tracking: bool = False
    captions: dict = {}
    speech_cleanup: bool = False
    broll: dict = {}
    music: dict = {}
    fx: dict = {}
    emoji_highlights: bool = False
    aspects: list[str] = []
    audio_enhance: bool = False


@router.get("/{series_id}/render_spec")
def get_render_spec_route(
    series_id: int,
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """Return the current render spec for a series (defaults when none saved).

    Response: the ClipRenderSpec dict matching the JSON contract in core/render_spec.
    """
    series = db.get(MiniSeries, series_id)
    if series is None or not series.approved:
        raise HTTPException(status_code=404, detail="series not found or not approved")
    spec = get_render_spec(series.parts_json)
    return spec.to_dict()


@router.put("/{series_id}/render_spec")
def save_render_spec_route(
    series_id: int,
    body: RenderSpecRequest,
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """Save render options for a series without triggering a render.

    Stores the spec inside parts_json (no new DB column).  Upgrades legacy
    list-form parts_json to envelope form transparently.

    Returns the saved spec dict.
    """
    raw = body.model_dump()
    try:
        spec = ClipRenderSpec.model_validate(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    series = db.get(MiniSeries, series_id)
    if series is None or not series.approved:
        raise HTTPException(status_code=404, detail="series not found or not approved")
    series.parts_json = set_render_spec(series.parts_json, spec)
    db.flush()

    logger.info("render_spec saved: series_id=%d spec=%s", series_id, spec.to_dict())
    return spec.to_dict()


@router.post("/{series_id}/render")
def trigger_render(
    series_id: int,
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """Kick off the Cloud Run render JOB for a single approved MiniSeries.

    Executes the Cloud Run Job named ``render`` via the Cloud Run Admin API v2,
    injecting ``RENDER_SERIES_ID={series_id}`` as a container env override so
    the job processes only that series instead of doing a full sweep.

    Returns 404 if the series does not exist or is not yet approved.
    Returns 502/503 on Cloud Run API errors (no traceback leaked to the caller).

    IAM (parent must grant before this works in prod):
      - api-run-sa needs  run.jobs.run  on the render job
        (roles/run.developer covers it, or a custom role with just run.jobs.run)
      - api-run-sa needs  iam.serviceAccounts.actAs  on jobs-sa
        (roles/iam.serviceAccountUser on jobs-sa@{project}.iam.gserviceaccount.com)
    """
    # 404 guard — series must exist and be approved.
    series = db.get(MiniSeries, series_id)
    if series is None or not series.approved:
        raise HTTPException(status_code=404, detail="series not found or not approved")

    job_parent = (
        f"projects/{_GCP_PROJECT}/locations/{_GCP_REGION}/jobs/{_RENDER_JOB_NAME}"
    )
    url = f"https://run.googleapis.com/v2/{job_parent}:run"
    body = {
        "overrides": {
            "containerOverrides": [
                {
                    "env": [
                        {"name": "RENDER_SERIES_ID", "value": str(series_id)}
                    ]
                }
            ]
        }
    }

    try:
        token = _cloud_run_bearer_token()
        resp = _requests.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Cloud Run job trigger network error: %s", exc)
        raise HTTPException(status_code=503, detail="could not reach Cloud Run API") from exc

    if not resp.ok:
        logger.error(
            "Cloud Run job trigger failed: status=%s body=%s",
            resp.status_code,
            resp.text[:400],
        )
        raise HTTPException(
            status_code=502,
            detail=f"Cloud Run API returned {resp.status_code}",
        )

    data = resp.json()
    execution_name = data.get("name", "")
    logger.info("Render job execution started: %s (series_id=%d)", execution_name, series_id)
    return {"execution": execution_name, "status": "started"}


@router.get("/{series_id}/preview-url")
def clip_preview_url(
    series_id: int,
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """Return a short-lived signed GCS URL for in-app video preview.

    Finds the first rendered SocialPost for this series (any platform),
    extracts the gs:// URI stored in gcs_url, and mints a 1-hour V4 signed
    GET URL (no Content-Disposition — video players need a bare URL).

    Returns::

        {"preview_url": str, "expires_in": 3600}

    Returns 404 when the series does not exist, is not approved, or has not
    been rendered yet.  Returns 502 when GCS signing fails (IAM not configured).
    """
    series = db.get(MiniSeries, series_id)
    if series is None or not series.approved:
        raise HTTPException(status_code=404, detail="series not found or not approved")

    rendered = (
        db.query(SocialPost)
        .filter(
            SocialPost.series_id == series_id,
            SocialPost.gcs_url.isnot(None),
        )
        .first()
    )
    if rendered is None:
        raise HTTPException(status_code=404, detail="series has not been rendered yet")

    gcs_uri = rendered.gcs_url  # gs://bucket/key
    if not gcs_uri or not gcs_uri.startswith("gs://"):
        raise HTTPException(status_code=404, detail="rendered URL is not a GCS URI")

    try:
        without_scheme = gcs_uri[len("gs://"):]
        slash = without_scheme.index("/")
        bucket = without_scheme[:slash]
        key = without_scheme[slash + 1:]
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=500, detail="malformed GCS URI in SocialPost") from exc

    try:
        from adapters.storage import signed_get_url  # noqa: PLC0415

        url = signed_get_url(bucket, key, ttl_seconds=3600)
    except RuntimeError as exc:
        logger.error("preview-url: GCS signing failed for series %d: %s", series_id, exc)
        raise HTTPException(status_code=502, detail="could not generate preview URL") from exc

    return {"preview_url": url, "expires_in": 3600}


@router.get("/{series_id}/render-status")
def render_status(
    series_id: int,
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """Return render progress for a MiniSeries.

    Counts SocialPost rows (matching render_job idempotency logic) to determine
    how many parts have been rendered vs. the total declared in parts_json.

    Returns:
        {rendered: bool, parts_total: int, parts_rendered: int}

    404 if the series does not exist or is not approved.
    """
    series = db.get(MiniSeries, series_id)
    if series is None or not series.approved:
        raise HTTPException(status_code=404, detail="series not found or not approved")

    parts_total = len(get_clips(series.parts_json))
    parts_rendered = (
        db.query(SocialPost.part)
        .filter(
            SocialPost.series_id == series_id,
            SocialPost.gcs_url.isnot(None),
        )
        .distinct()
        .count()
    )

    return {
        "rendered": parts_rendered >= parts_total and parts_total > 0,
        "parts_total": parts_total,
        "parts_rendered": parts_rendered,
    }


class PreflightBody(BaseModel):
    platforms: list[str]
    meta: dict  # duration_seconds, width, height, size_mb, codec_video, codec_audio


@router.post("/{clip_id}/preflight")
def preflight_clip(
    clip_id: str,
    body: PreflightBody,
    claims=Depends(require_role("approve_video")),
):
    """Per-platform pass/fail for a clip's rendered meta vs platform_specs, so the UI
    shows a ✓/⚠ per target platform before scheduling. clip_id is reserved for a future
    per-clip meta lookup; today the caller supplies meta in the body."""
    if not body.platforms:
        raise HTTPException(status_code=422, detail="platforms must not be empty")
    results = {}
    for p in body.platforms:
        failures = validate_platform(body.meta, p)
        results[p] = {"ok": not failures, "failures": failures}
    return {"results": results}


@router.get("/scenes")
def clip_scenes(
    video_id: str,
    start: float,
    end: float,
    claims=Depends(require_role("approve_video")),
    db: Session = Depends(get_db_session),
):
    """Suggested scene-cut points (seconds) from speech gaps within [start, end].

    Derived from stored word timestamps — no video download. Returns
    {"video_id", "boundaries": [float, ...]} (empty when no transcript in range)."""
    from app.models import Word  # noqa: PLC0415
    rows = (
        db.query(Word)
        .filter(Word.video_id == video_id, Word.start >= start, Word.start < end)
        .order_by(Word.start)
        .all()
    )
    words = [{"word": r.word or "", "start": float(r.start or 0.0)} for r in rows]
    return {"video_id": video_id, "boundaries": scene_boundaries(words)}
