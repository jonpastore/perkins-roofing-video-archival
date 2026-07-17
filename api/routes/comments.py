"""Comment reply assistant routes.

Export ``router`` only; mount in api/app.py.

Role requirements:
  - manage_articles → admin + web_admin  (all write operations + crawl trigger)
  - article_read    → sales + admin + web_admin  (GET /comments)
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.llm import chat
from app.models import CommentDraft, Video
from core.ratelimit import SingleFlightGuard

router = APIRouter(prefix="/comments", tags=["comments"])
log = logging.getLogger(__name__)

# Single-flight + 30-second cooldown guard for the expensive crawl fan-out.
# One guard per process; Cloud Run multi-instance is defense-in-depth only —
# add a platform_config daily budget counter for a durable cross-instance limit.
_crawl_guard = SingleFlightGuard(cooldown_seconds=30)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: CommentDraft, video_title: Optional[str] = None) -> dict:
    return {
        "id": row.id,
        "video_id": row.video_id,
        "video_title": video_title or row.video_id,
        "video_url": f"https://youtu.be/{row.video_id}",
        "comment_id": row.comment_id,
        "platform": row.platform,
        "author": row.author,
        "comment_text": row.comment_text,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "needs_reply": row.needs_reply,
        "draft_reply": row.draft_reply,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ---------------------------------------------------------------------------
# GET /comments
# ---------------------------------------------------------------------------

@router.get("")
def list_comments(
    status: Optional[str] = Query(None, description="Filter by status: pending|drafted|ready|dismissed"),
    needs_reply: Optional[bool] = Query(None, description="Filter by needs_reply flag"),
    platform: Optional[str] = Query(None, description="Filter by platform, e.g. youtube"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _claims=Depends(require_role("article_read")),
    db: Session = Depends(get_db_session),
):
    """Paginated list of comment drafts.
    Returns {total, items: [{id, video_id, video_title, comment_text, draft_reply, status, platform, ...}]}.
    """
    query = db.query(CommentDraft)

    if status is not None:
        query = query.filter(CommentDraft.status == status)
    if needs_reply is not None:
        query = query.filter(CommentDraft.needs_reply == needs_reply)
    if platform is not None:
        query = query.filter(CommentDraft.platform == platform)

    total = query.count()
    rows = (
        query.order_by(CommentDraft.published_at.desc().nullslast())
        .offset(offset)
        .limit(limit)
        .all()
    )

    video_ids = {r.video_id for r in rows}
    titles: dict[str, str] = {}
    if video_ids:
        vrows = db.query(Video.id, Video.title).filter(Video.id.in_(video_ids)).all()
        titles = {v.id: v.title for v in vrows}

    items = [_row_to_dict(r, titles.get(r.video_id)) for r in rows]
    return {"total": total, "items": items}


# ---------------------------------------------------------------------------
# POST /comments/{id}/draft  — regenerate draft reply
# ---------------------------------------------------------------------------

@router.post("/{comment_id}/draft")
def regenerate_draft(
    comment_id: int,
    _claims=Depends(require_role("manage_articles")),
    db: Session = Depends(get_db_session),
):
    """Regenerate the LLM draft reply for a comment. Overwrites any existing draft."""
    from app.models import Segment

    row = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Comment not found")

    video = db.query(Video).filter(Video.id == row.video_id).first()
    title = video.title if video else row.video_id

    segments = (
        db.query(Segment)
        .filter(Segment.video_id == row.video_id)
        .order_by(Segment.start)
        .limit(30)
        .all()
    )
    context = " ".join(s.text for s in segments if s.text)[:1200] or "(transcript not available)"

    prompt = (
        f'You are the social media voice for Perkins Roofing, a professional residential roofing company.\n\n'
        f'A viewer left this comment on the video "{title}":\n'
        f'"{row.comment_text}"\n\n'
        f"Video topic / context (transcript excerpt):\n{context}\n\n"
        "Write a concise, professional reply (2-4 sentences) that directly addresses the viewer's "
        "question or concern, reflects genuine roofing expertise, and ends with a friendly actionable "
        "sentence. No price promises, no excessive exclamation marks.\n\nReply only — no preamble."
    )

    try:
        draft = chat(prompt, want_json=False)
    except Exception as exc:
        log.error("regenerate_draft: LLM failed for comment %d: %s", comment_id, exc, exc_info=True)
        raise HTTPException(status_code=502, detail="comment draft generation failed") from exc

    if not draft or not draft.strip():
        raise HTTPException(status_code=502, detail="LLM returned an empty reply")

    row.draft_reply = draft.strip()
    row.status = "drafted"
    db.flush()
    db.refresh(row)

    return _row_to_dict(row, title)


# ---------------------------------------------------------------------------
# PUT /comments/{id}  — edit draft / change status
# ---------------------------------------------------------------------------

class UpdateRequest(BaseModel):
    draft_reply: Optional[str] = None
    status: Optional[str] = None  # ready | dismissed | drafted | pending


@router.put("/{comment_id}")
def update_comment(
    comment_id: int,
    body: UpdateRequest,
    _claims=Depends(require_role("manage_articles")),
    db: Session = Depends(get_db_session),
):
    """Edit the draft reply text and/or set status (ready | dismissed | drafted | pending | posted)."""
    valid_statuses = {"pending", "drafted", "ready", "dismissed", "posted"}
    if body.status is not None and body.status not in valid_statuses:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of: {', '.join(sorted(valid_statuses))}",
        )

    row = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Comment not found")

    if body.draft_reply is not None:
        row.draft_reply = body.draft_reply
    if body.status is not None:
        row.status = body.status

    db.flush()
    db.refresh(row)

    video = db.query(Video).filter(Video.id == row.video_id).first()
    title = video.title if video else row.video_id

    return _row_to_dict(row, title)


# ---------------------------------------------------------------------------
# YouTube reply posting (OAuth, scope youtube.force-ssl)
# ---------------------------------------------------------------------------

@router.get("/reply-config")
def reply_config(_claims=Depends(require_role("article_read"))):
    """Report whether direct YouTube reply posting is configured (owner OAuth token present)."""
    from adapters.youtube_comments import reply_oauth_configured
    return {"oauth_configured": reply_oauth_configured()}


@router.post("/{comment_id}/post")
def post_reply_to_youtube(
    comment_id: int,
    _claims=Depends(require_role("manage_articles")),
    db: Session = Depends(get_db_session),
):
    """Post the saved draft reply to YouTube (OAuth, scope youtube.force-ssl) and mark it posted.

    503 if reply OAuth isn't configured (no owner refresh token) — the UI keeps draft/copy mode.
    400 if there is no draft to post. 502 on a YouTube API failure.
    """
    from adapters.youtube_comments import post_reply

    row = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Comment not found")
    reply_text = (row.draft_reply or "").strip()
    if not reply_text:
        raise HTTPException(status_code=400, detail="no draft reply to post")

    # E1 content-safety gate (fail-closed) — the reply is a generated artifact and MUST
    # pass BEFORE it reaches YouTube, same as every caption in jobs/distribute_job.py.
    # Human approval is not a substitute: the gate is the platform-wide invariant.
    from adapters.safety import run_gate  # noqa: PLC0415
    gate_result = run_gate(reply_text, "social")
    if not gate_result.passed:
        log.warning("post_reply_to_youtube: reply BLOCKED by safety gate for %d: %s",
                    comment_id, gate_result.reason)
        raise HTTPException(status_code=422, detail=f"reply blocked by safety gate: {gate_result.reason}")

    try:
        post_reply(row.comment_id, reply_text)
    except RuntimeError as exc:
        # OAuth not configured — a deliberate, recoverable state.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log.error("post_reply_to_youtube: YouTube post failed for %d: %s", comment_id, exc, exc_info=True)
        raise HTTPException(status_code=502, detail="posting the reply to YouTube failed") from exc

    row.status = "posted"
    db.flush()
    db.refresh(row)

    video = db.query(Video).filter(Video.id == row.video_id).first()
    title = video.title if video else row.video_id

    return _row_to_dict(row, title)


# ---------------------------------------------------------------------------
# POST /comments/crawl  — trigger the crawl job
# ---------------------------------------------------------------------------

class CrawlRequest(BaseModel):
    limit: int = 20      # max number of videos to process
    max_drafts: int = 25  # max LLM drafts to generate per run


@router.post("/crawl")
def crawl_comments(
    body: CrawlRequest = CrawlRequest(),
    _claims=Depends(require_role("manage_articles")),
):
    """Trigger the comment crawl + draft generation job for up to ``limit`` videos.
    Returns a summary: {videos_processed, comments_upserted, flagged, drafted, errors}.

    Guarded by a single-flight lock + 30-second cooldown to prevent quota abuse:
    - 409 if a crawl is already running
    - 429 if a crawl ran less than 30 seconds ago
    """
    limit = max(1, min(body.limit, 100))
    max_drafts = max(1, min(body.max_drafts, 200))
    _crawl_guard.acquire_or_raise("crawl")
    try:
        from jobs.crawl_comments import run
        return run(limit=limit, max_drafts=max_drafts)
    except HTTPException:
        raise
    except Exception as exc:
        log.error("crawl_comments route: job failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="comment crawl failed") from exc
    finally:
        _crawl_guard.release("crawl")
