# IaC drift — residual after the 2026-07-18 apply

`scripts/drift_check.sh` will still report drift. This is the accurate residual after applying
what was safely applicable. **Ansible: clean (changed=0).** Terraform below.

## Applied + verified (live, all sites 200)
- `google_cloud_run_v2_service.gotenberg` — port drift-fixed **8080 → 3000** (Gotenberg's default;
  Ready). `gotenberg_jobs_invoker` IAM binding created.
- `cloudflare_ruleset.waf_block_internal` — created (via TF).
- **SSL → strict, min_tls 1.2, always_use_https on** — applied **via the Cloudflare API, not TF**
  (see zone_settings below). Verified: perkinsroofing.net + app + API stayed 200 (origins have
  valid certs, so strict is safe).

## Still drifting — each blocked on a distinct thing (none demo-critical)
| resource | blocker | to resolve |
|---|---|---|
| `cloudflare_ruleset.waf_rate_limits` | zone is **Cloudflare Free plan** — caps rate limiting to `period=10` + 1 rule; the IaC uses `period=60` × 3 rules (paid-plan design). Also Free requires `cf.colo.id` in `characteristics`. | Upgrade to Pro/Business, OR rewrite the rules to Free limits (degrades protection). |
| `cloudflare_ruleset.origin_routing` | the CF API token lacks **Transform Rules (Config Rules) : Edit** (has WAF + Settings now). "request is not authorized" on the `http_request_transform` phase. | Add that permission to the token (`cloudflare-api-token` secret / 1Password "Perkins Roofing - CloudFlare API Credentials"). Note: app uses the direct `run.app` API URL today, so this path is unused. |
| `cloudflare_zone_settings_override` | **v4 provider bug** — reads the read-only `true_client_ip_header` and errors. Settings were applied via API instead, so TF still shows it as "to create". | Upgrade the cloudflare provider to v5 (`cloudflare_zone_setting` singular) — breaking, do in a dedicated window. |
| `google_cloud_run_domain_mapping.api` (app.perkinsroofing.net) | **domain ownership not verified** for the project. A failed/inert mapping object exists; app.perkinsroofing.net still serves via Firebase/Cloudflare (200). | Verify perkinsroofing.net ownership in Google Webmaster Central (or grant the SA domain admin), then re-apply. |

## Token scope (as of 2026-07-18)
The `cloudflare-api-token` secret == the 1Password "Perkins Roofing - CloudFlare API Credentials"
item (same token). After Jon's edits it now has DNS + WAF + Zone-Settings edit on perkinsroofing.net
(zone `730729a1b3ac1d718727a0fccc07933b`), but **not** Transform/Config Rules edit. Inject via
`TF_VAR_cloudflare_api_token=$(gcloud secrets versions access latest --secret=cloudflare-api-token)`.

## Note on the manual SSL apply
Setting SSL via the API diverges from TF intent (R3). It was the only path (v4 provider can't apply
`zone_settings_override`, and Jon explicitly wanted strict SSL). Reconcile when the provider is
upgraded to v5. None of the above is caused by the cut-calculator work.

## Update 2026-07-18 (pm) — token verified, check fixed, drift de-risked
- **Root cause of the "plan ERROR (creds)":** `drift_check.sh` ran `terraform plan` without injecting
  `TF_VAR_cloudflare_api_token`, so the CF provider used the placeholder and errored on the zone read —
  masking ALL terraform drift as a creds failure. **Fixed:** the script now self-injects the token from
  Secret Manager. The token itself is valid/active (reads zone/settings/rulesets; plan = Free Website).
- **De-risked:** `cloudflare_zone_settings_override` and `google_cloud_run_domain_mapping.api` were
  tainted → **replace**; a blind apply would have destroyed live SSL + the api domain mapping and failed
  to recreate. `terraform untaint` (no cloud change) cleared the replaces. `zone_settings_override` then
  applied **in-place** cleanly (the v4 failure was the replace, not in-place). Also applied gotenberg
  scaling + created the 2 `companycam-*` secret containers. **0 destroyed** throughout.
- **Gated off (money-free, safe):** `waf_rate_limits` → `var.cloudflare_rate_limiting_enabled`
  (default false; flip after a paid plan), `origin_routing` → `var.cloudflare_origin_routing_enabled`
  (default false; unused). Plan is now **0 add / 0 destroy / 2 in-place**.
- **Residual (benign; each needs a decision, none block a deploy):** `zone_settings_override`
  (perpetual v4 `true_client_ip_header` diff — needs the v5 provider migration; an ignore_changes
  would stop TF-tracking SSL so it's NOT applied), `gotenberg` (perpetual cosmetic `0`↔`null` scaling
  diff — nested-path ignore_changes unsupported, documented benign in gotenberg.tf), `domain_mapping.api`
  (needs Google domain-ownership verification).
- **v4→v5 provider migration:** free-tier compatible, but it's a resource-type-change migration across
  LIVE email DNS (MX/SPF/DKIM/DMARC) whose only drift benefit is the cosmetic zone_settings diff — so
  best practice is a planned, zero-change-plan-verified cutover via the official tf-migrate codemod, NOT
  a rushed in-session apply. Deferred to a controlled change.
