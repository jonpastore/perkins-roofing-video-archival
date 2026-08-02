-- 0055_branch_referential_integrity.sql
-- Jarvis #359 (tenant-2 hardening): make `branch` a reference instead of a free string.
--
-- Five tables carry a `branch` column that is meant to name a row in `branches`, and nothing
-- enforced it. `api/routes/customers.py::_validate_branch` checks it on two endpoints; every
-- other writer — pricing_configs, branch_accounting, estimates, bid_projects, any script, any
-- backfill — could store a branch that does not exist, and a quote priced against a config
-- keyed to a typo'd branch fails open (no active config -> 503) or silently prices somewhere
-- else. It is a tenant-2 gate specifically because branch keys stop being the four we know by
-- heart the moment a second tenant has its own.
--
-- The constraint is COMPOSITE — (tenant_id, branch) -> branches(tenant_id, key), which the
-- existing uq_branches_tenant_key supports. A plain FK on `branch` alone would let tenant 2
-- reference tenant 1's branch keys, which is the isolation hole this is supposed to close.
-- (PostgreSQL runs referential checks with RLS bypassed, so the composite key is what does the
-- isolating here, not the branches policy.)
--
-- MATCH SIMPLE (the default) means a NULL branch skips the check — deliberate: `estimates` and
-- `bid_projects` allow a branchless row and must keep doing so.
--
-- Verified against prod 2026-08-02 before writing: zero orphan (tenant_id, branch) values in
-- all five tables, so VALIDATE will not fail. NOT VALID + VALIDATE is still used so the ACCESS
-- EXCLUSIVE lock is held only for the catalog change and the scan runs under SHARE UPDATE
-- EXCLUSIVE — `estimates` is the largest of these and should not block writes for its scan.
--
-- Idempotent: every step is guarded on pg_constraint. An unguarded ADD CONSTRAINT is exactly
-- what 0040 did, and because the runner has no ledger and replays from 0013 every time, that
-- one aborted the run and silently blocked 0041-0052 from ever applying.

DO $$
DECLARE
    t text;
    c text;
BEGIN
    FOREACH t IN ARRAY ARRAY['customers', 'pricing_configs', 'branch_accounting',
                             'estimates', 'bid_projects']
    LOOP
        c := 'fk_' || t || '_branch';

        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = c) THEN
            EXECUTE format(
                'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (tenant_id, branch) '
                'REFERENCES branches (tenant_id, key) NOT VALID', t, c);
        END IF;

        -- Separate guard: a re-run after a partial apply must still validate.
        IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = c AND NOT convalidated) THEN
            EXECUTE format('ALTER TABLE %I VALIDATE CONSTRAINT %I', t, c);
        END IF;
    END LOOP;
END $$;

-- Down path:
--   ALTER TABLE customers          DROP CONSTRAINT IF EXISTS fk_customers_branch;
--   ALTER TABLE pricing_configs    DROP CONSTRAINT IF EXISTS fk_pricing_configs_branch;
--   ALTER TABLE branch_accounting  DROP CONSTRAINT IF EXISTS fk_branch_accounting_branch;
--   ALTER TABLE estimates          DROP CONSTRAINT IF EXISTS fk_estimates_branch;
--   ALTER TABLE bid_projects       DROP CONSTRAINT IF EXISTS fk_bid_projects_branch;
