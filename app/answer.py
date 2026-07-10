"""Grounded 'Ask Tim' answer with ABSTENTION + citations (council requirement). Below the
confidence threshold it refuses rather than hallucinating — protects the brand on a public widget.
Abstention gate + prompt construction are pure (core.answer); the chat() call is I/O."""
from core.answer import build_answer_prompt, build_faq_answer_prompt, should_abstain
from core.retrieval import link

from .config import settings
from .llm import chat
from .models import GraphNode, SessionLocal, Video
from .retrieval import hybrid_search


def ask(query, k=8, db=None):
    # db: caller-passed (RLS-stamped) session; used but never closed here.
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
    return {"answer": chat(prompt), "abstained": False, "confidence": round(top, 2),
            "citations": [link(c.video_id, c.start) for c, _ in chunks], "sources": sources}


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
