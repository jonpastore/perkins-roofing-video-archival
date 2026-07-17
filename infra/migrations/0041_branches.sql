-- 0041_branches.sql
-- Branch management (Zoom 2026-07-17 [40:00-41:11]): branches become first-class rows
-- instead of the hardcoded miami/jupiter/naples selector; customers carry a branch and
-- every child asset inherits it. Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS branches (
    id         SERIAL PRIMARY KEY,
    tenant_id  INTEGER NOT NULL DEFAULT 1,
    key        VARCHAR(50)  NOT NULL,
    name       VARCHAR(100) NOT NULL,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    sort       INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_branches_tenant_key UNIQUE (tenant_id, key)
);

-- RLS (matches the _rls_on_create convention for tenant tables)
ALTER TABLE branches ENABLE ROW LEVEL SECURITY;
ALTER TABLE branches FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS branches_tenant_isolation ON branches;
CREATE POLICY branches_tenant_isolation ON branches
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int);

-- Seed tenant 1 branches (gc = Tim's fourth company, no pricing config yet).
-- FORCE RLS applies to the owner too: stamp the tenant GUC for this transaction
-- or the seed INSERT is rejected (same class as the price-book seed, 8b40b4a).
SET LOCAL app.tenant_id = '1';
INSERT INTO branches (tenant_id, key, name, sort) VALUES
    (1, 'miami',   'Miami',   1),
    (1, 'jupiter', 'Jupiter', 2),
    (1, 'naples',  'Naples',  3),
    (1, 'gc',      'GC',      4)
ON CONFLICT (tenant_id, key) DO NOTHING;

-- Customers: branch column, backfill miami (only Miami Knowify is connected today —
-- Zoom [25:41] "it's from miami... Josh added me to Miami")
ALTER TABLE customers ADD COLUMN IF NOT EXISTS branch VARCHAR(50) NOT NULL DEFAULT 'miami';
