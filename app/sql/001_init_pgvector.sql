-- Production migration (Cloud SQL Postgres). Apply via Alembic in prod; shown here as DDL.
-- Converts the dev JSON embedding to a native pgvector column + ANN index.
CREATE EXTENSION IF NOT EXISTS vector;

-- chunks.embedding: dev stores JSON; prod uses vector(768) (nomic-embed-text / Vertex dim).
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedding_vec vector(768);
-- (one-time backfill: UPDATE chunks SET embedding_vec = embedding::text::vector;)

-- HNSW index for fast ANN cosine search (matches store.py: ORDER BY embedding <=> :q)
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
  ON chunks USING hnsw (embedding_vec vector_cosine_ops);

-- Helpful secondary indexes
CREATE INDEX IF NOT EXISTS ix_segments_video ON segments(video_id);
CREATE INDEX IF NOT EXISTS ix_graph_video ON content_graph(video_id);
CREATE INDEX IF NOT EXISTS ix_runs_video_stage ON ingestion_runs(video_id, stage);
