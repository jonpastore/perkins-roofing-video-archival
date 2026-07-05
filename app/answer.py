"""Grounded 'Ask Tim' answer with ABSTENTION + citations (council requirement). Below the
confidence threshold it refuses rather than hallucinating — protects the brand on a public widget.
Abstention gate + prompt construction are pure (core.answer); the chat() call is I/O."""
from core.answer import build_answer_prompt, should_abstain
from core.retrieval import link

from .config import settings
from .llm import chat
from .models import GraphNode, SessionLocal, Video
from .retrieval import hybrid_search


def ask(query, k=8):
    r = hybrid_search(query, k)
    chunks = r["chunks"]
    top = max((sc for _, sc in chunks), default=0.0)
    if not chunks or should_abstain(top, settings.ABSTAIN_THRESHOLD):
        return {"answer": "I couldn't find that in Tim's videos.", "abstained": True,
                "confidence": round(top, 2), "citations": [], "sources": []}

    vids = {c.video_id for c, _ in chunks}
    s = SessionLocal()
    gp = s.query(GraphNode).filter(
        GraphNode.video_id.in_(vids),
        GraphNode.kind.in_(("objections", "claims", "ctas"))).all()
    titles = {v.id: v.title for v in s.query(Video.id, Video.title).filter(Video.id.in_(vids))}
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
