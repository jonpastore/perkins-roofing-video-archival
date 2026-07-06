"""Job: crawl YouTube comments, flag ones that need replies, and generate draft replies.

Usage:
    python -m jobs.crawl_comments [--limit N]   # N = max videos to process (default 20)

Idempotent: upserts on comment_id. Safe to re-run; existing drafts are not overwritten.

Environment variables:
    YT_OWNER_CHANNEL_ID   — channel ID of the Perkins Roofing owner account.
                            Comments by this author are skipped entirely.
                            Owner replies in threads suppress the needs_reply flag.
"""
import argparse
import logging
import os
from datetime import datetime, timezone

from adapters.youtube_comments import fetch_comments
from app.llm import chat
from sqlalchemy.exc import IntegrityError

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
_DEFAULT_MAX_DRAFTS = 25  # budget cap per run to limit LLM cost / wall time
_FETCH_MAX_PER_VIDEO = 20  # max comments fetched per video (keep API cost low)


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


def run(limit: int = 20, max_drafts: int = _DEFAULT_MAX_DRAFTS) -> dict:
    """Crawl comments for up to ``limit`` recent videos, upsert, and draft replies.

    Stops generating new drafts once ``max_drafts`` have been created in this
    run (existing drafts are never overwritten — idempotent).

    Comments authored by YT_OWNER_CHANNEL_ID are skipped entirely.
    has_channel_reply is True only when the owner channel has replied in-thread.

    Returns a summary dict: {videos_processed, comments_upserted, flagged, drafted, errors}.
    """
    init_db()

    owner_channel_id: str | None = os.environ.get("YT_OWNER_CHANNEL_ID") or None

    summary = {
        "videos_processed": 0,
        "comments_upserted": 0,
        "flagged": 0,
        "drafted": 0,
        "errors": 0,
    }

    drafts_this_run = 0

    with SessionLocal() as db:
        # Rotate through the whole catalog over successive (cron) runs: least-recently-
        # crawled first — never-crawled (NULL) videos, then the oldest comments_crawled_at.
        videos = (
            db.query(Video)
            .order_by(Video.comments_crawled_at.asc().nullsfirst())
            .limit(limit)
            .all()
        )

        for video in videos:
            if drafts_this_run >= max_drafts:
                log.info("crawl_comments: max_drafts=%d reached, stopping early", max_drafts)
                break

            summary["videos_processed"] += 1
            try:
                comments = fetch_comments(
                    video.id,
                    max_results=_FETCH_MAX_PER_VIDEO,
                    owner_channel_id=owner_channel_id,
                )
            except Exception as exc:
                log.warning("crawl_comments: fetch failed for %s: %s", video.id, exc)
                summary["errors"] += 1
                # Stamp anyway so a persistently-failing video doesn't block the rotation.
                video.comments_crawled_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()
                continue

            for item in comments:
                if drafts_this_run >= max_drafts:
                    break

                # Skip comments posted by the channel owner (never draft a reply to ourselves)
                if owner_channel_id and item["author_channel_id"] == owner_channel_id:
                    continue

                # Use real owner-reply detection (not reply_count proxy)
                has_reply = item["has_owner_reply"]
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
                    try:
                        # SAVEPOINT so a lost insert race doesn't poison the whole batch.
                        with db.begin_nested():
                            db.add(row)
                            db.flush()  # get row.id
                        summary["comments_upserted"] += 1
                        if flag:
                            summary["flagged"] += 1
                    except IntegrityError:
                        # Another concurrent run inserted this comment first — use theirs.
                        row = (
                            db.query(CommentDraft)
                            .filter(CommentDraft.comment_id == item["comment_id"])
                            .first()
                        )
                        if row is None:
                            continue
                else:
                    row = existing
                    # Update needs_reply flag if it changed (e.g. owner replied externally)
                    if existing.needs_reply != flag:
                        existing.needs_reply = flag

                # Generate draft only for flagged comments without a draft yet,
                # and only while under the max_drafts budget
                if flag and row.status == "pending" and not row.draft_reply:
                    if drafts_this_run >= max_drafts:
                        break
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
                            drafts_this_run += 1
                    except Exception as exc:
                        log.warning(
                            "crawl_comments: LLM draft failed for comment %s: %s",
                            item["comment_id"], exc,
                        )
                        summary["errors"] += 1

            # Stamp this video as crawled so the next run rotates to others.
            video.comments_crawled_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()

    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Crawl YouTube comments and generate draft replies")
    parser.add_argument("--limit", type=int, default=20, help="Max number of videos to process")
    parser.add_argument("--max-drafts", type=int, default=_DEFAULT_MAX_DRAFTS, help="Max drafts to generate per run")
    args = parser.parse_args()
    result = run(limit=args.limit, max_drafts=args.max_drafts)
    print(result)
