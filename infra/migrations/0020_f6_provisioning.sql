-- Migration 0020: F6 provisioning seeds
-- PROD APPLY: requires Jon's explicit permission + fresh ADC.
-- Run: .venv/bin/python scripts/apply_migrations_connector.py
--
-- Ownership note: tenants, tenant_gcip_map, platform_admins, tenant_default_admins,
-- and tenant_offboard_log are all owned by earlier migrations (0018 / 0019).
-- This migration ONLY seeds data — no DDL. All INSERTs use ON CONFLICT DO NOTHING
-- so re-running is safe (idempotent).
--
-- What this migration does:
--   1. Seed platform_admins with Jon's email if not already present (idempotent).
--   2. No tenant_gcip_map entries: no real GCIP tenants exist yet at migration time.
--      When Jon provisions the first real tenant via POST /internal/tenants the
--      provision_tenant() function handles the gcip_map INSERT at runtime.
--      A comment placeholder documents this expectation for future operators.
--
-- What this migration does NOT do:
--   - Re-create any tables (all owned by 0018/0019).
--   - Add any columns (tenants.status already exists from 0018).
--   - Insert tenant_gcip_map rows (none exist yet; runtime-managed by provision_tenant).
--
-- .sql extension required: scripts/apply_migrations_connector.py globs *.sql only.
-- A .py file would be silently skipped (TRD-F6 §8 note).

-- ── 1. Seed platform_admins with Jon's email ─────────────────────────────────
-- Idempotent: ON CONFLICT DO NOTHING.
-- granted_by = 'bootstrap' marks entries seeded via migration rather than via the UI.
INSERT INTO platform_admins (email, granted_by, granted_at)
VALUES ('jon@degenito.ai', 'bootstrap', NOW())
ON CONFLICT (email) DO NOTHING;

-- ── 2. tenant_gcip_map seeds ─────────────────────────────────────────────────
-- No rows to seed at F6 migration time. Real GCIP tenants do not exist yet —
-- they are created at runtime by provision_tenant() (core/provision.py) which
-- handles the INSERT into tenant_gcip_map immediately after GCIP tenant creation.
--
-- To verify after provisioning the first tenant in prod:
--   SELECT t.slug, m.gcip_tenant
--   FROM tenants t JOIN tenant_gcip_map m ON m.tenant_id = t.id
--   WHERE t.id != 1;
--
-- (No SQL statements needed here; this comment is the documentation.)

-- ── Down path (reference only — not executed by runner) ──────────────────────
-- DELETE FROM platform_admins WHERE email = 'jon@degenito.ai' AND granted_by = 'bootstrap';
-- (tenant_gcip_map has no seed rows to remove)
