-- Migration 0030: JB4 billing core — invoices, lines, milestone schedules/draws,
-- payments, credits, job documents (HOA/ACC), immutable billing-event ledger, and
-- the per-tenant invoice-number counter. Money-critical (plan JB4).
--
-- Every table is tenant-scoped + RLS-FORCED (NULLIF 2-arg GUC policy), matching
-- 0023. Enums are VARCHAR + CHECK to mirror the ORM's native_enum=False columns.
-- Idempotent (CREATE TABLE IF NOT EXISTS) so it no-ops if create_all front-ran it.
--
-- NUMBERING: the Perkins (tenant 1) counter is seeded at the LIVE Knowify max
-- (18732 as of 2026-07-10, from the read-only MCP pull) so the next issued number
-- is 18733 — NOT the plan's assumed 653 (that was an old 7-invoice sample; the live
-- sequence is at 18732). This value MUST be re-confirmed against the live max
-- immediately before cutover (Open Question #3 / Pre-mortem #2).

CREATE TABLE IF NOT EXISTS milestone_schedules (
    id                  SERIAL PRIMARY KEY,
    job_id              INTEGER      NOT NULL REFERENCES jobs(id),
    proposal_id         INTEGER      REFERENCES proposals(id),
    template_id         INTEGER,
    milestones_snapshot JSONB        NOT NULL DEFAULT '[]'::jsonb,
    snapshot_hash       VARCHAR(64),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    tenant_id           INTEGER      NOT NULL REFERENCES tenants(id) DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_milestone_schedules_job    ON milestone_schedules (job_id);
CREATE INDEX IF NOT EXISTS ix_milestone_schedules_tenant ON milestone_schedules (tenant_id);

CREATE TABLE IF NOT EXISTS milestone_draws (
    id              SERIAL PRIMARY KEY,
    job_id          INTEGER      NOT NULL REFERENCES jobs(id),
    schedule_id     INTEGER      REFERENCES milestone_schedules(id),
    sequence_number INTEGER      NOT NULL,
    milestone_name  VARCHAR(255),
    pct_due         NUMERIC(6,4) NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','invoiced','paid')),
    invoice_id      INTEGER,     -- soft ref (set on invoice creation; no FK, avoids cycle)
    planned_date    TIMESTAMPTZ,
    actual_date     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    tenant_id       INTEGER      NOT NULL REFERENCES tenants(id) DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_milestone_draws_job    ON milestone_draws (job_id, sequence_number);
CREATE INDEX IF NOT EXISTS ix_milestone_draws_tenant ON milestone_draws (tenant_id);

CREATE TABLE IF NOT EXISTS invoices (
    id                SERIAL PRIMARY KEY,
    invoice_number    INTEGER,           -- NULL until issued; per-tenant sequential
    job_id            INTEGER      NOT NULL REFERENCES jobs(id),
    customer_id       INTEGER      NOT NULL REFERENCES customers(id),
    proposal_id       INTEGER      REFERENCES proposals(id),
    milestone_draw_id INTEGER      REFERENCES milestone_draws(id),
    status            VARCHAR(20)  NOT NULL DEFAULT 'draft'
                          CHECK (status IN ('draft','sent','viewed','partially_paid','paid','voided')),
    invoice_date      TIMESTAMPTZ,
    due_date          TIMESTAMPTZ,
    milestone_pct     NUMERIC(6,4),
    subtotal          NUMERIC(12,2) NOT NULL DEFAULT 0,
    tax_amount        NUMERIC(12,2) NOT NULL DEFAULT 0,
    credit_amount     NUMERIC(12,2) NOT NULL DEFAULT 0,
    total             NUMERIC(12,2) NOT NULL DEFAULT 0,
    comments          TEXT,
    pdf_gcs           VARCHAR(1000),
    qb_entity_id      VARCHAR(100),
    qb_synced_at      TIMESTAMPTZ,
    qb_sync_status    VARCHAR(20)  CHECK (qb_sync_status IN ('pending','synced','error')),
    qb_error_message  TEXT,
    created_by        VARCHAR(255) NOT NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    tenant_id         INTEGER      NOT NULL REFERENCES tenants(id) DEFAULT 1,
    -- NULLs distinct in Postgres → many drafts coexist; issued numbers unique per tenant.
    CONSTRAINT uq_invoices_tenant_number UNIQUE (tenant_id, invoice_number)
);
CREATE INDEX IF NOT EXISTS ix_invoices_tenant        ON invoices (tenant_id);
CREATE INDEX IF NOT EXISTS ix_invoices_job           ON invoices (job_id);
CREATE INDEX IF NOT EXISTS ix_invoices_tenant_status ON invoices (tenant_id, status);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id            SERIAL PRIMARY KEY,
    invoice_id    INTEGER      NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    line_type     VARCHAR(20)  NOT NULL DEFAULT 'scope'
                      CHECK (line_type IN ('scope','discount','addon','tax','credit')),
    description   TEXT         NOT NULL,
    scope_id      INTEGER,     -- FK to a job-scope entity (not yet modeled)
    milestone_pct NUMERIC(6,4),
    quantity      NUMERIC(10,2) NOT NULL DEFAULT 1,
    unit_price    NUMERIC(12,2) NOT NULL DEFAULT 0,  -- NEGATIVE for discount lines
    subtotal      NUMERIC(12,2) NOT NULL DEFAULT 0,
    is_optional   BOOLEAN      NOT NULL DEFAULT FALSE,
    sort_order    INTEGER      NOT NULL DEFAULT 0,
    tenant_id     INTEGER      NOT NULL REFERENCES tenants(id) DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_invoice_lines_invoice ON invoice_lines (invoice_id, sort_order);
CREATE INDEX IF NOT EXISTS ix_invoice_lines_tenant  ON invoice_lines (tenant_id);

CREATE TABLE IF NOT EXISTS payments (
    id             SERIAL PRIMARY KEY,
    invoice_id     INTEGER      NOT NULL REFERENCES invoices(id),
    payment_date   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    amount         NUMERIC(12,2) NOT NULL,
    method         VARCHAR(20)  NOT NULL DEFAULT 'check'
                       CHECK (method IN ('check','ach','card','cash','other')),
    reference      VARCHAR(255),
    notes          TEXT,
    qb_entity_id   VARCHAR(100),
    qb_synced_at   TIMESTAMPTZ,
    qb_sync_status VARCHAR(20)  CHECK (qb_sync_status IN ('pending','synced','error')),
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    tenant_id      INTEGER      NOT NULL REFERENCES tenants(id) DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_payments_invoice ON payments (invoice_id);
CREATE INDEX IF NOT EXISTS ix_payments_tenant  ON payments (tenant_id);

CREATE TABLE IF NOT EXISTS credits (
    id                    SERIAL PRIMARY KEY,
    customer_id           INTEGER      NOT NULL REFERENCES customers(id),
    job_id                INTEGER      REFERENCES jobs(id),
    amount                NUMERIC(12,2) NOT NULL,
    reason                TEXT,
    applied_to_invoice_id INTEGER      REFERENCES invoices(id),
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    tenant_id             INTEGER      NOT NULL REFERENCES tenants(id) DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_credits_customer ON credits (customer_id);
CREATE INDEX IF NOT EXISTS ix_credits_tenant   ON credits (tenant_id);

CREATE TABLE IF NOT EXISTS job_documents (
    id                        SERIAL PRIMARY KEY,
    job_id                    INTEGER      NOT NULL REFERENCES jobs(id),
    doc_type                  VARCHAR(50)  NOT NULL DEFAULT 'hoa_acc_approval',
    reference_number          VARCHAR(100),
    hoa_name                  VARCHAR(255),
    management_company        VARCHAR(255),
    approval_date             TIMESTAMPTZ,
    scope_approved            TEXT,
    status                    VARCHAR(30)  NOT NULL DEFAULT 'pending'
                                  CHECK (status IN ('pending','approved','approved_pending_inspection','denied')),
    permit_responsibility     VARCHAR(50),
    final_inspection_required BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at                TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    tenant_id                 INTEGER      NOT NULL REFERENCES tenants(id) DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_job_documents_job    ON job_documents (job_id);
CREATE INDEX IF NOT EXISTS ix_job_documents_tenant ON job_documents (tenant_id);

CREATE TABLE IF NOT EXISTS job_billing_events (
    id              SERIAL PRIMARY KEY,
    job_id          INTEGER      REFERENCES jobs(id),
    invoice_id      INTEGER      REFERENCES invoices(id),
    event_type      VARCHAR(30)  NOT NULL
                        CHECK (event_type IN ('invoice_issued','invoice_sent','invoice_voided',
                                              'payment_recorded','credit_applied','draw_created','qb_synced')),
    payload         JSONB        NOT NULL DEFAULT '{}'::jsonb,
    idempotency_key VARCHAR(255),
    source          VARCHAR(50)  NOT NULL DEFAULT 'api',
    received_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    tenant_id       INTEGER      NOT NULL REFERENCES tenants(id) DEFAULT 1,
    CONSTRAINT uq_billing_events_tenant_idem UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_billing_events_job     ON job_billing_events (job_id, received_at);
CREATE INDEX IF NOT EXISTS ix_billing_events_invoice ON job_billing_events (invoice_id);
CREATE INDEX IF NOT EXISTS ix_billing_events_tenant  ON job_billing_events (tenant_id);

CREATE TABLE IF NOT EXISTS tenant_invoice_counters (
    tenant_id   INTEGER      PRIMARY KEY REFERENCES tenants(id),
    last_number INTEGER      NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- RLS: ENABLE + FORCE + NULLIF 2-arg tenant_isolation policy on every table above.
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'milestone_schedules','milestone_draws','invoices','invoice_lines',
        'payments','credits','job_documents','job_billing_events','tenant_invoice_counters'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::int) '
            'WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::int)', t);
    END LOOP;
END $$;

-- Seed the Perkins (tenant 1) invoice counter at the live Knowify max (next issued = 18733).
-- MUST re-confirm the live max immediately before cutover (Open Question #3).
INSERT INTO tenant_invoice_counters (tenant_id, last_number)
SELECT 1, 18732
WHERE NOT EXISTS (SELECT 1 FROM tenant_invoice_counters WHERE tenant_id = 1);
