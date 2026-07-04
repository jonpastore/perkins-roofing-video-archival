-- Wave 1 prod migration: move chunks.embedding to gemini-embedding-001's 3072 dimensions.
-- Run after `CREATE EXTENSION IF NOT EXISTS vector;` on the Cloud SQL Postgres instance.
-- The dev SQLite path stores embeddings as JSON and needs no migration.

ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(3072)
    USING embedding::text::vector(3072);

DROP INDEX IF EXISTS chunks_embedding_hnsw;
CREATE INDEX chunks_embedding_hnsw ON chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
