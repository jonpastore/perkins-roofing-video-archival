-- 0037_articles_updated_at.sql
-- articles.updated_at — when the row was last written, on EVERY write path.
--
-- articles had only generated_at, defaulted at insert and never touched again, so all 31 rows
-- read "2026-07-09" no matter how many times they had been rewritten. There was no way to ask
-- "which pipeline produced this article", which mattered the day the pipeline changed and the
-- only record lived in a scratch log.
--
-- Stamping generated_at on regen (the first attempt) was wrong twice over: it destroys the
-- creation date the column is named for, and it only covers the one job that remembers to do
-- it — seven modules write articles.content_md. The model uses onupdate=_utcnow, which
-- SQLAlchemy applies to every UPDATE from every path, matching the convention already on six
-- other tables here. generated_at goes back to meaning first generation.
--
-- Backfill: generated_at, the best evidence we have of when each row was last known-good.

ALTER TABLE articles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

UPDATE articles SET updated_at = generated_at WHERE updated_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_articles_tenant_updated
    ON articles (tenant_id, updated_at DESC);
