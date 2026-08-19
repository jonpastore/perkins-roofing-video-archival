"""Topic / FAQ graph for the Articles and FAQ consoles.

Read-only. Scores and grouping live in core.topic_graph (pure).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from app.models import Article, CommentDraft, FaqEntry, GraphNode, MiniSeries, SocialPost, Video
from core.competitor_brief import WATCHLIST, gap_from_serp, summarize_scan
from core.engagement_inbox import INBOX_VIDEO, inbox_items, paa_draft_key
from core.social_brief import rank_cut_for_social, rank_film_next, rank_this_week, rank_write_next
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


def _capture_paa(db: Session, ranked: list[dict]) -> int:
    """Idempotent: unanswered PAA become comment_drafts Tim can answer by hand."""
    added = 0
    existing = {
        row.comment_id
        for row in db.query(CommentDraft.comment_id).filter(CommentDraft.platform == "paa").all()
    }
    for gap in ranked:
        for q in gap.get("unanswered_paa") or []:
            key = paa_draft_key(q)
            if not key or key in existing:
                continue
            db.add(CommentDraft(
                video_id=INBOX_VIDEO,
                comment_id=key,
                platform="paa",
                author="People Also Ask",
                comment_text=q,
                needs_reply=True,
                status="pending",
                tenant_id=1,
            ))
            existing.add(key)
            added += 1
    if added:
        db.commit()
    return added


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
    ranked = summarize_scan(rows)
    captured = _capture_paa(db, ranked)
    return {
        "ok": True, "error": None, "queries": ranked, "errors": errors,
        "inbox_added": captured,
    }


@router.get("/engagement-inbox")
def engagement_inbox(
    claims=Depends(require_role("article_read")),
    db: Session = Depends(get_db_session),
):
    """YouTube comments + PAA + film questions. Tim answers; we do not post for him."""
    comments = [
        {
            "comment_id": c.comment_id,
            "comment_text": c.comment_text,
            "video_id": c.video_id,
            "needs_reply": c.needs_reply,
        }
        for c in db.query(CommentDraft).filter(CommentDraft.platform == "youtube").limit(80).all()
    ]
    paa = [
        c.comment_text
        for c in db.query(CommentDraft).filter(
            CommentDraft.platform == "paa", CommentDraft.needs_reply.is_(True),
        ).limit(40).all()
    ]
    brief = social_brief(claims=claims, db=db)
    film_qs: list[str] = []
    for row in brief.get("film_next") or []:
        film_qs.extend(row.get("questions") or [])
    return {"items": inbox_items(comments=comments, paa=paa, film_questions=film_qs)}


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
    genres = graph.get("genres") or []
    cuts = rank_cut_for_social(videos, limit=12)
    films = rank_film_next(genres, comments, limit=8)
    writes = rank_write_next(genres, limit=12)
    return {
        "cut_for_social": cuts,
        "film_next": films,
        "this_week": rank_this_week(cuts, films, writes, limit=5),
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
