-- Scan jobs (portfolio-scan-daily, later salinity/health) wrote only to Cloud Logging.
-- The weekly digest cannot read logs. Persist one row per tenant per run.

CREATE TABLE IF NOT EXISTS scan_reports (
    id         SERIAL PRIMARY KEY,
    tenant_id  INTEGER NOT NULL REFERENCES tenants(id),
    scan_type  TEXT NOT NULL,
    ran_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload    JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_scan_reports_tenant_type_ran
    ON scan_reports (tenant_id, scan_type, ran_at DESC);

ALTER TABLE scan_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE scan_reports FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS scan_reports_tenant_isolation ON scan_reports;
CREATE POLICY scan_reports_tenant_isolation ON scan_reports
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int);
