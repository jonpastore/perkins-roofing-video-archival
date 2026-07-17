# Known Gaps & Follow-ups (as of 2026-07-17)

Production-readiness gates evaluated against prod: **READY=True, 0 blockers, 4 warnings.**
`rls_security`, `dmarc`, `secrets_present` = ok. Warnings below are expected/intentional.

## Needs a human decision (go-live / R4)

### Terraform drift — 7 resources
- **What**: `cloudflare_ruleset.origin_routing` / `waf_block_internal` / `waf_rate_limits`,
  `cloudflare_zone_settings_override.perkinsroofing`, `google_cloud_run_domain_mapping.api`,
  `google_cloud_run_v2_service_iam_member.gotenberg_jobs_invoker` (creates) + `gotenberg`
  service (in-place update).
- **Impact**: `drift_check` (R4) fails; a blind `terraform apply` would change prod
  networking / WAF / custom-domain. Pre-existing — NOT from this session's work.
- **Next**: Jon reviews the Cloudflare + custom-domain intent, then apply deliberately
  (or codify the real desired state).

## Should-fix

### Migration replay script (DR path)
- **What**: `scripts/apply_migrations.sh`'s naive `;`-splitter can't handle complex
  statements (enum lists / multi-value CHECK) deeper in the set. Inline-comment stripping
  was fixed (a13b1a8); the splitter limitation remains.
- **Impact**: A full DR rebuild from migrations fails partway. Incremental apply (what we
  use — apply the newest migration directly) is unaffected.
- **Next**: Replace the splitter with `sqlparse` statement-splitting, or shell to `psql -f`.

### Pexels API key — placeholder only
- **What**: `pexels-api-key` secret has only the placeholder version.
- **Impact**: Clip Studio b-roll won't function until a real key is added.
- **Next**: `printf '<key>' | gcloud secrets versions add pexels-api-key --data-file=-`.

### deploy-sa is owner-scoped
- **What**: `perkins-deploy-sa` holds `roles/owner` (Jon chose "fast" over least-privilege).
- **Impact**: Broad blast radius if the key leaks.
- **Next**: (optional hardening) scope to the specific roles deploy/terraform need
  (secretmanager.admin, run.admin, cloudscheduler.admin, monitoring.editor, cloudsql.client,
  artifactregistry.writer, cloudbuild.builds.editor) and drop owner.

## Documented / deferred

### OAuth self-service capture UI — deployed but dark
- **What**: `/connections` + `/oauth/{platform}/start|callback` routes are LIVE but return
  503 (no `OAUTH_STATE_HMAC_KEY` value, no `OAUTH_REDIRECT_BASE`, no `Connections.tsx` page).
- **Impact**: None (graceful). Self-service reconnect is off.
- **Next**: Pairs with #319 — when the social platforms are connected: add the HMAC key
  value + redirect base to deploy.sh, register the `/oauth/{platform}/callback` redirect URIs
  in each provider app, and build `web/src/pages/Connections.tsx`.

### Knowify integration — placeholder token
- **What**: Token blob is a placeholder (RFC 8707 OAuth outage); the health alarm shows
  `knowify` = unconfigured (correctly, not "broken").
- **Next**: Await Knowify support on the server-side RFC 8707 500. MCP data path still works.

### Multi-platform comment adapters — Phase 3
- **What**: `CommentProvider` Protocol + Meta/TikTok/LinkedIn/X comment adapters not built
  (Phase 2 landed the data model + platform column only).
- **Next**: Phase 3, gated on #319 app-review credentials. Add comment scopes to the same
  #319 submissions (see docs/plans/2026-07-17-social-app-registrations.md).

### Email in test mode
- **What**: `EMAIL_SEND_MODE=test` — outbound email restricted to the allowlist.
- **Impact**: Real recipients don't receive mail (intentional pre-launch). Admin alerts to
  @perkinsroofing.net/@degenito.ai DO go through (allowlisted).
- **Next**: Flip to live once a verified sending domain is ready for real customer email.
