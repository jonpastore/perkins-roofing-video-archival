-- Search performance: the hybrid-retrieval lexical legs use leading-wildcard `ILIKE '%q%'`
-- on chunks.text and content_graph.label/detail (app/retrieval.py) — a btree can't serve a
-- leading wildcard, so without these every /search and /ask does full sequential scans.
-- pg_trgm GIN indexes DO accelerate substring ILIKE. Also index content_graph.kind, which the
-- topics/suggestions endpoints filter on unindexed. All idempotent.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS ix_chunks_text_trgm   ON chunks        USING gin (text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_graph_label_trgm   ON content_graph USING gin (label gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_graph_detail_trgm  ON content_graph USING gin (detail gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_graph_kind         ON content_graph (kind);
