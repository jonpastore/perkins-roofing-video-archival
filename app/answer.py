"""Grounded 'Ask Tim' answer with ABSTENTION + citations (council requirement). Below the
confidence threshold it refuses rather than hallucinating — protects the brand on a public widget.
Abstention gate + prompt construction are pure (core.answer); the chat() call is I/O.

Cache layer (migration 0025 / core.ask_cache):
  - Embed the query once; probe ask_cache via pgvector cosine (SQLite: exact question_norm match).
  - Hit (similarity >= 0.95, not stale): increment hit_count, return cached answer immediately.
  - Miss: run the full pipeline, then write-through to ask_cache (deduped by question_norm).

Pre-seeding from faq_entries is a follow-up; the cache self-populates from live /ask traffic.
PIPELINE_VERSION must be bumped whenever the embedding model or answer prompt changes so stale
entries are bypassed and eventually replaced.
"""
import numpy as np

from core.answer import build_answer_prompt, build_faq_answer_prompt, should_abstain
from core.ask_cache import (
    build_cache_entry,
    is_stale,
    normalize_question,
    should_serve,
)
from core.retrieval import link

from .config import settings
from .llm import chat, embed
from .models import AskCache, GraphNode, SessionLocal, Video
from .retrieval import hybrid_search

PIPELINE_VERSION = "v1"


def _is_pg() -> bool:
    """True when the configured DB is PostgreSQL (pgvector available)."""
    return settings.DB_URL.startswith("postgres")


def _probe_cache(query_embedding: list, query_norm: str, db):
    """Return (AskCache row | None, float similarity).

    Postgres: cosine ANN via halfvec; SQLite: exact question_norm match (similarity=1.0).
    """
    if _is_pg():
        from pgvector.psycopg import register_vector
        from sqlalchemy import text
        register_vector(db.connection().connection.driver_connection)
        q_arr = np.array(query_embedding, dtype=np.float32)
        row = db.execute(
            text(
                "SELECT id, 1 - (embedding::halfvec(3072) <=> CAST(:q AS halfvec(3072))) AS sim "
                "FROM ask_cache ORDER BY embedding::halfvec(3072) <=> CAST(:q AS halfvec(3072)) LIMIT 1"
            ),
            {"q": q_arr},
        ).fetchone()
        if row is None:
            return None, 0.0
        entry = db.get(AskCache, row.id)
        return entry, float(row.sim)
    # SQLite: exact norm match only
    entry = db.query(AskCache).filter(AskCache.question_norm == query_norm).first()
    return (entry, 1.0) if entry else (None, 0.0)


def _write_cache(question: str, query_embedding: list, answer_dict: dict, db):
    """Insert a new cache entry if question_norm is not already present for this tenant."""
    norm = normalize_question(question)
    existing = db.query(AskCache).filter(AskCache.question_norm == norm).first()
    if existing is not None:
        return
    entry_dict = build_cache_entry(question, answer_dict, PIPELINE_VERSION)
    entry_dict["embedding"] = query_embedding
    tenant_id = db.info.get("tenant_id", 1)
    row = AskCache(
        question=entry_dict["question"],
        question_norm=entry_dict["question_norm"],
        embedding=entry_dict["embedding"],
        answer_json=entry_dict["answer_json"],
        pipeline_version=entry_dict["pipeline_version"],
        hit_count=0,
        tenant_id=tenant_id,
    )
    db.add(row)
    db.flush()


