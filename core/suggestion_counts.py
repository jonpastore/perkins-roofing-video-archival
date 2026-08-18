"""Sidebar badge / digest queue counts. One function, used by the API and digest."""
from __future__ import annotations


def _normalize(label: str) -> str:
    return label.strip().lower()


def to_question(label: str, detail: str) -> str:
    text = (label or "").strip() or (detail or "").strip()
    if not text:
        return ""
    if text.endswith("?"):
        return text
    return text[0].upper() + text[1:] + "?"


def compute_suggestion_counts(db) -> dict[str, int]:
    """Same integers the sidebar badges show. `db` is a SQLAlchemy Session."""
    from app.models import (  # noqa: PLC0415
        Article,
        CommentDraft,
        GraphNode,
        MiniSeries,
        ScheduledContent,
        Segment,
        SocialPost,
        Video,
    )

    topic_rows = db.query(GraphNode).filter(GraphNode.kind == "topics").all()
    articles = db.query(Article).all()
    article_titles_lower = {(a.title or "").strip().lower() for a in articles}

    topic_groups: dict[str, set] = {}
    for row in topic_rows:
        if not row.label:
            continue
        topic_groups.setdefault(_normalize(row.label), set()).add(row.video_id)

    article_topics_count = sum(1 for key in topic_groups if key not in article_titles_lower)

    approved_ids = {s.id for s in db.query(MiniSeries).filter(MiniSeries.approved == 1).all()}
    scheduled_ref_ids = {
        sc.ref_id
        for sc in db.query(ScheduledContent).filter(ScheduledContent.kind == "reel").all()
        if sc.ref_id is not None
    }
    social_series_ids = {
        row.series_id
        for row in db.query(SocialPost.series_id).distinct().all()
        if row.series_id is not None
    }
    reels_count = sum(
        1 for sid in approved_ids
        if str(sid) not in scheduled_ref_ids and sid not in social_series_ids
    )

    all_video_ids_in_db: set[str] = {row.id for row in db.query(Video.id).all()}
    article_contents = [a.content_md or "" for a in articles]
    article_video_ids: set[str] = {
        vid_id for vid_id in all_video_ids_in_db
        if any(vid_id in content for content in article_contents)
    }

    faq_rows = (
        db.query(GraphNode)
        .filter(GraphNode.kind.in_(("objections", "claims")), GraphNode.start.isnot(None))
        .all()
    )
    faqs_count = sum(
        1 for row in faq_rows
        if row.video_id not in article_video_ids
        and bool(to_question(row.label or "", row.detail or ""))
    )

    series_video_ids = {s.video_id for s in db.query(MiniSeries).all() if s.video_id}
    segment_video_ids = {row.video_id for row in db.query(Segment.video_id).distinct().all()}
    graph_video_ids = {row.video_id for row in db.query(GraphNode.video_id).distinct().all()}
    covered_video_ids = segment_video_ids | graph_video_ids
    unused_count = sum(
        1 for v in db.query(Video).all()
        if v.id in covered_video_ids
        and v.id not in article_video_ids
        and v.id not in series_video_ids
    )

    return {
        "article_topics": article_topics_count,
        "reels": reels_count,
        "faqs": faqs_count,
        "unused_videos": unused_count,
        "pending_video_approvals": db.query(MiniSeries).filter(MiniSeries.approved == 0).count(),
        "scheduled_articles": db.query(ScheduledContent).filter(
            ScheduledContent.kind == "article",
            ScheduledContent.status == "scheduled",
        ).count(),
        "scheduled_content": db.query(ScheduledContent).filter(
            ScheduledContent.status.in_(("queued", "scheduled")),
        ).count(),
        "comment_drafts": db.query(CommentDraft).filter(
            CommentDraft.needs_reply.is_(True),
            CommentDraft.status.in_(("pending", "drafted")),
        ).count(),
    }
