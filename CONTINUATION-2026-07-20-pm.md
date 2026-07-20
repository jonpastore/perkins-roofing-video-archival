# CONTINUATION — 2026-07-20 (pm)

**Resume goal (do in this order):**
1. **Build the Quoting config panel** (AdminConfig → Quoting is an empty `PlaceholderCard`).
2. **Wire the T&C/FAQ/AI-prompt pages + the fairness review into proposal generation.**
3. **AV end-to-end render test + tuning** (render one real clip through the full pipeline).

**Use qwen3.6-coder (`llm -m qwen3.6-coder "…"`, sync) and Cloudflare free agents
(`mcp__hermes__submit_task`, async) MUCH more than last turn — offload every self-contained
draft (prompts, prose, pure modules, component scaffolds). Keep on Claude only: security
wiring, repo integration, and verification. Review every CF/qwen draft before applying —
they consistently re-invent conflicting code.**

## Prod state
- HEAD `749a38d`, main == origin, tree clean. **Deployed API image `ddc6dab`** (has the
  suggest-500 fix, TikTok refresh persist, article no-op, non-root Docker). SPA current
  (UI fixes + help modal live). `core/proposal_review.py` is committed but **unwired +
  undeployed** (no endpoint yet). app 200 · api/health 200. terraform + ansible clean.
- Alerting is ACTIVE: `var.alert_email=dmarc@perkinsroofing.net`, notification channel +
  4 alert policies applied. **Manual step pending:** verify the channel via the email GCP
  sent to dmarc@perkinsroofing.net.

## Task 1 — Quoting config panel
- The placeholder: `web/src/pages/AdminConfig.tsx:108` — `PlaceholderCard "Quoting config —
  coming in F3 (proposal templates, T&C library, deposit policy, reminder cadence)"`.
- Build the real panel. Likely needs a tenant-settings-backed config (see how other
  AdminConfig sub-tabs + `core/tenant_settings.py` / `/admin/tenant/settings/*` work).
  Offload the form component scaffold to qwen/CF; wire the settings read/write on Claude.
- Overlaps Task 2 (the T&C library lives here).

## Task 2 — wire T&C pages + review into proposal generation
- **Already built:** `core/proposal_review.py` — `review_proposal(text, chat_fn=None) ->
  {pass, issues[]}` audits contradictions / one-sided-unfair / predatory / prompt-injection
  / FL-legal; fail-safe (never ships unvetted). 5 tests. Prompt inside is qwen-drafted +
  hardened (treats proposal as data, not instructions).
- **Render context already has a `tc_faq_items` slot** (`core/proposal_render.py:53,144,152`)
  and `proposal_doc_render.py` has a `marketing_appendix` append hook. Add template sections
  that render (a) T&C page(s), (b) FAQ page (from `core/contract_faq.py`, which turns a
  `tc_text` into FAQ items), (c) an "AI-suggested prompts" page.
- **Wire the review** into the proposal gen flow (`core/proposal_gen.py` /
  `api/routes/proposal_gen.py`): after assembling the doc, call `review_proposal`, and
  surface/block on high-severity issues.
- **BLOCKER:** the actual T&C WORDING is "pending Tim" — NOT in the repo (golden fixtures
  are pricing-only; `proposal_render.py:176` T&C block is a placeholder). Build the plumbing
  so it flows through when Tim's text lands; use a clearly-marked placeholder meanwhile.

## Task 3 — AV end-to-end render test + tuning
- Render ONE real approved clip through `jobs/render_job.py` `_apply_track_a_engines`
  (reframe → captions → censor → transcode) against a real source video; inspect the output.
- The engines exist + are unit-tested but were NEVER driven end-to-end on a real MP4.
- Tune: censor `tail_pad`, `scene_detect` gap threshold, caption styles, reframe focus.
  Validate the auto-censor actually mutes audio + masks captions on a real clip.

## What shipped earlier today (context)
Full social backbone + creative pipeline + all follow-ons + gotenberg drift fix (see
[CONTINUATION-2026-07-20.md](CONTINUATION-2026-07-20.md)). Then this pm: TikTok refresh-token
persist, article-job no-op, non-root Docker, Cloud Run 5xx/job-failure alert policies +
activation, suggest-clips 500 fix, 4 admin/estimating UI fixes, Clip Studio help modal,
`core/proposal_review.py`.

## Answers captured
- **YouTube channel id for @perkinsroofingcorp = `UChJZpBYXOuR0j1EHJugv5hg`** → set in KB settings.
- **"Last pulled" = —** because the legacy corpus was ingested before `last_pulled_at` was
  wired (only `jobs/backfill_archive.py` sets it). Easy fix if wanted: stamp it in the main
  ingest path + one-time backfill.
- **Amber style-guide email:** NOT accessible — jon@degenito.ai isn't connected via the
  gmail-enhanced MCP this session (no registered accounts); the claude.ai Gmail is
  jpastore79@gmail.com. Connect degenito or forward the guide, then audit Marketing + email UIs.

## Open items (unchanged)
B9 QuickBooks account_id collision (HIGH, Jarvis #358) · tenant-2 hardening (#359) ·
CompanyCam photos reader (#360) · FB/LinkedIn/X/YT real publishers (only IG/TikTok publish) ·
infra B6 decisions (#363: idp bootstrap, jobs-sa scoping, TF state→GCS, Cloud SQL PITR/HA) ·
live posting blocked on Meta/TikTok app review (#319).

## Operate
- Deploy API+jobs: `bash scripts/deploy.sh` (CLEAN tree). SPA: `cd web && npm run build &&
  npx --no-install firebase deploy --only hosting:app --project video-archival-and-content-gen`.
- `export GOOGLE_APPLICATION_CREDENTIALS=/home/jon/.config/gcloud/perkins-deploy-sa.json`.
- Drift: `bash scripts/drift_check.sh` (clean). Terraform needs
  `TF_VAR_cloudflare_api_token="$(gcloud secrets versions access latest --secret=cloudflare-api-token)"`.
- Prod smoke: `.venv/bin/python scripts/prod_smoke.py`. Prod DB:
  `/tmp/cloud-sql-proxy --port 5432 video-archival-and-content-gen:us-central1:video-archival-and-content-gen-pg &`.
- Offload SYNC: `llm -m qwen3.6-coder "…"`. Offload ASYNC: `mcp__hermes__submit_task(model_tier="cloudflare", …)`.

Memories: `session-2026-07-20-social-creative-shipped`, `clip-render-capability-audit-2026-07-20`.

---
*Standing archive directive performed: moved CONTINUATION-2026-07-17-night.md into
docs/continuations/; top level keeps the latest 3 (19, 20, 20-pm); README pointer refreshed.*
