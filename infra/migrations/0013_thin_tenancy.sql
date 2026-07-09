-- Migration 0013: Thin tenancy foundation (F0).
-- Creates the tenants table, seeds Perkins as tenant 1, and adds tenant_id
-- (NOT NULL DEFAULT 1, FK tenants.id) to all 16 tenant-scoped tables.
-- Idempotent: CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.
-- PROD APPLY: requires Jon's explicit permission + fresh ADC (gcloud auth
-- application-default login). Run: .venv/bin/python scripts/apply_migrations_connector.py

-- ── 1. tenants table ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tenants (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR NOT NULL,
    slug       VARCHAR NOT NULL,
    status     VARCHAR NOT NULL DEFAULT 'active',
    settings   JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tenants_slug UNIQUE (slug)
);

-- Seed Perkins = tenant 1. Mirrored by the SQLite/dev-side after_create listener
-- (_seed_perkins_tenant in app/models.py) — keep both in sync.
INSERT INTO tenants (id, name, slug, status, settings)
VALUES (1, 'Perkins Roofing', 'perkins', 'active', '{}')
ON CONFLICT (id) DO NOTHING;

-- GREATEST guard: this file is re-run by the migration runner on every batch;
-- a bare setval(...,1) would rewind the sequence once tenant 2+ exists and the
-- next un-id'd INSERT would collide with the Perkins PK.
SELECT setval('tenants_id_seq', GREATEST((SELECT MAX(id) FROM tenants), 1), true);

-- ── 2. tenant_id column on all 16 tenant-scoped tables ──────────────────────
ALTER TABLE videos           ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE ingestion_runs   ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE segments         ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE words             ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE content_graph    ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE chunks            ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE email_templates  ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE clusters          ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE articles          ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE scheduled_content ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE mini_series       ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE social_posts      ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE aggregated_topics ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE comment_drafts    ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE user_settings     ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);
ALTER TABLE faq_entries        ADD COLUMN IF NOT EXISTS tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id);

-- ── 3. Composite indexes (hot query patterns filter on tenant_id first) ──────
-- Pattern: tenant_id + the existing lookup key on the table's hottest queries.

-- videos: most queries are "all videos for this tenant" or "video by id for this tenant"
CREATE INDEX IF NOT EXISTS ix_videos_tenant_id
    ON videos (tenant_id);

-- ingestion_runs: hot query is (video_id, stage) — tenant added for isolation
CREATE INDEX IF NOT EXISTS ix_ingestion_runs_tenant_video_stage
    ON ingestion_runs (tenant_id, video_id, stage);

-- segments / words: fetched by video_id, so tenant_id + video_id composite
CREATE INDEX IF NOT EXISTS ix_segments_tenant_video
    ON segments (tenant_id, video_id);
CREATE INDEX IF NOT EXISTS ix_words_tenant_video
    ON words (tenant_id, video_id);

-- content_graph: fetched by video_id; kind is a secondary filter
CREATE INDEX IF NOT EXISTS ix_content_graph_tenant_video
    ON content_graph (tenant_id, video_id);

-- chunks: vector search is HNSW (separate); tenant_id + video_id for join queries
CREATE INDEX IF NOT EXISTS ix_chunks_tenant_video
    ON chunks (tenant_id, video_id);

-- articles: most queries filter on status + tenant
CREATE INDEX IF NOT EXISTS ix_articles_tenant_status
    ON articles (tenant_id, status);

-- scheduled_content: queries filter on status (scheduled/published) + tenant
CREATE INDEX IF NOT EXISTS ix_scheduled_content_tenant_status
    ON scheduled_content (tenant_id, status);

-- faq_entries: fetched by video_id + status
CREATE INDEX IF NOT EXISTS ix_faq_entries_tenant_video
    ON faq_entries (tenant_id, video_id);

-- comment_drafts: fetched by status (pending/drafted) per tenant
CREATE INDEX IF NOT EXISTS ix_comment_drafts_tenant_status
    ON comment_drafts (tenant_id, status);

-- clusters: small table; tenant_id alone is sufficient
CREATE INDEX IF NOT EXISTS ix_clusters_tenant_id
    ON clusters (tenant_id);

-- social_posts: looked up by series_id + tenant
CREATE INDEX IF NOT EXISTS ix_social_posts_tenant_series
    ON social_posts (tenant_id, series_id);

-- mini_series: looked up by video_id + approved
CREATE INDEX IF NOT EXISTS ix_mini_series_tenant_video
    ON mini_series (tenant_id, video_id);

-- aggregated_topics / email_templates / user_settings: tenant_id index only (low query rate)
CREATE INDEX IF NOT EXISTS ix_aggregated_topics_tenant_id ON aggregated_topics (tenant_id);
CREATE INDEX IF NOT EXISTS ix_email_templates_tenant_id   ON email_templates (tenant_id);
CREATE INDEX IF NOT EXISTS ix_user_settings_tenant_id     ON user_settings (tenant_id);

-- ── Down path (safe — purely additive migration, no data lost) ───────────────
-- ALTER TABLE videos            DROP COLUMN IF EXISTS tenant_id;
-- ALTER TABLE ingestion_runs    DROP COLUMN IF EXISTS tenant_id;
-- ALTER TABLE segments          DROP COLUMN IF EXISTS tenant_id;
-- ALTER TABLE words              DROP COLUMN IF EXISTS tenant_id;
-- ALTER TABLE content_graph     DROP COLUMN IF EXISTS tenant_id;
-- ALTER TABLE chunks             DROP COLUMN IF EXISTS tenant_id;
-- ALTER TABLE email_templates   DROP COLUMN IF EXISTS tenant_id;
-- ALTER TABLE clusters           DROP COLUMN IF EXISTS tenant_id;
-- ALTER TABLE articles           DROP COLUMN IF EXISTS tenant_id;
-- ALTER TABLE scheduled_content  DROP COLUMN IF EXISTS tenant_id;
-- ALTER TABLE mini_series        DROP COLUMN IF EXISTS tenant_id;
-- ALTER TABLE social_posts       DROP COLUMN IF EXISTS tenant_id;
-- ALTER TABLE aggregated_topics  DROP COLUMN IF EXISTS tenant_id;
-- ALTER TABLE comment_drafts     DROP COLUMN IF EXISTS tenant_id;
-- ALTER TABLE user_settings      DROP COLUMN IF EXISTS tenant_id;
-- ALTER TABLE faq_entries         DROP COLUMN IF EXISTS tenant_id;
-- DROP TABLE IF EXISTS tenants;
