"""Grounded 'Ask Tim' answer with ABSTENTION + citations (council requirement). Below the
confidence threshold it refuses rather than hallucinating — protects the brand on a public widget."""
from .config import settings
from .models import SessionLocal, GraphNode
from .retrieval import hybrid_search, link
from .llm import chat

def ask(query, k=8):
    r = hybrid_search(query, k)
    chunks = r["chunks"]
    top = max((sc for _, sc in chunks), default=0.0)
    if not chunks or top < settings.ABSTAIN_THRESHOLD:
        return {"answer": "I couldn't find that in Tim's videos.", "abstained": True,
                "confidence": round(top, 2), "citations": []}

    vids = {c.video_id for c, _ in chunks}
    s = SessionLocal()
    gp = s.query(GraphNode).filter(
        GraphNode.video_id.in_(vids),
        GraphNode.kind.in_(("objections", "claims", "ctas"))).all()
    s.close()

    key = "\n".join(f"(key point, source {link(g.video_id, g.start)}) {g.label or g.detail}" for g in gp[:20])
    ctx = "\n\n".join(f"(source {link(c.video_id, c.start)}) {c.text}" for c, _ in chunks)
    prompt = ("Answer the homeowner's question using ONLY the material below. Cite the source link "
              "after each point. Prefer KEY POINTS (verified facts from the video). If the material "
              "does not cover it, say you couldn't find it in Tim's videos.\n\n"
              f"QUESTION: {query}\n\nKEY POINTS:\n{key}\n\nTRANSCRIPT EXCERPTS:\n{ctx}")
    return {"answer": chat(prompt), "abstained": False, "confidence": round(top, 2),
            "citations": [link(c.video_id, c.start) for c, _ in chunks]}
