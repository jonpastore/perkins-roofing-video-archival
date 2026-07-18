-- 0044_branch_accounting.sql
-- Per-branch QuickBooks/Knowify mapping (B9 scaffold): live QBO OAuth client is
-- HELD (no QB/Qvinci accounts exist yet), so this table holds only the mapping
-- (realm id, company name, Knowify sub) per branch. Idempotent. RLS follows the
-- exact 0043 convention.

CREATE TABLE IF NOT EXISTS branch_accounting (
    id                       SERIAL PRIMARY KEY,
    tenant_id                INTEGER NOT NULL REFERENCES tenants(id) DEFAULT 1,
    branch                   VARCHAR(50) NOT NULL,
    qb_realm_id              VARCHAR(50),
    qb_company_name          VARCHAR(200),
    knowify_subscription_id  VARCHAR(100),
    active                   BOOLEAN NOT NULL DEFAULT true,
    created_at               TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_branch_accounting_tenant_branch UNIQUE (tenant_id, branch)
);

CREATE INDEX IF NOT EXISTS ix_branch_accounting_tenant ON branch_accounting (tenant_id);

-- RLS: ENABLE + FORCE + the standard NULLIF 2-arg tenant_isolation policy.
ALTER TABLE branch_accounting ENABLE ROW LEVEL SECURITY;
ALTER TABLE branch_accounting FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS branch_accounting_tenant_isolation ON branch_accounting;
CREATE POLICY branch_accounting_tenant_isolation ON branch_accounting
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int);
