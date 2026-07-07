-- Article.focus_keyword (Rank Math SEO focus keyword) is declared in the ORM (app/models.py)
-- and written by POST/PUT /articles and jobs/regen_articles_seo, but 0004_wave_tables.sql's
-- CREATE TABLE articles omits it. create_all() only adds missing TABLES, never missing
-- COLUMNS, so any DB where `articles` already existed permanently lacked this column and the
-- SEO focus-keyword feature errored on Postgres. Idempotent add.
ALTER TABLE articles ADD COLUMN IF NOT EXISTS focus_keyword VARCHAR;
