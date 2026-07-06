"""Comment reply assistant routes.

Export ``router`` only; mount in api/app.py.

Role requirements:
  - manage_articles → admin + web_admin  (all write operations + crawl trigger)
  - article_read    → sales + admin + web_admin  (GET /comments)
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.auth import require_role
from app.llm import chat
from app.models import CommentDraft, SessionLocal, Video

router = APIRouter(prefix="/comments", tags=["comments"])
log = logging.getLogger(__name__)


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
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _claims=Depends(require_role("article_read")),
):
    """Paginated list of comment drafts.
    Returns {total, items: [{id, video_id, video_title, comment_text, draft_reply, status, ...}]}.
    """
    with SessionLocal() as db:
        query = db.query(CommentDraft)

        if status is not None:
            query = query.filter(CommentDraft.status == status)
        if needs_reply is not None:
            query = query.filter(CommentDraft.needs_reply == needs_reply)

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
def regenerate_draft(comment_id: int, _claims=Depends(require_role("manage_articles"))):
    """Regenerate the LLM draft reply for a comment. Overwrites any existing draft."""
    from app.models import Segment

    with SessionLocal() as db:
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
            log.error("regenerate_draft: LLM failed for comment %d: %s", comment_id, exc)
            raise HTTPException(status_code=502, detail=f"LLM error: {exc}") from exc

        if not draft or not draft.strip():
            raise HTTPException(status_code=502, detail="LLM returned an empty reply")

        row.draft_reply = draft.strip()
        row.status = "drafted"
        db.commit()
        db.refresh(row)

        v_title = title
    return _row_to_dict(row, v_title)


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
):
    """Edit the draft reply text and/or set status (ready | dismissed | drafted | pending)."""
    valid_statuses = {"pending", "drafted", "ready", "dismissed"}
    if body.status is not None and body.status not in valid_statuses:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of: {', '.join(sorted(valid_statuses))}",
        )

    with SessionLocal() as db:
        row = db.query(CommentDraft).filter(CommentDraft.id == comment_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Comment not found")

        if body.draft_reply is not None:
            row.draft_reply = body.draft_reply
        if body.status is not None:
            row.status = body.status

        db.commit()
        db.refresh(row)

        video = db.query(Video).filter(Video.id == row.video_id).first()
        title = video.title if video else row.video_id

    return _row_to_dict(row, title)


# ---------------------------------------------------------------------------
# POST /comments/crawl  — trigger the crawl job
# ---------------------------------------------------------------------------

class CrawlRequest(BaseModel):
    limit: int = 20  # max number of videos to process


@router.post("/crawl")
def crawl_comments(
    body: CrawlRequest = CrawlRequest(),
    _claims=Depends(require_role("manage_articles")),
):
    """Trigger the comment crawl + draft generation job for up to ``limit`` videos.
    Returns a summary: {videos_processed, comments_upserted, flagged, drafted, errors}.
    """
    limit = max(1, min(body.limit, 100))
    try:
        from jobs.crawl_comments import run
        return run(limit=limit)
    except Exception as exc:
        log.error("crawl_comments route: job failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
