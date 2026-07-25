# Perkins Roofing — Production Cutover Plan

Owner: Jon (DeGenito). Last updated 2026-07-22. This is the source-of-truth checklist for taking
the article/content platform from staging (`https://1228404.us6.myftpupload.com`) to production
(`perkinsroofing.net`), including the LLM backend flip.

## 1. Model routing policy (Jon, 2026-07-22) — BINDING

| Work | Generator | Validator / Reviewer |
|---|---|---|
| **Articles & all creative/writing** | **Cloudflare free-tier llama** (`LLM_BACKEND=cloudflare`, `@cf/meta/llama-3.3-70b-instruct-fp8-fast`) | **Vertex / Gemini on GCP** (explicit `VertexLLM` in the two-model split) |
| **`llms.txt` content** | CF llama | Vertex |
| **Project portfolio write-ups** | CF llama | Vertex |
| **Scope-of-work AI rewrite** (repair/re-roof UI: template + user prompt → rewrite) | **CF llama** | user reviews/edits on the UI |
| **App code** (repair/re-roof toggle, estimator, connectors, etc.) | built by **sonnet or qwen-coder 3.6** | reviewed/verified by **opus 4.8** |

- **Local gpt-oss on cerberus was 1-time priming only.** Prod must NOT depend on the local fleet
  (dev-only, unreachable from Cloud Run). All ongoing generation runs on CF free tier.
- Cost note: CF Workers-AI free tier has a daily neuron allowance; sustained thousands-of-articles
  generation may incur some cost — accepted trade for zero local dependence.

## 2. The production LLM flip (vertex → cloudflare)

- **Current prod:** `LLM_BACKEND=vertex`.
- **Target prod:** `LLM_BACKEND=cloudflare` — CF llama drafts, Vertex validates + embeds.
- **Adapter:** `adapters.llm.CloudflareLLM` (committed `43ec394`, live-verified). The prod fail-fast
  in `app/config.py` now allows `LLM_BACKEND ∈ {vertex, cloudflare}`; `EMBED_BACKEND` MUST stay
  `vertex` (the pgvector index is 3072-dim Vertex-embedded — grounding breaks otherwise).
- **To activate (terraform + deploy):**
  1. Inject `CLOUDFLARE_API_TOKEN` into the Cloud Run **api** + **jobs** services from Secret
     Manager `cloudflare-api-token` (env-from-secret in `infra/main.tf`).
  2. Set `LLM_BACKEND=cloudflare` and `CLOUDFLARE_ACCOUNT_ID=3303058f686721d6877d6d1e8b8a448c`
     (Tim's CF account) in the Cloud Run env. `CLOUDFLARE_MODEL` optional (defaults to 70B).
  3. `terraform apply` (infra/) + `bash scripts/deploy.sh` (clean tree).
  4. Smoke: run one article generation on prod; confirm CF drafts + Vertex validates.
- **Rollback:** set `LLM_BACKEND=vertex` and redeploy — the adapter change is additive, vertex
  path is untouched.

## 3. Pre-cutover checklist (all ✅ before going live)

- [ ] **Staging↔prod WordPress parity** — breadcrumbs were enabled on prod 7/16 but not staging;
      anything generated against staging must match prod. (Owner: Wendy)
- [ ] **Wendy reviews the 61 staging articles** + confirms process + shares her adherence criteria.
- [ ] **PROD WP Application Password** generated + vaulted (currently only the staging app pw is
      in `wordpress-app-password`). (Owner: Jon)
- [ ] **`perkins-jsonld` mu-plugin installed + active on PRODUCTION** (installed on staging; prod
      needs it or JSON-LD postmeta is silently dropped).
- [ ] **Rank Math on prod**: confirm its FAQ/schema output does NOT duplicate our FAQ+Video nodes.
      (Owner: Wendy)
- [ ] **Permalinks = "Post name" on prod** (top-level no-`/blog/` URLs + REST routes).
- [x] ~~**CF token injected into Cloud Run + `LLM_BACKEND=cloudflare`**~~ — SUPERSEDED 2026-07-23:
      `LLM_BACKEND=vertex` was chosen instead (CF free tier walls at ~1-2 articles/day and a
      24k-ctx ceiling; Vertex measured at ~$30-60 per 3k articles). No CF token needed.
- [ ] **SEO submission creds** provisioned IF enabling: IndexNow key (+ key-file at site root) and
      Google Indexing API service account (Search Console owner). Toggle is OFF by default.
- [ ] `WP_AUTHOR_ID=3` (Tim Kanak) confirmed stable on prod.
- [x] `core/internal_links.py` service slugs verified 200 against live `perkinsroofing.net`
      (done 2026-07-22 — was 2 hard 404s + 4 redirects, corrected).
- [x] ~~**Deploy `main` to prod**~~ — done 2026-07-24, five deploys through
      `platform:1c3e721` (estimator repair, SEO submission, internal-links fix, article-schema
      fix, gutter downspout, scope templates, proposal redesign, geometry day model).
- [x] Tim's `$1185/$1435` labor rates confirmed — **and now seeded to prod** (all 3 branches
      carried a NULL `repair` block until 2026-07-24, so repair quotes would have failed).
- [x] **All 20 sloped pricing values verified against Tim's LIVE calculator** 2026-07-24
      (`docs/TIM_SHEET_VERIFICATION_2026-07-24.md`): base costs, overheads, profit sliding scale,
      roof cuts, height, pointing, PM incentive bands, all four fixed costs. Low-slope base costs
      are also fully priced (11/11) — the `OI-1: ALL cells null` note in the config `_meta` is
      stale.
- [ ] **Remaining Tim pricing items** — narrowed to what his own sheet does NOT answer:
      sloped-HVHZ commission rate (10% or 15%), PM-incentive matrix sign-off, sliding-scale
      boundary rule, Verea/Other field-tile costs, and the 3-5 storey / 6+ crane adders
      (**blank in his sheet too**). Gutter hangers + the $14.70 upgraded downspout and copper K
      $50/$70 are still open from his 7/17 list.
- [ ] **A published barrel-tile price** — or confirmation that barrel tile is always
      engine-priced. The single `tile` catalog entry at $1,100/sq is below barrel tile's
      $1,435/sq base cost, so `proposal_gen` now refuses it (422).

## 4. Cutover steps (ordered)

1. **Deploy** `main` → prod (clean tree). Prod stays `LLM_BACKEND=vertex` at this point.
2. **Wendy**: bring staging → prod parity; install `perkins-jsonld` on prod; generate + hand over a
   **prod** WP app password → Jon vaults it.
3. **Bulk-upload** the reviewed articles to PROD (as drafts, then scheduled).
4. **Flip to CF**: inject the CF token into Cloud Run, set `LLM_BACKEND=cloudflare`, terraform
   apply + deploy (§2). All ongoing generation now runs on CF free tier.
5. **Release cadence**: 10/day (1 per pillar) via `ScheduledContent` + the promote cron.
6. **Enable SEO submission** (IndexNow + Google Indexing) once creds are provisioned.
7. **Monitor** generation cost (CF neurons) + publish success.

## 5. Open blockers (owners)

- **Wendy**: staging↔prod parity, prod Rank Math config, review the 61 articles.
- **Jon**: deploy decision; CF token injection into Cloud Run; PROD WP app password; SEO creds.
- **Tim**: remaining pricing confirmations.
