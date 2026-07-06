"""Job: crawl YouTube comments, flag ones that need replies, and generate draft replies.

Usage:
    python -m jobs.crawl_comments [--limit N]   # N = max videos to process (default 20)

Idempotent: upserts on comment_id. Safe to re-run; existing drafts are not overwritten.
"""
import argparse
import logging
from datetime import datetime, timezone

from adapters.youtube_comments import fetch_comments
from app.llm import chat
from app.models import CommentDraft, Segment, SessionLocal, Video, init_db
from core.comments import needs_reply

log = logging.getLogger(__name__)

_DRAFT_PROMPT_TEMPLATE = """You are the social media voice for Perkins Roofing, a professional residential roofing company.

A viewer left this comment on the video "{title}":
"{comment}"

Video topic / context (transcript excerpt):
{context}

Write a concise, professional reply (2-4 sentences) that:
- Directly addresses the viewer's question or concern
- Reflects genuine roofing expertise
- Ends with a friendly, actionable sentence (e.g. invite them to call, see another video, etc.)
- Does NOT make specific price promises or guarantee timelines
- Does NOT use excessive exclamation marks or hollow filler phrases

Reply only — no preamble, no label, no quotes."""

_CONTEXT_CHARS = 1200  # max transcript chars to feed the LLM


def _get_transcript_context(db, video_id: str) -> str:
    """Return a short excerpt of the video transcript for grounding the draft reply."""
    segments = (
        db.query(Segment)
        .filter(Segment.video_id == video_id)
        .order_by(Segment.start)
        .limit(30)
        .all()
    )
    text = " ".join(s.text for s in segments if s.text)
    return text[:_CONTEXT_CHARS] if text else "(transcript not available)"


def run(limit: int = 20) -> dict:
    """Crawl comments for up to ``limit`` recent videos, upsert, and draft replies.

    Returns a summary dict: {videos_processed, comments_upserted, flagged, drafted, errors}.
    """
    init_db()

    summary = {
        "videos_processed": 0,
        "comments_upserted": 0,
        "flagged": 0,
        "drafted": 0,
        "errors": 0,
    }

    with SessionLocal() as db:
        videos = (
            db.query(Video)
            .order_by(Video.upload_date.desc().nullslast())
            .limit(limit)
            .all()
        )

        for video in videos:
            summary["videos_processed"] += 1
            try:
                comments = fetch_comments(video.id)
            except Exception as exc:
                log.warning("crawl_comments: fetch failed for %s: %s", video.id, exc)
                summary["errors"] += 1
                continue

            # Build set of comment_ids that already have a channel reply
            # (reply_count > 0 is used as a proxy; we don't pull reply threads here)
            for item in comments:
                has_reply = item["reply_count"] > 0
                flag = needs_reply(item["text"], has_reply)

                # Upsert: skip if this comment_id already exists
                existing = (
                    db.query(CommentDraft)
                    .filter(CommentDraft.comment_id == item["comment_id"])
                    .first()
                )
                if existing is None:
                    row = CommentDraft(
                        video_id=video.id,
                        comment_id=item["comment_id"],
                        author=item["author"],
                        comment_text=item["text"],
                        published_at=item["published_at"],
                        needs_reply=flag,
                        draft_reply=None,
                        status="pending",
                        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    )
                    db.add(row)
                    db.flush()  # get row.id
                    summary["comments_upserted"] += 1
                    if flag:
                        summary["flagged"] += 1
                else:
                    row = existing
                    # Update needs_reply flag if it changed (e.g. a reply was posted externally)
                    if existing.needs_reply != flag:
                        existing.needs_reply = flag

                # Generate draft only for flagged comments without a draft yet
                if flag and row.status == "pending" and not row.draft_reply:
                    context = _get_transcript_context(db, video.id)
                    prompt = _DRAFT_PROMPT_TEMPLATE.format(
                        title=video.title or video.id,
                        comment=item["text"],
                        context=context,
                    )
                    try:
                        draft = chat(prompt, want_json=False)
                        if draft and draft.strip():
                            row.draft_reply = draft.strip()
                            row.status = "drafted"
                            summary["drafted"] += 1
                    except Exception as exc:
                        log.warning(
                            "crawl_comments: LLM draft failed for comment %s: %s",
                            item["comment_id"], exc,
                        )

            db.commit()

    return summary


if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Crawl YouTube comments and generate draft replies")
    parser.add_argument("--limit", type=int, default=20, help="Max number of videos to process")
    args = parser.parse_args()
    result = run(limit=args.limit)
    print(result)
