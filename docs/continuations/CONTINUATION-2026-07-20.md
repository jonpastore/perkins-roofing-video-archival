# CONTINUATION — 2026-07-20

**Prod state:** API+jobs image `cb82872` (== HEAD) live; SPA current on app.perkinsroofing.net;
app 200 · api/health 200. `main` == origin/main, tree clean. **Terraform plan fully clean for
the first time** (gotenberg drift fixed); Ansible clean; `terraform apply` = 0 changes.

## What shipped this session (21 commits, 5811a8b..cb82872, all deployed)

**Social publishing backbone:**
- `core/platform_specs.py` — per-platform video spec table + `validate()` + `PLATFORM_PRESETS`.
- `POST /clips/{id}/preflight` — per-platform pass/fail; wired to ClipCard as live ✓/⚠ fit badges.
- `core/social_creds.py` — store-first (SecretManagerOAuthStore) / env-fallback resolver, wired
  into `social_job` so a connected OAuth account actually feeds the publisher (was env-only).
- Checkbox multi-post UI (Scheduling) off `GET /connections` connected platforms.
- Retired the mocked `distribute_job` + `publish_dispatch` — unified on `social_job`.
- Platform preset buttons in Clip Studio suggest (tune per target platform).

**Auto-censor (complete):** `core/censor.py` — crude denylist + tenant `safety_denylist` → merged
spans → **audio mute** (`-af volume=enable`) in the render engine AND **burned-caption masking**
(`mask_caption_words`). Both live.

**Creative-feature gaps (audit found reframe/captions/per-platform-copy already existed):**
manual focal-point slider (was hardcoded 0.5), captions-"Off" relabel, scene-cut — speech-gap
(`core/scene_detect`) + visual ffmpeg scdet (`core/scene_detect_visual`, `/clips/scenes?mode=visual`
with speech-gap fallback), platform preset buttons, preflight fit badges.

**Follow-ons (all done):** visual scene-cut; auto-schedule target respects `render_spec.platforms`
(+ "Publish to" control) not hardcoded; `core/transcode` conform primitives **wired into render**
(per-platform trimmed variants — no-op for ig/tiktok caps, activates for tight-cap platforms).

**Infra:** gotenberg perpetual `0→null` scaling drift FIXED by declaring the service-level scaling
block (min=0, manual=0) so config matches GCP state (`ignore_changes` can't suppress a block
removal). `d8cacc8`.

**Method:** pure modules CF-drafted via Hermes ($0), reviewed on Claude before applying (CF drafts
consistently re-invented conflicting modules — always review). Security (`social_creds`) + render
wiring + infra drift stayed on Claude.

## What's left

**Code-completable now (not blocked):**
- **B9 QuickBooks `account_id` collision** (HIGH, before QB live) — `SecretManagerOAuthStore._secret_name`
  ignores account_id; 4 QB subs collide to one secret. Jarvis #358.
- **Tenant-#2 hardening** — strict session events, `require_role_db` migration, `(tenant_id, branch)`
  referential integrity + create_config validation. Jarvis #359.
- **CompanyCam photos reader** (mirror is write-only) — buildable; activation waits on Tim's PAT. Jarvis #360.

**Blocked on external app review:** live IG/TikTok/FB posting (#319, ~2–4wk). Code ready + dark.

**Blocked on Tim:** CompanyCam PAT · 4 QuickBooks + Qvinci accounts · low-slope prod pricing · gutters
7″/6″ 2-story discrepancy · per-branch daily OH · GC branch pricing · YouTube owner token.

**Jon decisions:** pay for Cloudflare plan (`var.cloudflare_rate_limiting_enabled=true` → WAF rate
limiting) · migrate terraform state to a GCS backend before a 2nd operator · B10 royalty ACH (Stripe
Connect + Tim's terms, HELD).

## Operate
- Deploy API+jobs: `bash scripts/deploy.sh` (clean tree). SPA: `cd web && npm run build && npx
  --no-install firebase deploy --only hosting:app --project video-archival-and-content-gen`.
- Drift: `bash scripts/drift_check.sh` (now fully clean). IaC apply: `terraform apply` in `infra/`
  with `TF_VAR_cloudflare_api_token` + the `perkins-deploy-sa.json` SA.
- Prod smoke: `.venv/bin/python scripts/prod_smoke.py`.
- Gotcha: `render_job` auto-creates a ScheduledContent from `render_spec.platforms` at render time;
  the Scheduling checkbox edits rows afterward. Only ig/tiktok have real publishers.

Memories: `session-2026-07-20-social-creative-shipped`, `clip-render-capability-audit-2026-07-20`,
`social-connect-architecture-2026-07-19`.

---
*Standing archive directive performed: moved CONTINUATION-2026-07-17-eve.md into
docs/continuations/; top level keeps the latest 3 (17-night, 19, 20); README pointer refreshed.*
