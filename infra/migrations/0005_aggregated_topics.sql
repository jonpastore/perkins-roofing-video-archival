-- Migration 0005: aggregated_topics — precomputed semantic topic clusters
-- Idempotent; safe to re-run on existing schemas.
-- Populated offline by jobs/aggregate_topics.py (never by the API layer).

CREATE TABLE IF NOT EXISTS aggregated_topics (
    id              SERIAL PRIMARY KEY,
    canonical_label VARCHAR NOT NULL,
    num_videos      INTEGER NOT NULL DEFAULT 0,
    total_seconds   FLOAT NOT NULL DEFAULT 0.0,
    video_ids       JSONB NOT NULL DEFAULT '[]',
    node_ids        JSONB NOT NULL DEFAULT '[]',
    version         VARCHAR NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_aggregated_topics_canonical_label
    ON aggregated_topics (canonical_label);
