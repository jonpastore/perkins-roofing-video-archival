"""Hybrid retrieval as a first-class design (council requirement): vector + lexical +
Content-Graph signal, merged. The Content Graph is the edge — not a vector-DB app.
Query/fetch I/O lives here; the pure scoring is core.retrieval.rank."""
from core.retrieval import link, rank

from .models import Chunk, GraphNode, SessionLocal
from .store import vector_search


def hybrid_search(query, k=8):
    vec = vector_search(query, k=k * 2)
    s = SessionLocal()
    kw = "%" + query.lower() + "%"
    lex = s.query(Chunk).filter(Chunk.text.ilike(kw)).limit(k).all()
    gnodes = s.query(GraphNode).filter(
        (GraphNode.label.ilike(kw)) | (GraphNode.detail.ilike(kw))).limit(k).all()
    s.close()
    gvids = {g.video_id for g in gnodes}
    return {"chunks": rank(vec, lex, gvids, k), "graph": gnodes}


def search(query, k=8):
    r = hybrid_search(query, k)
    return [{"score": round(sc, 2), "link": link(c.video_id, c.start),
             "video_id": c.video_id, "text": c.text[:180].strip()} for c, sc in r["chunks"]]