def ask(query, k=8, db=None):
    # db: caller-passed (RLS-stamped) session; used but never closed here.

    # ── Cache probe (embed once; reuse for retrieval) ────────────────────────
    query_embedding = embed([query])[0]
    query_norm = normalize_question(query)

    if db is not None:
        cached_entry, sim = _probe_cache(query_embedding, query_norm, db)
        if (cached_entry is not None
                and should_serve(sim)
                and not is_stale(
                    cached_entry.created_at,
                    cached_entry.pipeline_version,
                    PIPELINE_VERSION,
                )):
            cached_entry.hit_count = (cached_entry.hit_count or 0) + 1
            db.flush()
            return {**cached_entry.answer_json, "cached": True}

    # ── Full pipeline ─────────────────────────────────────────────────────────
    r = hybrid_search(query, k, db=db)
    chunks = r["chunks"]
    top = max((sc for _, sc in chunks), default=0.0)
    if not chunks or should_abstain(top, settings.ABSTAIN_THRESHOLD):
        return {"answer": "I couldn't find that in Tim's videos.", "abstained": True,
                "confidence": round(top, 2), "citations": [], "sources": []}

    vids = {c.video_id for c, _ in chunks}
    s = db or SessionLocal()
    gp = s.query(GraphNode).filter(
        GraphNode.video_id.in_(vids),
        GraphNode.kind.in_(("objections", "claims", "ctas"))).all()
    titles = {v.id: v.title for v in s.query(Video.id, Video.title).filter(Video.id.in_(vids))}
    if db is None:
        s.close()

    key_points = [(link(g.video_id, g.start), g.label or g.detail) for g in gp[:20]]
    contexts = [(link(c.video_id, c.start), c.text) for c, _ in chunks]
    prompt = build_answer_prompt(query, contexts, key_points)
    # Descriptive sources (video title + snippet + timestamp) so the UI can label each clip
    # instead of a bare timestamp. `citations` kept as bare links for the embed widget.
    sources = [{
        "url": link(c.video_id, c.start),
        "video_id": c.video_id,
        "t": int(c.start or 0),
        "title": titles.get(c.video_id) or c.video_id,
        "snippet": (c.text or "").strip()[:160],
    } for c, _ in chunks]
    answer_dict = {
        "answer": chat(prompt),
        "abstained": False,
        "confidence": round(top, 2),
        "citations": [link(c.video_id, c.start) for c, _ in chunks],
        "sources": sources,
    }

    # ── Write-through (only when we have a stamped tenant session) ────────────
    if db is not None:
        _write_cache(query, query_embedding, answer_dict, db)

    return answer_dict


def answer_faq(question, k=6, db=None):
    """Concise, professional FAQ answer with numbered ``link {n}`` citations at the end.

    Unlike ``ask`` (the public widget, which cites inline), this produces a tight
    2-4 sentence brand-professional answer with [n] markers, then appends a single
    ``Sources:`` line of markdown links — ``[link 1](url) · [link 2](url)`` — so the
    console and the WordPress FAQ page render clean numbered citations, not raw URLs.

    Returns {answer, abstained, confidence, sources}. On abstain, answer="" so the
    caller can leave the entry unanswered rather than store a filler paragraph.
    """
    r = hybrid_search(question, k, db=db)
    chunks = r["chunks"]
    top = max((sc for _, sc in chunks), default=0.0)
    if not chunks or should_abstain(top, settings.ABSTAIN_THRESHOLD):
        return {"answer": "", "abstained": True, "confidence": round(top, 2), "sources": []}

    # Dedupe sources by video (one citation per video), best-ranked first, cap at 3.
    order, per_video = [], {}
    for c, _ in chunks:
        per_video.setdefault(c.video_id, []).append(c)
        if c.video_id not in order:
            order.append(c.video_id)
    order = order[:3]

    s = db or SessionLocal()
    titles = {v.id: v.title for v in s.query(Video.id, Video.title).filter(Video.id.in_(order))}
    if db is None:
        s.close()

    sources, prompt_sources = [], []
    for i, vid in enumerate(order, start=1):
        cs = per_video[vid]
        first = cs[0]
        title = titles.get(vid) or vid
        text = " ".join((c.text or "").strip() for c in cs)[:1200]
        prompt_sources.append((i, title, text))
        sources.append({
            "n": i, "video_id": vid, "t": int(first.start or 0),
            "title": title, "url": link(vid, first.start),
        })

    body = (chat(build_faq_answer_prompt(question, prompt_sources)) or "").strip()
    if not body or body.upper().startswith("NO_ANSWER"):
        return {"answer": "", "abstained": True, "confidence": round(top, 2), "sources": []}

    cites = " · ".join(f"[link {s['n']}]({s['url']})" for s in sources)
    answer = f"{body}\n\nSources: {cites}" if cites else body
    return {"answer": answer, "abstained": False, "confidence": round(top, 2), "sources": sources}
