"""Vector store. Dev (sqlite): numpy cosine over JSON embeddings. Prod (postgres):
pgvector ANN with an HNSW index — same interface, selected by DB_URL."""
import numpy as np
from sqlalchemy import text
from .config import settings
from .models import SessionLocal, Chunk
from .llm import embed

def _is_pg():
    return settings.DB_URL.startswith("postgres")

class _Row:
    """Lightweight chunk view for the pgvector path (matches Chunk attrs used downstream)."""
    def __init__(self, r):
        self.id, self.video_id, self.text, self.start, self.end = r.id, r.video_id, r.text, r.start, r.end

def vector_search(query, k=8):
    q = embed([query])[0]
    if _is_pg():
        # PROD: requires `chunks.embedding vector(3072)` + HNSW index + register_vector(conn).
        s = SessionLocal()
        rows = s.execute(text(
            'SELECT id, video_id, text, start, "end", 1 - (embedding <=> :q) AS score '
            'FROM chunks ORDER BY embedding <=> :q LIMIT :k'), {"q": q, "k": k}).fetchall()
        s.close()
        return [(_Row(r), float(r.score)) for r in rows]
    # DEV: numpy cosine
    s = SessionLocal(); rows = s.query(Chunk).all(); s.close()
    if not rows:
        return []
    M = np.array([r.embedding for r in rows], dtype=np.float32)
    qv = np.array(q, dtype=np.float32)
    sims = M @ qv / (np.linalg.norm(M, axis=1) * np.linalg.norm(qv) + 1e-9)
    return [(rows[i], float(sims[i])) for i in sims.argsort()[::-1][:k]]
