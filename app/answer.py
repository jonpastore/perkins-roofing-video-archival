"""Grounded 'Ask Tim' answer with ABSTENTION + citations (council requirement). Below the
confidence threshold it refuses rather than hallucinating — protects the brand on a public widget.
Abstention gate + prompt construction are pure (core.answer); the chat() call is I/O."""
from core.answer import build_answer_prompt, should_abstain
from core.retrieval import link

from .config import settings
from .llm import chat
from .models import GraphNode, SessionLocal
from .retrieval import hybrid_search


def ask(query, k=8):
    r = hybrid_search(query, k)
    chunks = r["chunks"]
    top = max((sc for _, sc in chunks), default=0.0)
    if not chunks or should_abstain(top, settings.ABSTAIN_THRESHOLD):
        return {"answer": "I couldn't find that in Tim's videos.", "abstained": True,
                "confidence": round(top, 2), "citations": []}

    vids = {c.video_id for c, _ in chunks}
    s = SessionLocal()
    gp = s.query(GraphNode).filter(
        GraphNode.video_id.in_(vids),
        GraphNode.kind.in_(("objections", "claims", "ctas"))).all()
    s.close()

    key_points = [(link(g.video_id, g.start), g.label or g.detail) for g in gp[:20]]
    contexts = [(link(c.video_id, c.start), c.text) for c, _ in chunks]
    prompt = build_answer_prompt(query, contexts, key_points)
    return {"answer": chat(prompt), "abstained": False, "confidence": round(top, 2),
            "citations": [link(c.video_id, c.start) for c, _ in chunks]}
