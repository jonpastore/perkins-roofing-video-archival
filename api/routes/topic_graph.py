"""Topic / FAQ graph for the Articles and FAQ consoles.

Read-only. Scores and grouping live in core.topic_graph (pure).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import Article, FaqEntry, GraphNode, Video
from core.suggestion_counts import to_question
from core.topic_graph import build_article_graph, build_faq_graph, genre_catalog

router = APIRouter(prefix="/topic-graph", tags=["topic-graph"])


@router.get("/genres")
def list_genres(claims=Depends(require_role("article_read"))):
    return genre_catalog()


def _video_map(db: Session) -> dict[str, Video]:
    return {v.id: v for v in db.query(Video).all()}


def _stats(video: Video | None) -> dict:
    if video is None:
        return {"duration": 0.0, "views": 0, "likes": 0, "comments": 0}
    return {
        "duration": float(video.duration or 0),
        "views": int(video.views or 0),
        "likes": int(video.likes or 0),
        "comments": int(video.comments or 0),
    }


@router.get("")
def topic_graph(
    kind: str = Query("articles"),
    published: str = Query("all"),
    claims=Depends(require_role("article_read")),
    db: Session = Depends(get_db_session),
):
    if kind not in ("articles", "faqs"):
        kind = "articles"
    if published not in ("all", "yes", "no"):
        published = "all"
    videos = _video_map(db)
    if kind == "faqs":
        return _faq_payload(db, videos, published)
    return _article_payload(db, videos, published)


def _article_payload(db: Session, videos: dict[str, Video], published: str) -> dict:
    topics = []
    for row in db.query(GraphNode).filter(GraphNode.kind == "topics").all():
        if not (row.label or "").strip():
            continue
        st = _stats(videos.get(row.video_id))
        topics.append({"label": row.label, "video_id": row.video_id, **st})
    articles = [
        {
            "slug": a.slug,
            "title": a.title,
            "status": a.status,
            "role": a.role,
            "focus_keyword": a.focus_keyword,
            "pillar_slug": a.pillar_slug,
        }
        for a in db.query(Article).all()
    ]
    return build_article_graph(topics, articles, published=published)


def _faq_payload(db: Session, videos: dict[str, Video], published: str) -> dict:
    faqs = []
    used_nodes: set[int] = set()
    for f in db.query(FaqEntry).all():
        used_nodes.add(f.source_node_id)
        st = _stats(videos.get(f.video_id))
        faqs.append({
            "question": f.question,
            "status": f.status,
            "video_id": f.video_id,
            "has_answer": bool(f.answer),
            **st,
        })
    unmined = []
    rows = (
        db.query(GraphNode)
        .filter(GraphNode.kind.in_(("objections", "claims")), GraphNode.start.isnot(None))
        .all()
    )
    for row in rows:
        if row.id in used_nodes:
            continue
        q = to_question(row.label or "", row.detail or "")
        if not q:
            continue
        st = _stats(videos.get(row.video_id))
        unmined.append({"question": q, "video_id": row.video_id, **st})
    return build_faq_graph(faqs, unmined, published=published)
