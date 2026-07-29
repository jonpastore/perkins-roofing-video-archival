-- 0047_companycam_videos.sql
-- CompanyCam VIDEO mirror. Videos are a separate v2 resource from photos, not photos with a
-- different type: the payload carries playback_url + thumbnail_urls where a photo carries
-- uris[], and its timestamps are unix epoch ints (adapters/companycam.normalize_video).
-- Measured 2026-07-29 over the live account: 234 videos across 20 of 25 sampled projects, so
-- this is real content, not an edge case. Idempotent; RLS follows the 0043 convention exactly.

CREATE TABLE IF NOT EXISTS companycam_videos (
    id                   SERIAL PRIMARY KEY,
    tenant_id            INTEGER NOT NULL REFERENCES tenants(id) DEFAULT 1,
    companycam_video_id  VARCHAR(100) NOT NULL,
    project_id           VARCHAR(100),
    url                  VARCHAR(1000),
    thumbnail_url        VARCHAR(1000),
    captured_at          TIMESTAMP,
    lat                  DOUBLE PRECISION,
    lon                  DOUBLE PRECISION,
    status               VARCHAR(50),
    -- CompanyCam lets a crew mark media internal-only. Internal media must never reach a
    -- proposal or a public project page, so the flag is mirrored as a first-class column
    -- (NOT NULL, defaults to the safe value) rather than left buried in raw for a publisher
    -- to forget. Every consumer filters on internal = false.
    internal             BOOLEAN NOT NULL DEFAULT TRUE,
    raw                  JSONB NOT NULL DEFAULT '{}',
    content_hash         VARCHAR(64) NOT NULL,
    created_at           TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_companycam_videos_tenant_video UNIQUE (tenant_id, companycam_video_id)
);

CREATE INDEX IF NOT EXISTS ix_companycam_videos_tenant ON companycam_videos (tenant_id);
CREATE INDEX IF NOT EXISTS ix_companycam_videos_companycam_video_id
    ON companycam_videos (companycam_video_id);
-- Gallery lookups are always "the publishable media for this project".
CREATE INDEX IF NOT EXISTS ix_companycam_videos_project
    ON companycam_videos (tenant_id, project_id) WHERE internal = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS uq_companycam_videos_tenant_video_partial
    ON companycam_videos (tenant_id, companycam_video_id) WHERE companycam_video_id IS NOT NULL;

ALTER TABLE companycam_videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE companycam_videos FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS companycam_videos_tenant_isolation ON companycam_videos;
CREATE POLICY companycam_videos_tenant_isolation ON companycam_videos
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int);
