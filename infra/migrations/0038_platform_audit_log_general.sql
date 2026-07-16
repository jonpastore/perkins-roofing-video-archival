-- 0038_platform_audit_log_general.sql
-- Generalise platform_audit_log from "impersonation only" into the platform-level audit trail.
--
-- WHY A SECOND TABLE rather than nullable tenant_id on audit_log:
-- audit_log is RLS tenant-scoped, and its policy is
--     tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int
-- A NULL-tenant row evaluates that to NULL (never true), so it would be invisible to everyone,
-- including platform admins. Making it work needs a policy like
--     OR (current_setting('app.platform_scope', true) = 'on' AND tenant_id IS NULL)
-- which puts the most sensitive rows in the schema — who was granted platform_admin, which
-- tenant was provisioned for whom — behind a GUC the application sets on itself, inside the
-- table every tenant queries daily. One policy bug is then a cross-tenant leak.
--
-- Table separation makes that leak structurally impossible, and it is the boundary this schema
-- already draws: tenants, platform_admins, platform_audit_log and tenant_offboard_log are all
-- RLS-exempt and reachable only via PlatformSessionLocal. Merging buys one less query; getting
-- it wrong is a breach.
--
-- Debuggability is answered at the READ layer instead: GET /audit?scope=all unions both for
-- platform admins (the only readers allowed platform rows anyway), and request_id — already on
-- audit_log — stitches a single request that spans both, e.g. a platform admin impersonating
-- tenant 1 and editing a proposal.
--
-- Routing rule: "has a tenant_id" -> audit_log. "is ABOUT tenants, or about the platform
-- itself" -> here. The admin portal's unbuilt actions (provisioning, billing plans, SSO,
-- feature flags) are the latter and have no tenant_id, hence target_tenant_id becomes nullable.

ALTER TABLE platform_audit_log ADD COLUMN IF NOT EXISTS action       VARCHAR(120);
ALTER TABLE platform_audit_log ADD COLUMN IF NOT EXISTS entity_type  VARCHAR(60);
ALTER TABLE platform_audit_log ADD COLUMN IF NOT EXISTS entity_id    VARCHAR(255);
ALTER TABLE platform_audit_log ADD COLUMN IF NOT EXISTS status_code  INTEGER;
ALTER TABLE platform_audit_log ADD COLUMN IF NOT EXISTS request_id   VARCHAR(64);
ALTER TABLE platform_audit_log ADD COLUMN IF NOT EXISTS source       VARCHAR(20) NOT NULL DEFAULT 'api';
ALTER TABLE platform_audit_log ADD COLUMN IF NOT EXISTS path         VARCHAR(1024);
ALTER TABLE platform_audit_log ADD COLUMN IF NOT EXISTS detail       JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Impersonation always had a target; platform-level actions (create a tenant, grant an admin)
-- do not. Existing rows are all impersonation, so nothing is lost by relaxing this.
ALTER TABLE platform_audit_log ALTER COLUMN target_tenant_id DROP NOT NULL;

-- Backfill the rows written before this table had an action, so `action` is never null in
-- practice and the /audit?scope=all union does not show a column of blanks for history.
UPDATE platform_audit_log SET action = 'platform.impersonate' WHERE action IS NULL;

CREATE INDEX IF NOT EXISTS ix_platform_audit_log_time   ON platform_audit_log (occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_platform_audit_log_action ON platform_audit_log (action, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_platform_audit_log_req    ON platform_audit_log (request_id);
