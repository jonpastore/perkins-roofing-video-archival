-- Hybrid pillar/cluster publish pipeline (Track D).
-- Adds the `clusters` table and three publish-pipeline columns on `articles`
-- (cluster_id, priority, scheduled_at). `articles.role` and `articles.status` (with the
-- 'ready'/'scheduled' values the drip job filters on) already exist from an earlier wave migration.
-- All statements are idempotent: CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS clusters (
    id            SERIAL PRIMARY KEY,
    pillar_topic  VARCHAR NOT NULL,
    status        VARCHAR NOT NULL DEFAULT 'pending',   -- pending | active | complete
    position      INTEGER NOT NULL DEFAULT 0            -- activation order (ascending); default for forward-safe re-add
);

ALTER TABLE articles ADD COLUMN IF NOT EXISTS cluster_id   INTEGER REFERENCES clusters(id);
ALTER TABLE articles ADD COLUMN IF NOT EXISTS priority     INTEGER;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMP;
