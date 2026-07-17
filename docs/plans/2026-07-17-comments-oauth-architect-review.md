# Architect review — comments/OAuth plan (2026-07-17) — consensus artifact

Verdict summary: direction sound; mass over-built. Blockers: H1, H2; H3 must be
tightened before any callback code. Steelman: split alarm by layer (Cloud
Monitoring = job liveness; in-app = only the business status the UI renders,
defer the transition/dedup state machine); extract the comment Protocol at Meta
rather than freezing it against one real adapter now.

HIGH
- H1: Phase-2 migration names uq_comment_drafts_comment_id — exists only in the
  ORM (app/models.py:432). Prod constraint is the inline UNIQUE(comment_id) from
  infra/migrations/0007_comment_drafts.sql:16 → auto-named
  comment_drafts_comment_id_key. DROP by that name (with IF EXISTS +
  information_schema verification) or the migration fails.
- H2: E1 safety gate is NOT wired on the live reply path —
  api/routes/comments.py post_reply_to_youtube → adapters/youtube_comments.py
  post_reply, no run_gate call (distribute_job.py:173 and avatar_job.py:111 have
  it). Centralize run_gate(text,"social") in the provider post_reply wrapper so
  all future platforms are covered by construction; fix YouTube NOW.
- H3: OAuth callback is an UNAUTHENTICATED browser GET in a bearer-token app —
  no caller claims exist at the callback; the signed state is the ENTIRE tenant
  binding. Mandatory: HMAC key in Secret Manager (+rotation), SINGLE-USE nonce
  persisted and burned on callback (replay defense), exact-match redirect_uri
  allowlist + {platform} validated against a fixed registry. /oauth/start must
  use require_role_db (tenant-scoped), not legacy require_role (defaults
  tenant_id=1, api/auth.py:158).

MEDIUM
- M1: unique must be (tenant_id, platform, comment_id) per uq_*_tenant_*
  convention; the global index + RLS-scoped re-SELECT in crawl_comments.py:144
  silently drops cross-tenant colliding comments.
- M2: probes must be LIVENESS checks, not refresh attempts — refresh tokens are
  single-use (knowify precedent, core/knowify/tokens.py:11); a 30-min force
  refresh rotates 48x/day and can kill a working cred. Refresh only on
  observed-dead, under the advisory-lock pattern.
- M3: probe job runs under core.tenant_loop.for_each_tenant with the tenant GUC;
  /internal/integration-health uses _require_internal + scheduler OIDC +
  X-Internal-Secret (infra/main.tf:622 pattern). Unstated in plan.

Principles flagged: P1 violated by shipping code (H2); P2 inconsistent (YouTube
OAuth env creds probed but never migrated); P5 contradicts pre-mortem #1 —
resolve by severity: hard 401/invalid_grant alarms on FIRST occurrence, only
transient 5xx needs N=3.

LOW: L1 next migrations are 0039/0040 (latest applied 0038). L2 shared-cred
integrations (Knowify/Resend/WP) need platform-level (nullable-tenant) status
rows, not N per-tenant duplicates. L3 phasing (health before comments) is
verified-defensible; keep it.
