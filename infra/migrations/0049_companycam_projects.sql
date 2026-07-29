-- 0049_companycam_projects.sql
-- Project-level mirror, which exists to make the sync INCREMENTAL.
--
-- The account holds 3,684 projects (measured 2026-07-29, once the pagination truncation in
-- adapters/companycam._get_all was fixed — it had been mirroring the first 50). Fetching
-- photos AND videos for every project on every run is ~7,400 paginated requests and takes
-- hours; almost none of it changes between nights.
--
-- CompanyCam has no server-side modified_since filter (tried: modified_since 500s,
-- updated_after/start_date are ignored), but every project carries updated_at. So we store it
-- and re-fetch a project's media only when that timestamp moves. A nightly run with nothing
-- new costs one paginated project listing.
--
-- name/address are mirrored too because they are how a project is matched to a portfolio
-- candidate — CompanyCam projects are keyed by customer/property name, unlike the YouTube
-- channel, which has no join key to a property at all.

CREATE TABLE IF NOT EXISTS companycam_projects (
    id                     SERIAL PRIMARY KEY,
    tenant_id              INTEGER NOT NULL REFERENCES tenants(id) DEFAULT 1,
    companycam_project_id  VARCHAR(100) NOT NULL,
    name                   VARCHAR(500),
    address                JSONB NOT NULL DEFAULT '{}',
    status                 VARCHAR(50),
    archived               BOOLEAN NOT NULL DEFAULT FALSE,
    photo_count            INTEGER,
    -- CompanyCam's own updated_at (unix epoch -> timestamp). The incremental key.
    remote_updated_at      TIMESTAMP,
    -- When we last pulled this project's media. NULL = never, so it always fetches once.
    media_synced_at        TIMESTAMP,
    created_at             TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_companycam_projects_tenant_project UNIQUE (tenant_id, companycam_project_id)
);

CREATE INDEX IF NOT EXISTS ix_companycam_projects_tenant ON companycam_projects (tenant_id);
CREATE INDEX IF NOT EXISTS ix_companycam_projects_name ON companycam_projects (tenant_id, name);

ALTER TABLE companycam_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE companycam_projects FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS companycam_projects_tenant_isolation ON companycam_projects;
CREATE POLICY companycam_projects_tenant_isolation ON companycam_projects
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int);
