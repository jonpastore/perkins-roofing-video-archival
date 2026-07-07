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
        # PROD: pgvector cosine ANN. embedding is vector(3072); HNSW caps `vector` at
        # 2000 dims, so we index+query the halfvec(3072) cast (HNSW supports 4000 dims).
        from pgvector.psycopg import register_vector
        s = SessionLocal()
        try:
            # .driver_connection is the raw psycopg3 conn (unwrap SQLAlchemy's pool proxy)
            register_vector(s.connection().connection.driver_connection)
            rows = s.execute(text(
                'SELECT id, video_id, text, start, "end", '
                '1 - (embedding::halfvec(3072) <=> CAST(:q AS halfvec(3072))) AS score '
                'FROM chunks ORDER BY embedding::halfvec(3072) <=> CAST(:q AS halfvec(3072)) LIMIT :k'),
                {"q": np.array(q, dtype=np.float32), "k": k}).fetchall()
        finally:
            s.close()   # never leak the pooled connection on a query error (hot path)
        return [(_Row(r), float(r.score)) for r in rows]
    # DEV: numpy cosine
    s = SessionLocal()
    try:
        rows = s.query(Chunk).all()
    finally:
        s.close()
    if not rows:
        return []
    M = np.array([r.embedding for r in rows], dtype=np.float32)
    qv = np.array(q, dtype=np.float32)
    sims = M @ qv / (np.linalg.norm(M, axis=1) * np.linalg.norm(qv) + 1e-9)
    return [(rows[i], float(sims[i])) for i in sims.argsort()[::-1][:k]]
