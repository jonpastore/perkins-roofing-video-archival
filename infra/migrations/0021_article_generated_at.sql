-- Migration 0021: add generated_at to articles table
--
-- Records when an article was generated so the topic-freshness feature can
-- detect whether new source videos have appeared since the articles were
-- created.
--
-- Backfill via a DDL column DEFAULT rather than a separate UPDATE: `articles` is
-- RLS-FORCED (0018) and the migration runner connects as the NOBYPASSRLS `app`
-- role with no app.tenant_id set, so an UPDATE on the table would raise
-- ("unrecognized configuration parameter app.tenant_id"). ADD COLUMN ... DEFAULT
-- is DDL — it populates all existing rows (every tenant) with the default at
-- migration time and is NOT subject to row-level security. New rows get the value
-- from the app model (Article.generated_at default=_utcnow); the DB default is a
-- backstop. Freshness therefore begins tracking from this migration's timestamp.
--
-- Idempotent: IF NOT EXISTS makes repeated execution safe.

ALTER TABLE articles ADD COLUMN IF NOT EXISTS generated_at TIMESTAMP DEFAULT now();
