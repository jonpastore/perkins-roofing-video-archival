-- Migration 0033: Knowify contacts/properties backfill support.
-- Adds a tenant-scoped Knowify contact crosswalk so Contacts imported via MCP are
-- idempotent across hourly syncs and manual backfills.

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS knowify_contact_id VARCHAR(100);

CREATE INDEX IF NOT EXISTS ix_contacts_tenant_knowify
    ON contacts (tenant_id, knowify_contact_id)
    WHERE knowify_contact_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_contacts_tenant_knowify
    ON contacts (tenant_id, knowify_contact_id)
    WHERE knowify_contact_id IS NOT NULL;
