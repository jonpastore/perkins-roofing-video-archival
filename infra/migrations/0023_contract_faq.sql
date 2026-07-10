-- Migration 0023: contract_faq_entries table + RLS (F5 #321)
CREATE TABLE IF NOT EXISTS contract_faq_entries (
    id            SERIAL PRIMARY KEY,
    question      TEXT        NOT NULL,
    answer        TEXT,
    quote         TEXT,
    status        VARCHAR(20) NOT NULL DEFAULT 'draft',
    tc_version_id INTEGER     REFERENCES tc_versions(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    tenant_id     INTEGER     NOT NULL REFERENCES tenants(id) DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_contract_faq_tenant ON contract_faq_entries (tenant_id);
ALTER TABLE contract_faq_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE contract_faq_entries FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON contract_faq_entries;
CREATE POLICY tenant_isolation ON contract_faq_entries
    USING      (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int);
