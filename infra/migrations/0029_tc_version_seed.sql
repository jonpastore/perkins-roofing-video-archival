-- 0029: Seed DRAFT T&C version for Perkins Roofing (tenant_id=1)
-- PENDING TIM SIGN-OFF — do not promote to approved until reviewed.
INSERT INTO tc_versions (tenant_id, version_tag, content_gcs, effective_at, created_at)
SELECT 1, 'v0.1-DRAFT', NULL, NOW(), NOW()
WHERE NOT EXISTS (
    SELECT 1 FROM tc_versions WHERE tenant_id = 1 AND version_tag = 'v0.1-DRAFT'
);
