-- Migration 0018: RLS + GCIP tenancy hardening (F4)
-- Ownership: this file is co-owned by two parallel agents:
--   RLS CORE section (below)    — written by f4-rls agent
--   GCIP IDENTITY section       — appended by f4-identity agent (DO NOT EDIT that region)
-- PROD APPLY: requires Jon's explicit permission + fresh ADC.
-- Run: .venv/bin/python scripts/apply_migrations_connector.py
--
-- App role change (step 7 below) REQUIRES SUPERUSER. Jon must confirm and apply
-- manually via the Cloud SQL connector as the postgres superuser. It is included
-- here as documentation and is guarded with a comment marker.

-- ═══════════════════════════════════════════════════════════════════════════════
-- RLS CORE SECTION (f4-rls agent)
-- ═══════════════════════════════════════════════════════════════════════════════

-- ── 1. Platform tables (no tenant_id, RLS-exempt) ───────────────────────────
--    tenant_gcip_map, tenant_default_admins, platform_admins, tenant_offboard_log,
--    platform_audit_log: owned by f4-identity agent; created in GCIP IDENTITY
--    section below. Referenced here for documentation only.

-- ── 2. Seed tenant_default_admins from current DEFAULT_ADMINS (after identity
--       section creates the table). See GCIP IDENTITY section.

-- ── 3. RLS policies on all tenant-scoped tables ─────────────────────────────
--
-- Tables receiving RLS (exhaustive as of F4):
--   From F0/0013: videos, ingestion_runs, segments, words, content_graph, chunks,
--                 email_templates, clusters, articles, scheduled_content, mini_series,
--                 social_posts, aggregated_topics, comment_drafts, user_settings, faq_entries
--   From F2/0014: pricing_configs
--   From F2/0015: estimates, measurements
--   From F3/0017: customers, contacts, properties, proposal_templates, proposals,
--                 proposal_events, leads, jobs, catalog_items, tc_versions
--
-- Policy template per table (idempotent: CREATE POLICY guarded by DO block):
--   ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;
--   ALTER TABLE <t> FORCE ROW LEVEL SECURITY;
--   CREATE POLICY tenant_isolation ON <t>
--       USING (tenant_id = current_setting('app.tenant_id')::int)
--       WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
--
-- current_setting('app.tenant_id') raises if unset — intentional. The after_begin
-- event in core/tenant.py guarantees it is set before the first SQL of any
-- tenant-scoped transaction.

-- ── videos ───────────────────────────────────────────────────────────────────
ALTER TABLE videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE videos FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON videos
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── ingestion_runs ───────────────────────────────────────────────────────────
ALTER TABLE ingestion_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion_runs FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON ingestion_runs
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── segments ─────────────────────────────────────────────────────────────────
ALTER TABLE segments ENABLE ROW LEVEL SECURITY;
ALTER TABLE segments FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON segments
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── words ────────────────────────────────────────────────────────────────────
ALTER TABLE words ENABLE ROW LEVEL SECURITY;
ALTER TABLE words FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON words
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── content_graph ────────────────────────────────────────────────────────────
ALTER TABLE content_graph ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_graph FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON content_graph
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── chunks ───────────────────────────────────────────────────────────────────
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON chunks
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── email_templates ──────────────────────────────────────────────────────────
ALTER TABLE email_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_templates FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON email_templates
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── clusters ─────────────────────────────────────────────────────────────────
ALTER TABLE clusters ENABLE ROW LEVEL SECURITY;
ALTER TABLE clusters FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON clusters
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── articles ─────────────────────────────────────────────────────────────────
ALTER TABLE articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE articles FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON articles
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── scheduled_content ────────────────────────────────────────────────────────
ALTER TABLE scheduled_content ENABLE ROW LEVEL SECURITY;
ALTER TABLE scheduled_content FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON scheduled_content
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── mini_series ──────────────────────────────────────────────────────────────
ALTER TABLE mini_series ENABLE ROW LEVEL SECURITY;
ALTER TABLE mini_series FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON mini_series
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── social_posts ─────────────────────────────────────────────────────────────
ALTER TABLE social_posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE social_posts FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON social_posts
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── aggregated_topics ────────────────────────────────────────────────────────
ALTER TABLE aggregated_topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE aggregated_topics FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON aggregated_topics
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── comment_drafts ───────────────────────────────────────────────────────────
ALTER TABLE comment_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE comment_drafts FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON comment_drafts
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── user_settings ────────────────────────────────────────────────────────────
ALTER TABLE user_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_settings FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON user_settings
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── faq_entries ──────────────────────────────────────────────────────────────
ALTER TABLE faq_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE faq_entries FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON faq_entries
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── pricing_configs (F2) ─────────────────────────────────────────────────────
ALTER TABLE pricing_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE pricing_configs FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON pricing_configs
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── estimates (F2) ───────────────────────────────────────────────────────────
ALTER TABLE estimates ENABLE ROW LEVEL SECURITY;
ALTER TABLE estimates FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON estimates
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── measurements (F2) ────────────────────────────────────────────────────────
ALTER TABLE measurements ENABLE ROW LEVEL SECURITY;
ALTER TABLE measurements FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON measurements
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── customers (F3) ───────────────────────────────────────────────────────────
ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE customers FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON customers
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── contacts (F3) ────────────────────────────────────────────────────────────
ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON contacts
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── properties (F3) ──────────────────────────────────────────────────────────
ALTER TABLE properties ENABLE ROW LEVEL SECURITY;
ALTER TABLE properties FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON properties
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── proposal_templates (F3) ──────────────────────────────────────────────────
ALTER TABLE proposal_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE proposal_templates FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON proposal_templates
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── proposals (F3) ───────────────────────────────────────────────────────────
ALTER TABLE proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE proposals FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON proposals
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── proposal_events (F3) ─────────────────────────────────────────────────────
ALTER TABLE proposal_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE proposal_events FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON proposal_events
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── leads (F3) ───────────────────────────────────────────────────────────────
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE leads FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON leads
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── jobs (F3 stub) ───────────────────────────────────────────────────────────
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON jobs
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── catalog_items (F3 stub) ──────────────────────────────────────────────────
ALTER TABLE catalog_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE catalog_items FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON catalog_items
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── tc_versions (F3 stub) ────────────────────────────────────────────────────
ALTER TABLE tc_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE tc_versions FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
    CREATE POLICY tenant_isolation ON tc_versions
        USING      (tenant_id = current_setting('app.tenant_id')::int)
        WITH CHECK (tenant_id = current_setting('app.tenant_id')::int);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── 4. App role hardening ────────────────────────────────────────────────────
