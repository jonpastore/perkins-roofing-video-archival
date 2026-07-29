-- 0048_portfolio_curation.sql
-- Curated media selection + client permissions for a portfolio project.
--
-- Two things previously had nowhere to live:
--   * WHICH CompanyCam photos/videos belong on a project page, in what order, with what alt
--     text. The nine live project pages each carry four images sharing ONE alt string, which
--     is exactly what happens when nobody can record per-image alt text.
--   * The three client permissions (name the property / use photos / use video).
--     api/routes/portfolio.py hardcoded all three to False with a comment saying a follow-on
--     ticket should add a store — publish was blocked for everything, permanently.
--
-- Keyed by the candidate SLUG (scripts/portfolio_prefill.CANDIDATES is the project list; there
-- is no projects table and WordPress is the publish-status source of truth), so this table
-- carries only what a human decides, never a copy of the media itself.
--
-- selections is a JSONB array, ordered: [{"kind":"photo"|"video","id":"...","alt":"..."}, ...].
-- JSON rather than a row per item because the ORDER is the payload and the whole selection is
-- always written at once by one PUT — a join table would buy nothing but a sort column.
-- Idempotent; RLS follows the 0043/0047 convention.

CREATE TABLE IF NOT EXISTS portfolio_curation (
    id                      SERIAL PRIMARY KEY,
    tenant_id               INTEGER NOT NULL REFERENCES tenants(id) DEFAULT 1,
    slug                    VARCHAR(200) NOT NULL,
    companycam_project_id   VARCHAR(100),
    youtube_url             VARCHAR(500),
    -- Default FALSE: absent permission means NOT cleared. Publishing is gated on all three.
    permission_property     BOOLEAN NOT NULL DEFAULT FALSE,
    permission_photos       BOOLEAN NOT NULL DEFAULT FALSE,
    permission_video        BOOLEAN NOT NULL DEFAULT FALSE,
    selections              JSONB NOT NULL DEFAULT '[]',
    updated_by              VARCHAR(320),
    updated_at              TIMESTAMP NOT NULL DEFAULT now(),
    created_at              TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_portfolio_curation_tenant_slug UNIQUE (tenant_id, slug)
);

CREATE INDEX IF NOT EXISTS ix_portfolio_curation_tenant ON portfolio_curation (tenant_id);

ALTER TABLE portfolio_curation ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_curation FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS portfolio_curation_tenant_isolation ON portfolio_curation;
CREATE POLICY portfolio_curation_tenant_isolation ON portfolio_curation
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int);
