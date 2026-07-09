-- Migration 0021: add generated_at to articles table
--
-- Records when an article was generated so the topic-freshness feature can
-- detect whether new source videos have appeared since the articles were
-- created.  Backfills existing rows from scheduled_at or publish_at (whichever
-- is non-null), falling back to NOW() so the column is never NULL after this
-- migration runs.
--
-- Idempotent: IF NOT EXISTS guards mean repeated execution is safe.

ALTER TABLE articles ADD COLUMN IF NOT EXISTS generated_at TIMESTAMP;

UPDATE articles
   SET generated_at = COALESCE(scheduled_at, publish_at, NOW())
 WHERE generated_at IS NULL;
