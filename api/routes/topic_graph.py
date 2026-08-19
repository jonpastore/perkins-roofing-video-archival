"""Topic / FAQ graph for the Articles and FAQ consoles.

Read-only. Scores and grouping live in core.topic_graph (pure).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import Article, CommentDraft, FaqEntry, GraphNode, MiniSeries, SocialPost, Video
from core.competitor_brief import WATCHLIST, gap_from_serp, summarize_scan
from core.social_brief import rank_cut_for_social, rank_film_next
from core.suggestion_counts import to_question
from core.topic_graph import build_article_graph, build_faq_graph, genre_catalog

router = APIRouter(prefix="/topic-graph", tags=["topic-graph"])


def _our_keywords(db: Session) -> set[str]:
    kws: set[str] = set()
    for slug, title, kw in db.query(Article.slug, Article.title, Article.focus_keyword).all():
        if slug:
            kws.add(slug.replace("-", " "))
        if title:
            kws.add(title)
        if kw:
            kws.add(kw)
    return kws


def _scan_watch_query(wq, our_keywords: set[str], fetch) -> dict:
    gap = gap_from_serp(
        query=wq.query,
        genre_id=wq.genre_id,
        serp=fetch(wq.query),
        our_keywords=our_keywords,
    )
    gap["why"] = wq.why
    return gap


@router.post("/competitor-scan")
def competitor_scan(
    claims=Depends(require_role("article_read")),
    db: Session = Depends(get_db_session),
):
    """On-demand 5-query SERP gap scan. Not called on page load."""
    from adapters.serper import fetch_serp  # noqa: PLC0415

    our = _our_keywords(db)
    rows: list[dict] = []
    errors: list[dict] = []
    for wq in WATCHLIST:
        try:
            rows.append(_scan_watch_query(wq, our, fetch_serp))
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)[:200], "queries": [], "errors": []}
        except Exception as exc:  # noqa: BLE001
            errors.append({"query": wq.query, "error": str(exc)[:200]})
    return {"ok": True, "error": None, "queries": summarize_scan(rows), "errors": errors}


@router.get("/genres")
def list_genres(claims=Depends(require_role("article_read"))):
    return genre_catalog()


@router.get("/social-brief")
def social_brief(
    claims=Depends(require_role("article_read")),
    db: Session = Depends(get_db_session),
):
    """What to cut from existing footage and what Tim should film next."""
    clip_ids = {s.video_id for s in db.query(MiniSeries.video_id).all() if s.video_id}
    posted_series = {
        row[0] for row in db.query(SocialPost.series_id).distinct().all() if row[0] is not None
    }
    posted_ids: set[str] = set()
    if posted_series:
        posted_ids = {
            s.video_id for s in db.query(MiniSeries).filter(MiniSeries.id.in_(posted_series)).all()
            if s.video_id
        }
    videos = []
    for v in db.query(Video).all():
        videos.append({
            "id": v.id,
            "title": v.title,
            "duration": v.duration or 0,
            "views": v.views or 0,
            "likes": v.likes or 0,
            "comments": v.comments or v.comment_count or 0,
            "has_clips": v.id in clip_ids,
            "has_social": v.id in posted_ids,
        })
    comments = [
        {"text": c.comment_text, "video_id": c.video_id}
        for c in db.query(CommentDraft).filter(CommentDraft.needs_reply.is_(True)).limit(200).all()
    ]
    graph = _article_payload(db, _video_map(db), "all")
    return {
        "cut_for_social": rank_cut_for_social(videos, limit=12),
        "film_next": rank_film_next(graph.get("genres") or [], comments, limit=8),
    }


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
