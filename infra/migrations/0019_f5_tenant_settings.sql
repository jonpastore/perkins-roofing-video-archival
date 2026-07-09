-- Migration 0019: F5 tenant settings seed + offboard log
-- PROD APPLY: requires Jon's explicit permission + fresh ADC.
-- Run: .venv/bin/python scripts/apply_migrations_connector.py
--
-- Ownership note: tenant_offboard_log was documented as F4-owned (TRD-F4 §8 /
-- TRD-F5 §11 note), but migration 0018 did NOT create it — 0018's GCIP IDENTITY
-- section created tenant_gcip_map, tenant_default_admins, platform_admins, and
-- platform_audit_log only. This migration creates tenant_offboard_log with
-- CREATE TABLE IF NOT EXISTS (idempotent). Ownership reconciliation needed:
-- TRD-F4 §8 should be updated to reflect that 0019 is the actual creator.
--
-- render_spec NOTE: TRD-F5 step 9 called for a render_spec COLUMN on mini_series,
-- but the #320 carry-over (commit c0a12c9) already stores render_spec inside the
-- existing parts_json JSON column (envelope form, read via core.render_spec
-- get_render_spec/set_render_spec — the live path in jobs/render_job.py). Adding
-- a column would create a second, dead storage location. So NO render_spec column
-- is added here; the envelope is the single source of truth.

-- ── 1. tenant_offboard_log table ─────────────────────────────────────────────
-- Platform-level table: no tenant_id FK, no RLS.
-- F4 is the documented owner but failed to ship it in 0018. Created here
-- idempotently so it exists before offboard_tenant() is called.
-- OWNERSHIP GAP: update TRD-F4 §8 to acknowledge 0019 as the actual creator.
CREATE TABLE IF NOT EXISTS tenant_offboard_log (
    id            SERIAL PRIMARY KEY,
    tenant_id     INTEGER      NOT NULL,   -- not FK; tenant row may be deleted
    offboarded_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    offboarded_by TEXT         NOT NULL,   -- platform_admin email
    gcs_prefix    TEXT         NOT NULL,   -- "tenants/{id}/" — for audit
    row_counts    JSONB        NOT NULL,   -- {"videos": 832, "chunks": 12400, ...}
    status        TEXT         NOT NULL DEFAULT 'pending'  -- pending | complete | failed
);

CREATE INDEX IF NOT EXISTS ix_tenant_offboard_log_tenant_id
    ON tenant_offboard_log (tenant_id);

-- ── 2. Seed tenants.settings for tenant 1 with F5 brand defaults ─────────────
-- Idempotent: jsonb_build_object merges; existing keys (F3 deposit etc.) are
-- preserved because we use || (jsonb concat) rather than wholesale replacement.
-- Only sets the brand sub-object if the 'brand' key is currently absent or null.
UPDATE tenants
SET settings = settings || jsonb_build_object(
    'brand', jsonb_build_object(
        'logo_gcs_uri',         NULL,
        'primary_color',        '#1a3c5e',
        'accent_color',         '#f4a226',
        'font_heading',         'Montserrat',
        'font_body',            'Open Sans',
        'intro_gcs_uri',        NULL,
        'outro_gcs_uri',        NULL,
        'voice_sample_gcs_uri', NULL
    )
)
WHERE id = 1
  AND (settings -> 'brand') IS NULL;

-- Seed metering_caps for tenant 1 if absent (unlimited by default).
UPDATE tenants
SET settings = settings || jsonb_build_object(
    'metering_caps', jsonb_build_object(
        'llm_tokens_per_month',     NULL,
        'stt_minutes_per_month',    NULL,
        'render_minutes_per_month', NULL
    )
)
WHERE id = 1
  AND (settings -> 'metering_caps') IS NULL;

-- ── Down path (reference — not executed by runner) ───────────────────────────
-- DROP TABLE IF EXISTS tenant_offboard_log;
-- (settings seed is non-destructive; no down step needed for the UPDATE)
