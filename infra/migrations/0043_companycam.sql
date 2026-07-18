-- 0043_companycam.sql
-- CompanyCam photo mirror (ahead-of-account scaffold): PAT not issued yet, so this
-- table sits empty until jobs/companycam_sync.py is enabled. Idempotent: safe to
-- re-run. RLS follows the exact 0032/0041 convention.

CREATE TABLE IF NOT EXISTS companycam_photos (
    id                   SERIAL PRIMARY KEY,
    tenant_id            INTEGER NOT NULL REFERENCES tenants(id) DEFAULT 1,
    companycam_photo_id  VARCHAR(100) NOT NULL,
    project_id           VARCHAR(100),
    url                  VARCHAR(1000),
    captured_at          TIMESTAMP,
    lat                  DOUBLE PRECISION,
    lon                  DOUBLE PRECISION,
    tags                 JSONB NOT NULL DEFAULT '[]',
    raw                  JSONB NOT NULL DEFAULT '{}',
    content_hash         VARCHAR(64) NOT NULL,
    created_at           TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_companycam_photos_tenant_photo UNIQUE (tenant_id, companycam_photo_id)
);

CREATE INDEX IF NOT EXISTS ix_companycam_photos_tenant ON companycam_photos (tenant_id);
CREATE INDEX IF NOT EXISTS ix_companycam_photos_companycam_photo_id ON companycam_photos (companycam_photo_id);

-- Partial-unique index — the ON CONFLICT target for the hash-gated upsert
-- (core/companycam/mirror.py). The table-level UNIQUE constraint above already
-- covers this shape; this partial index matches the WHERE-guarded convention used
-- for crosswalk columns elsewhere (0032) in case companycam_photo_id ever becomes
-- nullable for a different ingestion path.
CREATE UNIQUE INDEX IF NOT EXISTS uq_companycam_photos_tenant_photo_partial
    ON companycam_photos (tenant_id, companycam_photo_id) WHERE companycam_photo_id IS NOT NULL;

-- RLS: ENABLE + FORCE + the standard NULLIF 2-arg tenant_isolation policy.
ALTER TABLE companycam_photos ENABLE ROW LEVEL SECURITY;
ALTER TABLE companycam_photos FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS companycam_photos_tenant_isolation ON companycam_photos;
CREATE POLICY companycam_photos_tenant_isolation ON companycam_photos
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int);
