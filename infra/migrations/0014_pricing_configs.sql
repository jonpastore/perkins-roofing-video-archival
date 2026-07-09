-- Migration 0014: Versioned per-tenant, per-branch pricing configuration.
-- Immutable rows: new row per edit; is_active pointer for activation.
-- Idempotent: CREATE TABLE IF NOT EXISTS / ON CONFLICT DO NOTHING.
-- PROD APPLY: requires Jon's explicit permission + fresh ADC.
-- Run: .venv/bin/python scripts/apply_migrations_connector.py

-- ── 1. pricing_configs table ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS pricing_configs (
    id           SERIAL PRIMARY KEY,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id),
    branch       VARCHAR NOT NULL,
    version      INTEGER NOT NULL,
    label        VARCHAR,
    config       JSONB NOT NULL,
    config_hash  CHAR(64) NOT NULL,
    is_active    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by   VARCHAR NOT NULL,
    CONSTRAINT uq_pricing_configs_tenant_branch_version
        UNIQUE (tenant_id, branch, version),
    CONSTRAINT uq_pricing_configs_active_branch
        UNIQUE (tenant_id, branch, is_active)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS ix_pricing_configs_tenant_branch
    ON pricing_configs (tenant_id, branch);

-- ── 2. Seed ───────────────────────────────────────────────────────────────────
-- Seeding is handled by scripts/seed_pricing_configs.py (not inline SQL).
-- pg8000 cannot bind psql-style :'var' substitution variables, so the seed
-- was moved to Python which uses parameterized queries.
-- After applying 0014 and 0015, run:
--   python scripts/seed_pricing_configs.py
-- to insert the Exhibit B fixture for tenant 1 (miami/jupiter/naples).
-- Verify with:
--   python scripts/seed_pricing_configs.py --check

-- ── Down path (additive migration — no data lost on rollback) ─────────────────
-- DROP TABLE IF EXISTS pricing_configs;
