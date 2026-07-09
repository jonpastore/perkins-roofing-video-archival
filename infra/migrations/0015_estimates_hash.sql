-- Migration 0015: Pricing audit columns on estimates + measurements stub table.
-- Additive: ADD COLUMN IF NOT EXISTS; safe on repeated runs.
-- PROD APPLY: requires Jon's explicit permission + fresh ADC.
-- Run: .venv/bin/python scripts/apply_migrations_connector.py

-- ── 1. Estimates table — pricing audit columns ───────────────────────────────

-- Create estimates table if it does not exist yet (F2 first creates it).
CREATE TABLE IF NOT EXISTS estimates (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by          VARCHAR
);

ALTER TABLE estimates
    ADD COLUMN IF NOT EXISTS pricing_config_id   INTEGER REFERENCES pricing_configs(id),
    ADD COLUMN IF NOT EXISTS pricing_config_hash CHAR(64),
    ADD COLUMN IF NOT EXISTS branch              VARCHAR,
    ADD COLUMN IF NOT EXISTS code_zone           VARCHAR,
    ADD COLUMN IF NOT EXISTS county              VARCHAR,
    ADD COLUMN IF NOT EXISTS input_json          JSONB,
    ADD COLUMN IF NOT EXISTS result_json         JSONB;

CREATE INDEX IF NOT EXISTS ix_estimates_tenant_id ON estimates (tenant_id);

-- ── 2. Measurements stub table (F2 shell; F2b adds provider-specific columns) ─

CREATE TABLE IF NOT EXISTS measurements (
    id                SERIAL PRIMARY KEY,
    tenant_id         INTEGER NOT NULL REFERENCES tenants(id),
    property_id       INTEGER,
    provider          VARCHAR NOT NULL DEFAULT 'manual',
    status            VARCHAR NOT NULL DEFAULT 'complete',
    total_sq          NUMERIC(10,2),
    hips_lf           NUMERIC(10,2),
    ridges_lf         NUMERIC(10,2),
    valleys_lf        NUMERIC(10,2),
    rakes_lf          NUMERIC(10,2),
    eaves_lf          NUMERIC(10,2),
    wall_flashings_lf NUMERIC(10,2),
    pitch_primary     NUMERIC(5,2),
    segments_json     JSONB,
    confidence        NUMERIC(4,3),
    raw_payload       JSONB,
    provenance_note   VARCHAR,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by        VARCHAR NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_measurements_tenant ON measurements (tenant_id);

-- ── Down path (additive — no data lost on rollback) ───────────────────────────
-- ALTER TABLE estimates DROP COLUMN IF EXISTS pricing_config_id;
-- ALTER TABLE estimates DROP COLUMN IF EXISTS pricing_config_hash;
-- ALTER TABLE estimates DROP COLUMN IF EXISTS branch;
-- ALTER TABLE estimates DROP COLUMN IF EXISTS code_zone;
-- ALTER TABLE estimates DROP COLUMN IF EXISTS county;
-- ALTER TABLE estimates DROP COLUMN IF EXISTS input_json;
-- ALTER TABLE estimates DROP COLUMN IF EXISTS result_json;
-- DROP TABLE IF EXISTS measurements;
