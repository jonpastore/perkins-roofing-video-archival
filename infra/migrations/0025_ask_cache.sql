-- Migration 0025: ask_cache table + RLS + pgvector embedding index + pg_trgm on chunks
-- Additive, idempotent (IF NOT EXISTS throughout).

-- ── pg_trgm (fixes the slow ILIKE lexical leg in hybrid_search) ─────────────
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS ix_chunks_text_trgm ON chunks USING gin (text gin_trgm_ops);

-- ── ask_cache table ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ask_cache (
    id               SERIAL        PRIMARY KEY,
    question         TEXT          NOT NULL,
    question_norm    TEXT          NOT NULL,
    embedding        vector(3072),
    answer_json      JSONB         NOT NULL DEFAULT '{}',
    pipeline_version VARCHAR(64)   NOT NULL DEFAULT '',
    hit_count        INTEGER       NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    tenant_id        INTEGER       NOT NULL REFERENCES tenants(id) DEFAULT 1
);

-- Composite index for tenant-scoped norm-match dedup (exact-match fallback + dedup check)
CREATE INDEX IF NOT EXISTS ix_ask_cache_tenant_norm
    ON ask_cache (tenant_id, question_norm);

-- HNSW index on halfvec cast for cosine ANN (same pattern as chunks — vector(3072) exceeds
-- the 2000-dim native HNSW cap; halfvec(3072) is HNSW-eligible up to 4000 dims).
CREATE INDEX IF NOT EXISTS ix_ask_cache_embedding_hnsw
    ON ask_cache
    USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ── RLS (same NULLIF-GUC pattern as 0023/0024) ──────────────────────────────
ALTER TABLE ask_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE ask_cache FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON ask_cache;
CREATE POLICY tenant_isolation ON ask_cache
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int);
