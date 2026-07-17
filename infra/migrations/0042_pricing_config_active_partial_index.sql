-- 0042_pricing_config_active_partial_index.sql
-- Fix the pricing-config "one active per branch" guard.
--
-- 0014 declared CONSTRAINT uq_pricing_configs_active_branch UNIQUE(tenant_id, branch,
-- is_active). That does NOT mean "one active per branch" — it means at most ONE active
-- AND at most ONE inactive row per branch, capping version history at 2. The documented
-- intent (0014 header: "Immutable rows: new row per edit; is_active pointer") is a full
-- version history with a single active pointer. Once a branch accumulated a 2nd version
-- (config edits / the 2026-07-17 gutters+daily seeds), both creating another version
-- (POST /estimator/configs inserts is_active=false → collides with the existing inactive
-- row → 409) and re-activating (two inactive rows at commit) started failing.
--
-- Replace it with a PARTIAL unique index: at most one is_active=true per (tenant, branch),
-- unlimited inactive history. Idempotent.

ALTER TABLE pricing_configs DROP CONSTRAINT IF EXISTS uq_pricing_configs_active_branch;

CREATE UNIQUE INDEX IF NOT EXISTS uq_pricing_configs_one_active_per_branch
    ON pricing_configs (tenant_id, branch)
    WHERE is_active;
