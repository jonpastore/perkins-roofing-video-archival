-- Migration 0026: cors_origins table + seed Perkins origins
-- W0: DB-backed CORS; app-owned table, no TF attribute, runtime writes are zero-drift.
-- tenant_id NULL = platform-wide origin; non-null = tenant-scoped (added at domain onboarding W2).
-- Additive, idempotent (IF NOT EXISTS throughout).

CREATE TABLE IF NOT EXISTS cors_origins (
    id         SERIAL       PRIMARY KEY,
    origin     TEXT         NOT NULL,
    tenant_id  INTEGER      REFERENCES tenants(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cors_origins_origin UNIQUE (origin)
);

CREATE INDEX IF NOT EXISTS ix_cors_origins_tenant_id ON cors_origins (tenant_id);

-- Seed Perkins (tenant 1) origins — exact origins previously held in env CORS_ORIGINS.
-- ON CONFLICT DO NOTHING so re-running the migration is safe.
-- NOTE: http://localhost:5173 is intentionally EXCLUDED from the prod seed (MEDIUM-D):
-- a NULL-tenant localhost origin would grant credentialed ACAO to any localhost port in
-- prod. Add it manually in local dev: INSERT INTO cors_origins (origin) VALUES ('http://localhost:5173') ON CONFLICT DO NOTHING;
-- OR set CORS_DEV_ORIGINS=http://localhost:5173 and the middleware will allow it when
-- PERKINS_ENV != 'prod' (see api/middleware/cors.py _get_dev_origins()).
INSERT INTO cors_origins (origin, tenant_id) VALUES
    ('https://video-archival-and-content-gen.web.app',         1),
    ('https://video-archival-and-content-gen.firebaseapp.com', 1),
    ('https://perkins.degenito.ai',                            1),
    ('https://app.perkinsroofing.net',                         1)
ON CONFLICT DO NOTHING;

-- Ez-Bids platform origin (W0 brand — degenito.ai platform home)
INSERT INTO cors_origins (origin, tenant_id) VALUES
    ('https://ezbids.degenito.ai', NULL)
ON CONFLICT DO NOTHING;

-- MEDIUM-C: Seed tenant 1's workspace_admin_subject so the proposals accept-link reply-to
-- preserves the existing jon@perkinsroofing.net behaviour after the env var retirement.
-- Merges into the existing settings JSONB without overwriting other keys (uses ||).
-- ON CONFLICT on the tenants PK ensures idempotency.
UPDATE tenants
SET settings = COALESCE(settings, '{}'::jsonb) ||
    jsonb_build_object(
        'integrations',
        COALESCE(settings->'integrations', '{}'::jsonb) ||
        jsonb_build_object('workspace_admin_subject', 'jon@perkinsroofing.net')
    )
WHERE id = 1
  AND (settings->'integrations'->>'workspace_admin_subject') IS NULL;

-- RLS: cors_origins is a platform-level table consulted before tenant context is known;
-- it is intentionally RLS-EXEMPT (same as tenants, platform_config, etc.).
-- No ENABLE ROW LEVEL SECURITY — the middleware reads all rows then filters in-process.
--
-- IaC note: Cloud Run env vars are deployed via scripts/deploy.sh (gcloud run deploy
-- --set-env-vars), NOT via Terraform — the api resource in infra/main.tf has
-- ignore_changes = [template[0].containers[0].env] (main.tf:411). "Removed from infra"
-- means removed from scripts/deploy.sh; tfstate will retain the old values until the
-- next deploy clears them.
