-- Migration 0031: JB1 price-book engine — editable catalog + immutable snapshots.
--
-- price_books     — immutable versioned snapshots (mirrors pricing_configs shape).
-- price_book_items — editable catalog rows; price_book_id FK is nullable (live rows
--                    have no book yet; frozen rows belong to a PriceBook version).
--
-- RLS: ENABLE + FORCE + NULLIF 2-arg tenant_isolation policy on both tables,
-- matching the pattern in 0030. Idempotent (CREATE TABLE IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS price_books (
    id              SERIAL PRIMARY KEY,
    supplier        VARCHAR(100)  NOT NULL DEFAULT 'DEFAULT',
    version_number  INTEGER       NOT NULL,
    label           TEXT,
    items_snapshot  JSONB         NOT NULL DEFAULT '[]'::jsonb,
    config_hash     VARCHAR(64)   NOT NULL,
    is_active       BOOLEAN       NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    created_by      TEXT          NOT NULL,
    tenant_id       INTEGER       NOT NULL REFERENCES tenants(id) DEFAULT 1,
    CONSTRAINT uq_price_books_tenant_supplier_version
        UNIQUE (tenant_id, supplier, version_number)
);
CREATE INDEX IF NOT EXISTS ix_price_books_tenant_supplier ON price_books (tenant_id, supplier);

CREATE TABLE IF NOT EXISTS price_book_items (
    id               SERIAL PRIMARY KEY,
    price_book_id    INTEGER       REFERENCES price_books(id),
    sku              VARCHAR(100),
    name             VARCHAR(255)  NOT NULL,
    unit             VARCHAR(50),                             -- roll|bundle|box|can|sheet|piece|LF|bag|bucket|square|foot
    unit_coverage    NUMERIC(10,4),                          -- sq per unit; NULL = not a per-sq item
    unit_price       NUMERIC(12,4),                          -- NULL = not-stocked / unknown; never 0
    tax_rate         NUMERIC(6,4)  NOT NULL DEFAULT 0.07,
    waste_rate       NUMERIC(6,4)  NOT NULL DEFAULT 0.10,
    supplier         VARCHAR(100),                           -- ABC_SUPPLY|BEACON|VEREA|…
    roof_system_ids  JSONB         DEFAULT '[]'::jsonb,
    knowify_item_id  VARCHAR(100),                           -- Knowify↔item crosswalk
    item_type        VARCHAR(30),                            -- material|system|service
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    tenant_id        INTEGER       NOT NULL REFERENCES tenants(id) DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_price_book_items_tenant
    ON price_book_items (tenant_id);
CREATE INDEX IF NOT EXISTS ix_price_book_items_tenant_knowify
    ON price_book_items (tenant_id, knowify_item_id);
CREATE INDEX IF NOT EXISTS ix_price_book_items_price_book_id
    ON price_book_items (price_book_id);

-- Immutability trigger: once a price_books row is written, its snapshot fields
-- (items_snapshot, config_hash, version_number) must never change.
-- is_active and label are allowed to change (activation / rename).
-- Postgres-only; SQLite dev/test does not run this block.
CREATE OR REPLACE FUNCTION price_books_immutable_fields()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.items_snapshot IS DISTINCT FROM OLD.items_snapshot THEN
        RAISE EXCEPTION 'price_books.items_snapshot is immutable after creation';
    END IF;
    IF NEW.config_hash IS DISTINCT FROM OLD.config_hash THEN
        RAISE EXCEPTION 'price_books.config_hash is immutable after creation';
    END IF;
    IF NEW.version_number IS DISTINCT FROM OLD.version_number THEN
        RAISE EXCEPTION 'price_books.version_number is immutable after creation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_price_books_immutable ON price_books;
CREATE TRIGGER trg_price_books_immutable
    BEFORE UPDATE ON price_books
    FOR EACH ROW EXECUTE FUNCTION price_books_immutable_fields();

-- RLS: ENABLE + FORCE + NULLIF 2-arg tenant_isolation policy on both tables.
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['price_books', 'price_book_items'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I '
            'USING (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::int) '
            'WITH CHECK (tenant_id = NULLIF(current_setting(''app.tenant_id'', true), '''')::int)', t);
    END LOOP;
END $$;
