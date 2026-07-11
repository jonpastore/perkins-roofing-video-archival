-- Migration 0032: Knowify data mirror (Wave 1) — crosswalk columns on the money/job
-- tables + two mirror tables (sync watermark + generic lossless raw records).
--
-- Idempotent (ADD COLUMN IF NOT EXISTS, CREATE TABLE IF NOT EXISTS, CREATE INDEX
-- IF NOT EXISTS) so it no-ops if create_all front-ran it. No migration-tracking
-- table exists (per 0030/0031); apply via scripts/apply_migrations_connector.py.
--
-- RLS follows the exact 0030/0031 convention: ENABLE + FORCE + drop/create the
-- tenant_isolation policy with the NULLIF 2-arg GUC. The ORM create_all path also
-- emits a coexisting tenant_isolation_auto policy on these tables (expected, not
-- drift — see TRD §1d).
--
-- MONEY NOTE: knowify_invoice_number is TEXT because Knowify InvoiceNumber is a
-- user-facing STRING (may be non-numeric); it is NOT our integer invoice_number.
-- Imports carry source='knowify_import' with invoice_number=NULL so they never
-- collide with a future v2-issued integer, and the sync never touches
-- tenant_invoice_counters.

-- 1a. Crosswalk columns on existing money/job tables.
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS knowify_invoice_id     VARCHAR(100);
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS knowify_invoice_number TEXT;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS source                 VARCHAR(30) NOT NULL DEFAULT 'v2';
ALTER TABLE payments ADD COLUMN IF NOT EXISTS knowify_payment_id     VARCHAR(100);
ALTER TABLE jobs     ADD COLUMN IF NOT EXISTS knowify_job_id         VARCHAR(100);

-- source CHECK constraint (NOT VALID avoids a long lock on the existing table;
-- new rows are still validated, and every existing row already defaults to 'v2').
-- Guarded so re-applying the migration does not error on the pre-existing constraint.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_invoices_source'
    ) THEN
        ALTER TABLE invoices
            ADD CONSTRAINT chk_invoices_source
            CHECK (source IN ('v2','knowify_import')) NOT VALID;
    END IF;
END $$;

-- Crosswalk lookup indexes (tenant-scoped).
CREATE INDEX IF NOT EXISTS ix_invoices_tenant_knowify ON invoices (tenant_id, knowify_invoice_id);
CREATE INDEX IF NOT EXISTS ix_payments_tenant_knowify ON payments (tenant_id, knowify_payment_id);
CREATE INDEX IF NOT EXISTS ix_jobs_tenant_knowify     ON jobs     (tenant_id, knowify_job_id);

-- Partial-unique indexes: the ON CONFLICT targets that make crosswalk upserts safe.
-- customers.knowify_customer_id + price_book_items.knowify_item_id already exist
-- (models.py / 0031); 0032 only adds the unique partial index where one is missing.
CREATE UNIQUE INDEX IF NOT EXISTS uq_customers_tenant_knowify
    ON customers (tenant_id, knowify_customer_id) WHERE knowify_customer_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_invoices_tenant_knowify_id
    ON invoices (tenant_id, knowify_invoice_id) WHERE knowify_invoice_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_tenant_knowify_id
    ON payments (tenant_id, knowify_payment_id) WHERE knowify_payment_id IS NOT NULL;

-- 1b. knowify_sync_state — per-(tenant, entity) sync watermark + health.
CREATE TABLE IF NOT EXISTS knowify_sync_state (
    id              SERIAL PRIMARY KEY,
    entity          VARCHAR(50)  NOT NULL,          -- 'invoices','clients',...
    last_high_water TIMESTAMPTZ,                    -- max updated_at (or created_at) seen
    last_cursor     VARCHAR(500),                   -- opaque next-page cursor if API is cursor-paged
    last_run_at     TIMESTAMPTZ,
    last_status     VARCHAR(30)  NOT NULL DEFAULT 'never'
                        CHECK (last_status IN ('never','ok','partial','error','auth_error','skipped')),
    last_error      TEXT,
    rows_seen       INTEGER      NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    tenant_id       INTEGER      NOT NULL REFERENCES tenants(id) DEFAULT 1,
    CONSTRAINT uq_knowify_sync_state_tenant_entity UNIQUE (tenant_id, entity)
);
CREATE INDEX IF NOT EXISTS ix_knowify_sync_state_tenant ON knowify_sync_state (tenant_id);

-- 1c. knowify_raw_records — generic lossless mirror with tombstone columns.
CREATE TABLE IF NOT EXISTS knowify_raw_records (
    id           SERIAL PRIMARY KEY,
    entity       VARCHAR(50)  NOT NULL,
    knowify_id   VARCHAR(100) NOT NULL,             -- the record's id in Knowify
    payload      JSONB        NOT NULL,
    content_hash VARCHAR(64)  NOT NULL,             -- sha256 of canonicalized payload
    high_water   TIMESTAMPTZ,                       -- record's updated_at (v2 incremental seed)
    is_present   BOOLEAN      NOT NULL DEFAULT TRUE, -- FALSE = absent from last full pull (deleted upstream)
    deleted_at   TIMESTAMPTZ,                        -- when tombstoned (§2a-bis)
    fetched_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    tenant_id    INTEGER      NOT NULL REFERENCES tenants(id) DEFAULT 1,
    CONSTRAINT uq_knowify_raw_tenant_entity_id UNIQUE (tenant_id, entity, knowify_id)
);
CREATE INDEX IF NOT EXISTS ix_knowify_raw_tenant_entity ON knowify_raw_records (tenant_id, entity);
CREATE INDEX IF NOT EXISTS ix_knowify_raw_high_water    ON knowify_raw_records (tenant_id, entity, high_water);

-- 1d. RLS: ENABLE + FORCE + NULLIF 2-arg tenant_isolation policy on both new tables.
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['knowify_sync_state','knowify_raw_records'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::int) '
            'WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::int)', t);
    END LOOP;
END $$;
