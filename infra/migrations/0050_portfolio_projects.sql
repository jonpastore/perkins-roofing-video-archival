-- 0050_portfolio_projects.sql
-- Portfolio projects become DATA. Until now the project list was a hardcoded Python list
-- (scripts/portfolio_prefill.CANDIDATES), which meant the admin UI could curate media for a
-- project but could not add one, fix a wrong city, or supply the CompanyCam URL that two of the
-- thirteen candidates are missing — the work had to go through a code change and a deploy.
--
-- Curation (media selection + client permissions, migration 0048) stays in its own table keyed
-- by slug: it is a different lifecycle (an editor's choices) from the project record itself
-- (what the job WAS), and keeping them apart means re-seeding a project cannot clear the
-- permissions someone recorded.
--
-- search_terms is JSONB because it is a list used only for the Knowify scope lookup, and
-- notes/dates are free text the way the source doc has them ("20 Feb 2024") rather than DATEs —
-- they are display strings, and inventing precision we do not have would be worse.

CREATE TABLE IF NOT EXISTS portfolio_projects (
    id                    SERIAL PRIMARY KEY,
    tenant_id             INTEGER NOT NULL REFERENCES tenants(id) DEFAULT 1,
    slug                  VARCHAR(200) NOT NULL,
    name                  VARCHAR(300) NOT NULL,
    city                  VARCHAR(120),
    section               VARCHAR(40)  NOT NULL DEFAULT 'commercial',
    companycam_url        VARCHAR(500),
    youtube_url           VARCHAR(500),
    date_start            VARCHAR(60),
    date_end              VARCHAR(60),
    notes                 TEXT,
    search_terms          JSONB NOT NULL DEFAULT '[]',
    -- Soft delete: a project that has been published to WordPress must not vanish from the
    -- admin list just because someone archived it, or nobody can find the page to unpublish.
    archived_at           TIMESTAMP,
    created_at            TIMESTAMP NOT NULL DEFAULT now(),
    updated_at            TIMESTAMP NOT NULL DEFAULT now(),
    updated_by            VARCHAR(320),
    CONSTRAINT uq_portfolio_projects_tenant_slug UNIQUE (tenant_id, slug)
);

CREATE INDEX IF NOT EXISTS ix_portfolio_projects_tenant ON portfolio_projects (tenant_id);
CREATE INDEX IF NOT EXISTS ix_portfolio_projects_live
    ON portfolio_projects (tenant_id, name) WHERE archived_at IS NULL;

ALTER TABLE portfolio_projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_projects FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS portfolio_projects_tenant_isolation ON portfolio_projects;
CREATE POLICY portfolio_projects_tenant_isolation ON portfolio_projects
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int);
