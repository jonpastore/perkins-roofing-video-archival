-- Migration 0024: Additive columns on measurements for Solar API / Google Squares integration.
-- All changes are ADD COLUMN IF NOT EXISTS — safe on repeated runs, no data loss.
-- RLS is inherited: measurements already has FORCE ROW LEVEL SECURITY + tenant_isolation policy.
-- PROD APPLY: .venv/bin/python scripts/apply_migrations_connector.py

ALTER TABLE measurements
    ADD COLUMN IF NOT EXISTS address          VARCHAR,
    ADD COLUMN IF NOT EXISTS latitude         NUMERIC(9,6),
    ADD COLUMN IF NOT EXISTS longitude        NUMERIC(9,6),
    ADD COLUMN IF NOT EXISTS imagery_date     VARCHAR,
    ADD COLUMN IF NOT EXISTS imagery_quality  VARCHAR,
    ADD COLUMN IF NOT EXISTS source_building  VARCHAR;
