-- Migration 0004: Wave-4 tables documentation
-- The following tables are created via SQLAlchemy Base.metadata.create_all()
-- in app/models.py (init_db). This migration documents their schemas for
-- reference and provides CREATE TABLE IF NOT EXISTS statements for manual
-- bootstrapping on instances that cannot use create_all.
--
-- Tables created by create_all (no-op if they already exist):
--   social_posts, scheduled_content, mini_series, articles, email_templates

CREATE TABLE IF NOT EXISTS social_posts (
    id          SERIAL PRIMARY KEY,
    series_id   INTEGER NOT NULL,
    part        INTEGER NOT NULL,
    platform    VARCHAR NOT NULL,
    gcs_url     VARCHAR,
    external_id VARCHAR,
    status      VARCHAR DEFAULT 'pending',
    CONSTRAINT uq_social_series_part_platform UNIQUE (series_id, part, platform)
);

CREATE TABLE IF NOT EXISTS scheduled_content (
    id         SERIAL PRIMARY KEY,
    kind       VARCHAR NOT NULL,
    ref_id     VARCHAR,
    publish_at TIMESTAMP,
    status     VARCHAR DEFAULT 'scheduled',
    target     VARCHAR
);

CREATE TABLE IF NOT EXISTS mini_series (
    id         SERIAL PRIMARY KEY,
    video_id   VARCHAR,
    title      VARCHAR,
    parts_json JSONB,
    approved   INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS articles (
    slug         VARCHAR PRIMARY KEY,
    title        VARCHAR,
    meta         TEXT,
    content_md   TEXT,
    faq_json     JSONB,
    jsonld_json  JSONB,
    role         VARCHAR,
    pillar_slug  VARCHAR,
    wp_post_id   INTEGER,
    status       VARCHAR,
    publish_at   TIMESTAMP
);

CREATE TABLE IF NOT EXISTS email_templates (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR,
    subject    VARCHAR,
    body       TEXT,
    created_by VARCHAR
);
