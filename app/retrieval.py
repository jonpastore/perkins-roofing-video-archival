"""Hybrid retrieval as a first-class design (council requirement): vector + lexical +
Content-Graph signal, merged. The Content Graph is the edge — not a vector-DB app.
Query/fetch I/O lives here; the pure scoring is core.retrieval.rank."""
from core.retrieval import link, rank

from .models import Chunk, GraphNode, SessionLocal
from .store import vector_search


def hybrid_search(query, k=8, db=None):
    # db: caller-passed (RLS-stamped) session, threaded through vector_search too.
    # Used but never closed here; None opens an own SessionLocal (compat).
    vec = vector_search(query, k=k * 2, db=db)
    s = db or SessionLocal()
    try:
        kw = "%" + query.lower() + "%"
        lex = s.query(Chunk).filter(Chunk.text.ilike(kw)).limit(k).all()
        gnodes = s.query(GraphNode).filter(
            (GraphNode.label.ilike(kw)) | (GraphNode.detail.ilike(kw))).limit(k).all()
    finally:
        if db is None:
            s.close()   # never leak the pooled connection on a query error (every /ask hits this)
    gvids = {g.video_id for g in gnodes}
    return {"chunks": rank(vec, lex, gvids, k), "graph": gnodes}


def search(query, k=8, db=None):
    r = hybrid_search(query, k, db=db)
    return [{"score": round(sc, 2), "link": link(c.video_id, c.start),
             "video_id": c.video_id, "text": c.text[:180].strip()} for c, sc in r["chunks"]]
