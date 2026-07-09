-- Wave F3: Quoting / Proposals
-- Migration: 0017_quoting.sql
-- All tables are tenant-scoped (tenant_id FK to tenants.id). RLS added in F4.
-- All CREATE statements are idempotent (IF NOT EXISTS / DO $$ EXCEPTION blocks).
-- Dependency: 0013 (tenants), 0014 (pricing_configs), 0015 (estimates + measurements stub)
-- PROD APPLY: requires Jon's explicit OK + fresh ADC.
-- Run: .venv/bin/python scripts/apply_migrations_connector.py

-- ── ENUM types (idempotent: CREATE TYPE IF NOT EXISTS is invalid Postgres syntax;
--    use DO $$ ... EXCEPTION WHEN duplicate_object THEN NULL $$ pattern instead) ──

DO $$ BEGIN
    CREATE TYPE proposal_status AS ENUM (
        'draft',
        'sent',
        'viewed',
        'accepted',
        'declined',
        'revision_requested',
        'superseded'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE proposal_event_type AS ENUM (
        'sent',
        'viewed',
        'accepted',
        'declined',
        'revision_requested',
        'reminder_sent'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE lead_status AS ENUM (
        'new',
        'contacted',
        'qualified',
        'converted',
        'lost'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── 1. customers ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS customers (
    id                   SERIAL PRIMARY KEY,
    tenant_id            INTEGER NOT NULL REFERENCES tenants(id),
    display_name         VARCHAR(255) NOT NULL,
    company_name         VARCHAR(255),
    email                VARCHAR(255),
    phone                VARCHAR(50),
    knowify_customer_id  VARCHAR(100),
    notes                TEXT,
    created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_customers_tenant
    ON customers(tenant_id);

CREATE INDEX IF NOT EXISTS ix_customers_knowify
    ON customers(tenant_id, knowify_customer_id)
    WHERE knowify_customer_id IS NOT NULL;

-- ── 2. contacts ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS contacts (
    id           SERIAL PRIMARY KEY,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id),
    customer_id  INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    name         VARCHAR(255) NOT NULL,
    role         VARCHAR(100),
    email        VARCHAR(255),
    phone        VARCHAR(50),
    is_primary   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_contacts_customer
    ON contacts(customer_id);

-- ── 3. properties ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS properties (
    id                   SERIAL PRIMARY KEY,
    tenant_id            INTEGER NOT NULL REFERENCES tenants(id),
    customer_id          INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    street               VARCHAR(255) NOT NULL,
    city                 VARCHAR(100) NOT NULL,
    state                VARCHAR(2)   NOT NULL DEFAULT 'FL',
    zip                  VARCHAR(10),
    county               VARCHAR(100),
    code_zone            VARCHAR(10)  NOT NULL DEFAULT 'FBC',
    knowify_customer_id  VARCHAR(100),
    gcs_pdf_prefix       VARCHAR(500),
    notes                TEXT,
    created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_properties_tenant
    ON properties(tenant_id);

CREATE INDEX IF NOT EXISTS ix_properties_customer
    ON properties(customer_id);

-- ── 4. proposal_templates ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS proposal_templates (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id),
    name                VARCHAR(255) NOT NULL,
    is_default          BOOLEAN NOT NULL DEFAULT FALSE,
    html_body           TEXT NOT NULL,
    logo_url            VARCHAR(1000),
    primary_color       VARCHAR(7),
    accent_color        VARCHAR(7),
    footer_text         TEXT,
    tc_attachment_gcs   VARCHAR(1000),
    cover_page_html     TEXT,
    created_by          VARCHAR(255) NOT NULL,
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Only one default template per tenant.
CREATE UNIQUE INDEX IF NOT EXISTS uq_template_default_per_tenant
    ON proposal_templates(tenant_id)
    WHERE is_default = TRUE;

CREATE INDEX IF NOT EXISTS ix_templates_tenant
    ON proposal_templates(tenant_id);

-- ── 5. proposals ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS proposals (
    id                    SERIAL PRIMARY KEY,
    tenant_id             INTEGER NOT NULL REFERENCES tenants(id),
    customer_id           INTEGER NOT NULL REFERENCES customers(id),
    property_id           INTEGER NOT NULL REFERENCES properties(id),
    template_id           INTEGER REFERENCES proposal_templates(id),

    -- Version chain
    root_id               INTEGER REFERENCES proposals(id),
    parent_id             INTEGER REFERENCES proposals(id),
    version_number        INTEGER NOT NULL DEFAULT 1,

    -- Content
    title                 VARCHAR(500) NOT NULL,
    quote_snapshot        JSONB NOT NULL,
    selected_tier         VARCHAR(50),
    selected_options      JSONB,

    -- Status machine
    status                proposal_status NOT NULL DEFAULT 'draft',

    -- E-sign fields
    accept_token          VARCHAR(86) NOT NULL UNIQUE,
    accepted_by_name      VARCHAR(255),
    accepted_at           TIMESTAMP,
    accepted_ip           INET,
    accepted_ua           TEXT,
    consent_electronic    BOOLEAN,

    -- PDF delivery
    signed_pdf_gcs        VARCHAR(1000),
    signed_pdf_emailed_at TIMESTAMP,

    -- Audit
    created_by            VARCHAR(255) NOT NULL,
    sent_at               TIMESTAMP,
    created_at            TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_proposals_tenant
    ON proposals(tenant_id);

CREATE INDEX IF NOT EXISTS ix_proposals_customer
    ON proposals(customer_id);

CREATE INDEX IF NOT EXISTS ix_proposals_root
    ON proposals(root_id);

CREATE INDEX IF NOT EXISTS ix_proposals_token
    ON proposals(accept_token);

CREATE INDEX IF NOT EXISTS ix_proposals_status
    ON proposals(tenant_id, status);

-- ── 6. jobs (stub — created on acceptance; full build-out post-F3) ───────────

CREATE TABLE IF NOT EXISTS jobs (
    id          SERIAL PRIMARY KEY,
    tenant_id   INTEGER NOT NULL REFERENCES tenants(id),
    proposal_id INTEGER REFERENCES proposals(id),
    status      VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_jobs_tenant
    ON jobs(tenant_id);

-- ── 7. catalog_items (stub — Knowify import target; full build-out post-F3) ──

CREATE TABLE IF NOT EXISTS catalog_items (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    name            VARCHAR(255) NOT NULL,
    unit            VARCHAR(50),
    unit_price      NUMERIC(10,2),
    knowify_item_id VARCHAR(100),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_catalog_items_tenant
    ON catalog_items(tenant_id);

-- ── 8. tc_versions (stub — T&C version referenced by proposals/consent) ──────

CREATE TABLE IF NOT EXISTS tc_versions (
    id           SERIAL PRIMARY KEY,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id),
    version_tag  VARCHAR(50) NOT NULL,
    content_gcs  VARCHAR(1000),
    effective_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_tc_versions_tenant
    ON tc_versions(tenant_id);

-- ── 9. proposal_events ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS proposal_events (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id),
    proposal_id  INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    event_type   proposal_event_type NOT NULL,
    occurred_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    ip_address   INET,
    user_agent   TEXT,
    actor_email  VARCHAR(255),
    metadata     JSONB
);

CREATE INDEX IF NOT EXISTS ix_events_proposal
    ON proposal_events(proposal_id, occurred_at);

CREATE INDEX IF NOT EXISTS ix_events_tenant
    ON proposal_events(tenant_id, event_type);

-- ── 10. leads ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS leads (
    id                    SERIAL PRIMARY KEY,
    tenant_id             INTEGER NOT NULL REFERENCES tenants(id),
    name                  VARCHAR(255) NOT NULL,
    email                 VARCHAR(255),
    phone                 VARCHAR(50),
    source                VARCHAR(100),
    notes                 TEXT,
    status                lead_status NOT NULL DEFAULT 'new',
    converted_customer_id INTEGER REFERENCES customers(id),
    created_at            TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_leads_tenant
    ON leads(tenant_id, status);

-- ── Down path (additive migration — drop in reverse dependency order) ─────────
-- DROP TABLE IF EXISTS proposal_events CASCADE;
-- DROP TABLE IF EXISTS proposals CASCADE;
-- DROP TABLE IF EXISTS leads CASCADE;
-- DROP TABLE IF EXISTS jobs CASCADE;
-- DROP TABLE IF EXISTS catalog_items CASCADE;
-- DROP TABLE IF EXISTS tc_versions CASCADE;
-- DROP TABLE IF EXISTS proposal_templates CASCADE;
-- DROP TABLE IF EXISTS contacts CASCADE;
-- DROP TABLE IF EXISTS properties CASCADE;
-- DROP TABLE IF EXISTS customers CASCADE;
-- DROP TYPE IF EXISTS proposal_status;
-- DROP TYPE IF EXISTS proposal_event_type;
-- DROP TYPE IF EXISTS lead_status;