-- REQUIRES SUPERUSER — Jon must apply this manually via the Cloud SQL connector
-- as the postgres superuser. Intentionally commented out to prevent accidental
-- execution by the migration runner (which runs as the app role, not superuser).
--
-- Verify current state first:
--   SELECT rolsuper, bypassrls FROM pg_roles WHERE rolname = '<app-role>';
-- Then apply (as superuser):
--   ALTER ROLE <app-role> NOSUPERUSER NOBYPASSRLS;
--
-- This is a one-way DDL change. Validate in staging before applying to prod.
-- If the app role was previously a superuser, verify no other privileges depend on it.

-- ── Down path (RLS disable — instant, no data change) ────────────────────────
-- ALTER TABLE videos            DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE ingestion_runs    DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE segments          DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE words             DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE content_graph     DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE chunks            DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE email_templates   DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE clusters          DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE articles          DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE scheduled_content DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE mini_series       DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE social_posts      DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE aggregated_topics DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE comment_drafts    DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE user_settings     DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE faq_entries       DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE pricing_configs   DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE estimates         DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE measurements      DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE customers         DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE contacts          DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE properties        DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE proposal_templates DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE proposals         DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE proposal_events   DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE leads             DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE jobs              DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE catalog_items     DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE tc_versions       DISABLE ROW LEVEL SECURITY;

-- ═══════════════════════════════════════════════════════════════════════════════
-- GCIP IDENTITY SECTION — f4-identity agent appends here
-- DO NOT EDIT THIS MARKER LINE
-- ═══════════════════════════════════════════════════════════════════════════════

-- ── IDENTITY TABLES (F4b) ─────────────────────────────────────────────────────
-- Owner: f4-identity agent. These tables are platform-level (no tenant_id FK
-- on the table itself, no RLS policies). F5/F6 must reference IF NOT EXISTS.

-- 1. GCIP tenant mapping
CREATE TABLE IF NOT EXISTS tenant_gcip_map (
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    gcip_tenant TEXT    NOT NULL,
    PRIMARY KEY (tenant_id),
    UNIQUE (gcip_tenant)
);

-- 2. Per-tenant default admin list (replaces global DEFAULT_ADMINS constant)
CREATE TABLE IF NOT EXISTS tenant_default_admins (
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email       TEXT    NOT NULL,
    PRIMARY KEY (tenant_id, email)
);

-- 3. Platform admin grants (DeGenito staff; cross-tenant)
CREATE TABLE IF NOT EXISTS platform_admins (
    email       TEXT PRIMARY KEY,
    granted_by  TEXT NOT NULL,
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. Platform audit log — written for every impersonated request
--    (TRD-F4 §4.4 impersonate_tenant invariant #3)
CREATE TABLE IF NOT EXISTS platform_audit_log (
    id                   SERIAL PRIMARY KEY,
    platform_admin_email TEXT        NOT NULL,
    target_tenant_id     INTEGER     NOT NULL,
    route                TEXT        NOT NULL,
    method               TEXT        NOT NULL,
    occurred_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_platform_audit_log_admin
    ON platform_audit_log (platform_admin_email);

-- 5. Seed tenant_default_admins from current DEFAULT_ADMINS for tenant 1.
--    Idempotent: ON CONFLICT DO NOTHING. Add/remove rows here to update the seed.
INSERT INTO tenant_default_admins (tenant_id, email) VALUES
    (1, 'jon@perkinsroofing.net'),
    (1, 'tim@perkinsroofing.net'),
    (1, 'amber@perkinsroofing.net')
ON CONFLICT DO NOTHING;

-- ── Down path (identity tables — drop in reverse dependency order) ────────────
-- DROP TABLE IF EXISTS platform_audit_log;
-- DROP TABLE IF EXISTS platform_admins;
-- DROP TABLE IF EXISTS tenant_default_admins;
-- DROP TABLE IF EXISTS tenant_gcip_map;
