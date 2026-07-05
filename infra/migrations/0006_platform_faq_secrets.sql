-- Wave: platform config, persistent FAQ, and secret-audit tables.
-- Idempotent: safe to re-run. Applied by scripts/apply_migrations.sh (git -> apply, R3).
-- These were previously created ad-hoc; this file is the source of truth for the schema.

CREATE TABLE IF NOT EXISTS platform_config (
    key        VARCHAR NOT NULL,
    value      VARCHAR,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    updated_by VARCHAR,
    PRIMARY KEY (key)
);
-- Upgrade path if the table pre-existed without the audit columns.
ALTER TABLE platform_config ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE;
ALTER TABLE platform_config ADD COLUMN IF NOT EXISTS updated_by VARCHAR;

CREATE TABLE IF NOT EXISTS faq_entries (
    id             SERIAL NOT NULL,
    question       TEXT NOT NULL,
    answer         TEXT,
    source_kind    VARCHAR NOT NULL,
    source_node_id INTEGER NOT NULL,
    video_id       VARCHAR NOT NULL,
    start          FLOAT NOT NULL,
    status         VARCHAR NOT NULL,
    created_at     TIMESTAMP WITHOUT TIME ZONE,
    PRIMARY KEY (id),
    UNIQUE (source_node_id)
);

CREATE TABLE IF NOT EXISTS secret_audit (
    key        VARCHAR NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE,
    updated_by VARCHAR,
    PRIMARY KEY (key)
);
