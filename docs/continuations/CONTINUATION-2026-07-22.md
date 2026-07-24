# CONTINUATION — 2026-07-22

Massive session. Prod was deployed twice; 61 articles went live on the new staging; the LLM
routing strategy pivoted to Cloudflare; o365 mail MCP shipped. Read this + `prompt.txt` to resume.

## Deployed state
- **Prod image: `d1e25b5`** (was `41472dc` — ~27 commits shipped). API + all Cloud Run jobs updated.
  `prod_smoke.py` PASS. Prod stays **`LLM_BACKEND=vertex`** (deploy.sh hardcodes it; the Cloudflare
  adapter ships DORMANT until the deliberate flip).
- **HEAD == origin/main == `d1e25b5`** (a 2nd deploy of the WP_URL no-env-fallback change was in
  flight at write time — if `deploy2.log` shows "== Done ==", the deployed image is HEAD).

## What shipped today
- **Full article pipeline** live (FAQ+Video-only schema, numeric grounding, dense answer-first, no /blog/).
- **Estimator**: repair-quote (time-based, Tim's $1185/$1435 labor rates) + **gutter downspout split** ($10.50/LF 4x5, config-driven, Tim to confirm bundling).
- **SEO submission** (IndexNow + Google Indexing API) — **OFF by default**; needs creds to enable.
- **internal_links.py** — real perkinsroofing.net service slugs (verified 200; was 2 hard 404s + 4 redirects).
- **article_job old path** now emits FAQ+Video-only JSON-LD (was a latent full-graph-schema bug).
- **CloudflareLLM adapter** (`adapters/llm.py`) — prod-capable, live-verified; `LLM_BACKEND=cloudflare` allowed in prod. DORMANT.
- **WP_URL resolver** (`adapters.wordpress.resolved_wp_url`): admin-config (`PlatformConfig WP_URL`) is the SINGLE source of truth, **NO .env fallback** (Jon: .env is only a secure key transport into the vault). Routed the publisher + all UI/gen link builders through it.
- **o365 mail MCP** wired (draft/send to Jon@DeGenito.ai Outlook via the shared cerberus `o365-api`); jarvis git reconciled. See memory [[o365-mail-mcp-shipped-2026-07-21]].

## Content state
- **61 articles LIVE + validated on the new staging** `https://1228404.us6.myftpupload.com` (30 new
  + 31 refreshed): all pass FAQ+Video schema, no /blog/, YouTube footer, corrected 200 service links.
  Published as WP `publish`; DB `status=published` with 1228404 wp_post_ids. `perkins-jsonld` plugin
  installed on the clone. Ready for Wendy's review.
- Article generation: local gpt-oss was 1-time PRIMING; **prod generation → Cloudflare llama** going forward.

## BINDING model routing (Jon 2026-07-22) — see `docs/PRODUCTION_CUTOVER_PLAN.md` + memory [[prod-model-routing-and-cf-flip]]
- **All creative/content (articles, llms.txt, portfolio write-ups, scope-of-work rewrite) → Cloudflare free-tier llama**, validated by **Vertex/Gemini**.
- **App code (toggles, estimator, connectors) → sonnet or qwen-coder 3.6, reviewed by opus 4.8.**
- No dependence on the local cerberus fleet in prod.

## Key facts / gotchas
- **Cloud SQL proxy**: `/tmp/cloud-sql-proxy <conn> --port 5432` (instance
  `video-archival-and-content-gen:us-central1:video-archival-and-content-gen-pg`). Started this
  session; RESTART it next session (proxy on 127.0.0.1:5432 for DB access). Query with raw psycopg +
  `SET app.tenant_id='1'`, or `_stamped_session(1)`.
- **CF Workers-AI**: token in Secret Manager `cloudflare-api-token` (now has Workers AI:Edit),
  account `3303058f686721d6877d6d1e8b8a448c` (Tim's). Verified working (llama-3.3-70b). The **prod
  flip** = inject `CLOUDFLARE_API_TOKEN` into Cloud Run + set `LLM_BACKEND=cloudflare` (terraform).
- **WP staging** `1228404` app pw vaulted (`wordpress-app-password` v3); `WP_USER=jon`; auth verified
  via `adapters.wordpress` (handles GoDaddy redirect/header quirk). Admin `PlatformConfig WP_URL=1228404`.
- Prod backend stays vertex; SEO submission off; email test-mode.

## Remaining queue (build to the routing policy above)
1. **llms.txt generator** (AIO — pull-based; robots.txt allowlist + llms.txt manifest; do NOT touch Rank Math's sitemap/robots). CF-gen content.
2. **Repair/re-roof toggle + scope-of-work field** — app code (sonnet/qwen). The scope-of-work "template + AI rewrite" runs on **CF llama**. Design brief: `scratchpad/repair-sow-design.md`. NOTE: repair card can't create a proposal yet; UI has no toggle.
3. **Portfolio automation** (Wendy) — her 30-field Google Sheet → **Avada Portfolio** (categories Commercial/Residential/Construction, tags=location, skills=roof type). Semi-auto: CF write-ups from CompanyCam/proposal/YouTube, permissions human-gated. Doc + Sheet IDs in the O365 thread.
4. **CF prod flip** (terraform: inject token + `LLM_BACKEND=cloudflare`) — see cutover plan.
5. **AIO plan** details: `scratchpad/aio-and-cf-plan.md`.

## Blocked on others
- **Wendy Biksen** (wendy@webpowermarketing.com, WP consultant): staging↔prod parity (breadcrumbs enabled on prod 7/16, not staging), prod Rank Math config (no dup FAQ schema), review the 61, provide project data.
- **Tim**: 6 pricing items (per-branch OH, gutter hangers, downspout $10.50, Verea field-tile, FBC low-slope deltas, T&C) — $1185/$1435 labor CONFIRMED.
- **Jon**: CF prod flip; generate a PROD WP app password at cutover; SEO submission creds (IndexNow key + Google Indexing SA).

## Operate
- Deploy: `set -a; source .env; set +a; export GOOGLE_APPLICATION_CREDENTIALS=/home/jon/.config/gcloud/perkins-deploy-sa.json; bash scripts/deploy.sh` (CLEAN tree; hardcodes vertex + prod).
- SPA: `cd web && npm run build && firebase deploy --only hosting:app`.
- Prod smoke: `.venv/bin/python scripts/prod_smoke.py`.
- Cutover checklist + steps: **`docs/PRODUCTION_CUTOVER_PLAN.md`**.

---
Archive directive applied: moved `CONTINUATION-2026-07-20-pm.md` → `docs/continuations/` (keep latest 3 at top level).
