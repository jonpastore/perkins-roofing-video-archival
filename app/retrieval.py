"""Hybrid retrieval as a first-class design (council requirement): vector + lexical +
Content-Graph signal, merged. The Content Graph is the edge — not a vector-DB app."""
from .models import SessionLocal, Chunk, GraphNode
from .store import vector_search

def link(vid, start):
    return f"https://youtu.be/{vid}?t={int(start)}"

def hybrid_search(query, k=8):
    vec = vector_search(query, k=k * 2)
    s = SessionLocal()
    kw = "%" + query.lower() + "%"
    lex = s.query(Chunk).filter(Chunk.text.ilike(kw)).limit(k).all()
    gnodes = s.query(GraphNode).filter(
        (GraphNode.label.ilike(kw)) | (GraphNode.detail.ilike(kw))).limit(k).all()
    s.close()

    scored = {}
    for ch, sim in vec:
        scored[ch.id] = [ch, sim]
    for ch in lex:                       # lexical boost (keyword match)
        if ch.id in scored:
            scored[ch.id][1] += 0.15
        else:
            scored[ch.id] = [ch, 0.5]
    gvids = {g.video_id for g in gnodes}
    for entry in scored.values():        # graph boost (video has a matching key point)
        if entry[0].video_id in gvids:
            entry[1] += 0.1

    ranked = sorted(scored.values(), key=lambda x: -x[1])[:k]
    return {"chunks": [(c, sc) for c, sc in ranked], "graph": gnodes}

def search(query, k=8):
    r = hybrid_search(query, k)
    return [{"score": round(sc, 2), "link": link(c.video_id, c.start),
             "video_id": c.video_id, "text": c.text[:180].strip()} for c, sc in r["chunks"]]
