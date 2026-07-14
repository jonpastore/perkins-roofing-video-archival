-- 0035_email_logs.sql
-- Central outbound-email audit log. The Resend adapter writes one row for every
-- attempted email: sent, blocked, failed, or dry_run. Body content is not stored.

CREATE TABLE IF NOT EXISTS email_logs (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    provider            VARCHAR(50) NOT NULL DEFAULT 'resend',
    send_type           VARCHAR(100) NOT NULL DEFAULT 'resend',
    from_email          VARCHAR(255) NOT NULL,
    to_email            VARCHAR(255) NOT NULL,
    subject             TEXT NOT NULL,
    status              VARCHAR(30) NOT NULL,
    provider_message_id VARCHAR(255),
    error               TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT chk_email_logs_status
        CHECK (status IN ('blocked','sent','failed','dry_run'))
);

CREATE INDEX IF NOT EXISTS ix_email_logs_tenant_created
    ON email_logs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_email_logs_tenant_status
    ON email_logs (tenant_id, status);
CREATE INDEX IF NOT EXISTS ix_email_logs_tenant_send_type
    ON email_logs (tenant_id, send_type);

DO $$
BEGIN
    ALTER TABLE email_logs ENABLE ROW LEVEL SECURITY;
    ALTER TABLE email_logs FORCE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON email_logs;
    CREATE POLICY tenant_isolation ON email_logs
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int)
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::int);
END $$;
