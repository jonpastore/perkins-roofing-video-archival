-- 0027: HOTFIX — re-scope seeded frontend origins to platform-wide (tenant_id NULL).
--
-- 0026 seeded the four Perkins frontend origins as tenant_id=1. But the tenant/host/
-- origin alignment rule only honors tenant-scoped origins when the request's Host
-- itself resolves to that tenant via a cors_origins row. In prod the API serves on a
-- shared Cloud Run host (api-*.run.app) that is NOT a registered origin, so
-- host_tenant=None and tenant-scoped origins are denied — the fail-closed default —
-- which blocked the live SPA (no ACAO for app.perkinsroofing.net / the Firebase
-- origins) from 0026-deploy until this fix.
--
-- Platform-wide scoping restores the exact pre-W0 semantics (static allowlist, no
-- tenant binding). Tenant re-scoping becomes meaningful in Ez-Bids W2 when tenant
-- hosts are onboarded into cors_origins; W2 MUST re-scope these rows then.

UPDATE cors_origins
   SET tenant_id = NULL
 WHERE origin IN (
    'https://video-archival-and-content-gen.web.app',
    'https://video-archival-and-content-gen.firebaseapp.com',
    'https://perkins.degenito.ai',
    'https://app.perkinsroofing.net'
 );
