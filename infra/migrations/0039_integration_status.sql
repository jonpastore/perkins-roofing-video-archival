-- 0039_integration_status.sql
-- Integration health status + OAuth state nonces (plan 2026-07-17 Phase 1.2/1.5).
--
-- BOTH tables are PLATFORM-LEVEL: no RLS, reachable via PlatformSessionLocal, same
-- boundary as tenant_offboard_log / platform_audit_log (see 0038's header for the full
-- rationale — a NULL-tenant row under the standard RLS policy is invisible to everyone,
-- and probing shared integrations runs with no tenant GUC at all). Tenant filtering for
-- integration_status happens in-query. NEITHER table is added to core/offboard.py's
-- _TENANT_SCOPED_TABLES: status strings and short-lived nonces are not tenant content,
-- and shared (NULL-tenant) rows must survive any tenant's offboarding.

-- Per-integration health: one row per (tenant, integration) for per-tenant OAuth creds,
-- one NULL-tenant row per shared platform integration (knowify, resend, wordpress).
CREATE TABLE IF NOT EXISTS integration_status (
    id                   SERIAL PRIMARY KEY,
    tenant_id            INTEGER,            -- NULL = platform-level shared integration
    integration          TEXT NOT NULL,      -- e.g. 'youtube_reply', 'knowify', 'resend', 'wordpress', 'tiktok'
    status               TEXT NOT NULL DEFAULT 'unconfigured',  -- unconfigured|healthy|expiring|broken
    last_checked         TIMESTAMPTZ,
    last_ok              TIMESTAMPTZ,
    last_error           TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Uniqueness must hold for both shapes; NULL never collides in a plain UNIQUE, so use
-- partial indexes: one per-tenant, one for the shared (NULL-tenant) namespace.
CREATE UNIQUE INDEX IF NOT EXISTS uq_integration_status_tenant
    ON integration_status (tenant_id, integration) WHERE tenant_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_integration_status_shared
    ON integration_status (integration) WHERE tenant_id IS NULL;

-- OAuth capture-flow state nonces (single-use; burned via DELETE ... RETURNING at the
-- callback). The callback is an unauthenticated browser GET: the signed state + this
-- nonce ARE the tenant binding, so rows are platform-level by construction. expires_at
-- enforced at validation; expired rows are swept opportunistically by the health job.
CREATE TABLE IF NOT EXISTS oauth_state_nonces (
    nonce      TEXT PRIMARY KEY,
    tenant_id  INTEGER NOT NULL,
    platform   TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);

-- Both tables carry a tenant_id column, so app/models.py's _rls_on_create
-- after_create hook (which FORCE-RLS's every tenant_id table) will have stamped
-- them if create_all ran before this migration. They are platform-level (no RLS),
-- so undo it here — idempotent, and the hook is also fixed to exempt these names.
ALTER TABLE integration_status DISABLE ROW LEVEL SECURITY;
ALTER TABLE integration_status NO FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_auto ON integration_status;
ALTER TABLE oauth_state_nonces DISABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_state_nonces NO FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation_auto ON oauth_state_nonces;
