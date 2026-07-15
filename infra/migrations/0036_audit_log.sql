-- 0036_audit_log.sql
-- Central audit trail: who did what, when, to which entity, and what happened.
--
-- Every mutating HTTP request writes one row (api/audit_mw.py), so coverage cannot drift as
-- endpoints are added — there are 86 mutating endpoints across 25 route modules and
-- hand-instrumenting each one guarantees the 87th is forgotten. Domain code adds semantic
-- rows on top (core/audit.record) where the route alone does not say what happened.
--
-- Failed requests are audited too: a 403 nobody can explain, or a 500 mid-write, is exactly
-- what this exists to debug. Rows are therefore written in their own transaction and survive
-- the request's rollback.
--
-- Scope: tenant-scoped actions. Platform-admin impersonation keeps its own trail in
-- platform_audit_log; tenant offboarding in tenant_offboard_log.

CREATE TABLE IF NOT EXISTS audit_log (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        INTEGER NOT NULL REFERENCES tenants(id) DEFAULT 1,
    occurred_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- actor
    actor_email      VARCHAR(320),
    actor_role       VARCHAR(50),
    impersonating    BOOLEAN NOT NULL DEFAULT FALSE,
    impersonating_as INTEGER,

    -- what
    action           VARCHAR(120) NOT NULL,   -- "article.create", "proposal.sign"
    entity_type      VARCHAR(60),             -- "article", "proposal", "estimate"
    entity_id        VARCHAR(255),

    -- how
    method           VARCHAR(10),
    route            VARCHAR(255),            -- templated path: /articles/{slug}
    path             VARCHAR(1024),           -- concrete path as requested
    status_code      INTEGER,
    request_id       VARCHAR(64),
    source           VARCHAR(20) NOT NULL DEFAULT 'api',  -- api | job | script

    -- why / detail. Redacted before write (core.audit.redact): never secrets or bodies.
    detail           JSONB NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT chk_audit_log_source CHECK (source IN ('api','job','script','system'))
);

-- The three ways this gets read: "what happened lately", "what did this person do",
-- "what happened to this thing".
CREATE INDEX IF NOT EXISTS ix_audit_log_tenant_time
    ON audit_log (tenant_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_log_tenant_actor
    ON audit_log (tenant_id, actor_email, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_log_tenant_entity
    ON audit_log (tenant_id, entity_type, entity_id);
CREATE INDEX IF NOT EXISTS ix_audit_log_tenant_action
    ON audit_log (tenant_id, action, occurred_at DESC);

DO $$
BEGIN
    ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
    ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON audit_log;
    CREATE POLICY tenant_isolation ON audit_log
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int);
END $$;
