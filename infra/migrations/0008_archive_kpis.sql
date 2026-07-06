-- Migration 0008: KPI + pull-tracking columns for the videos table.
-- Adds views/likes/comment_count/last_comment_at/kpis_polled_at/last_pulled_at/clips_generated_at.
-- Idempotent (ADD COLUMN IF NOT EXISTS). Safe to re-run.
ALTER TABLE videos ADD COLUMN IF NOT EXISTS views            BIGINT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS likes            BIGINT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS comment_count    BIGINT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS last_comment_at  TIMESTAMP;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS kpis_polled_at   TIMESTAMP;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS last_pulled_at   TIMESTAMP;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS clips_generated_at TIMESTAMP;
