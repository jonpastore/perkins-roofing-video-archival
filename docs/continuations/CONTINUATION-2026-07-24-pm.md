# CONTINUATION 2026-07-24 pm — articles complete + Tim email triage + estimator tiers

Resume after restart. **HEAD == `738b638`** (clean tree, pushed).
SCRATCH = `/tmp/claude-1000/-home-jon-projects-perkins-roofing-video-archival/fc25f81c-006d-444d-a7cf-26ac94fa2737/scratchpad`

## ARTICLE LIBRARY — DONE (375 articles, all compliant, on STAGING)
- 165 originals reprocessed + 210 new (70 pillars × 2 clusters, 20 metal, deduped) → **374→375**.
- **All 62 metal articles are now LIVE** on staging (flipped this session).
- **QC pass applied (commit 12966ff, scripts/relink_hub.py):** relativized 940 absolute
  perkinsroofing.net links → portable `/path` (they bounced staging reviewers to prod); repointed
  169 dead cluster→pillar links + pillar_slug to the pillar's REAL slug (non-deterministic LLM slug
  made `/slugify(pillar_kw)` 404); added pillar→cluster down-links. 373 articles rewritten,
  status-preserved. Loop now self-heals: relativize wired into `_reapply_fixable_ensures`.
- Calibrated grounding critic per iteration (0ae4607) + video-hallucination auto-heal (187b65b) +
  video↔article linkage migration 0045 (20014ba). Gate is fully deterministic.
- **RE-RUN AFTER EVERY BATCH:** `scripts/backfill_article_videos.py` (video linkage) +
  `scripts/relink_hub.py --apply` (hub links). Both idempotent.
- Remaining article polish (optional): fuzzy-backfill the ~52 keyword-mismatch video links; prod
  cutover (Jon-gated); paid 3k run (Jon-gated).

## GMAIL-ENHANCED MCP — FIXED so it works locally (was `[]` accounts)
Root causes: (1) Claude Code ignored the MCP `cwd`, so it read a relative `accounts.json` from the
wrong dir → patched `~/.claude.json` (bash `cd` + absolute ACCOUNTS_PATH; backup `.bak-gmailcwd`) —
takes effect on restart. (2) morpheus DeGenito token was expired (Apr 23, 90-day inactivity) →
copied cerberus's live token to `credentials/jon@degenito.ai/token.json`.
- **MS re-auth command:** `cd ~/gmail-enhanced-mcp && .venv/bin/python -m gmail_mcp auth --provider outlook`.
- **Why no auto-renew:** Azure refresh tokens roll on USE; unused 90 days → hard-expire. Fix =
  a keep-alive cron. ⚠️ morpheus+cerberus now share one token — pick ONE owner or they rotate stale.
- Reading mail locally: run scripts from `~/projects/gmail-enhanced-mcp` with
  `PYTHONPATH=. .venv/bin/python`, `from src.outlook_client import OutlookClient`; attachments via
  `oc._graph_get(f"/me/messages/{id}/attachments")` (needs the `/me/` prefix).

## TIM CORPUS PULLED → `~/perkins-corpus/` (durable; /tmp was ephemeral)
- `roofr-attachments/` — 37 RoofR measurement PDFs (30 residential + Evergrene/Miramar commercial)
  + 3 OH calculators + commercial report zip. `pricing/` — Material Prices + Lumber Schedule.
  `golden-proposals/` — golden-address measurement PDFs. `branding/` — DeGenito logo (NOT a style
  guide). `tim_emails_manifest.json` — all 23 Tim emails last 8 days. README.md documents it.
- 8 full golden proposal packages (proposal+invoice PDFs) are in July 10-11 emails (outside 8-day
  pull) — re-fetch if needed.

## TIM'S OUTSTANDING ITEMS — status
1. **RoofR "Time Learning" estimator overhead** — DATA PULLED + ANALYZED → `docs/ROOFR_OVERHEAD_TIERS.md`.
   Backed the tiers out of his 30 homes: `days = setup + rate*SQ` (Tile 0.45+0.129/SQ R²0.70, Metal
   0.59+0.106/SQ R²0.66; Demo/Shingle noisy — need the demo-selector/tear-off type). The estimator
   ENGINE supports daily_series but the quote-builder wasn't feeding it (root cause of the ~$2k
   PROTECTOR delta per the Zoom notes). ⛔ **TO APPLY (prod-critical, Tim-gate):** feed setup+rate
   into daily_series config + refresh PREFERRED adder $160→$165.
2. **Gutters** — ALREADY BUILT (config schema + Tim's exact prices + 13 tests, commits 7191b06/
   933efb6). ⛔ **TO GO LIVE:** run `scripts/seed_gutters_config.py` (writes per-branch config
   versions to DB). 2 Tim-questions: hangers/$14.70 upgraded-DS unbundling; copper K $50/$70 (not
   in his list).
3. **Lumber chart optional proposal attachment + checkbox** — ✅ DONE + committed (738b638,
   208+4 tests pass). Reuses `adapters/gotenberg.html_to_pdf(attachment_pdf_bytes=)` on the real
   send flow; `include_lumber_chart` in quote_snapshot; SPA checkbox; Dockerfile `COPY assets`.
   (Aside the agent flagged: T&C/FAQ are currently ALWAYS rendered with no toggle — possible
   follow-up to add a T&C/FAQ toggle.)
4. **Metal Warranty Checker** — ✅ DONE (plugin + live `/metal-roofing-warranty/` staging page +
   brackish sources). Not #4-plugin-tool — that was a different "plugin tool" thread (est. widget).
5. **Metal roof series + FAQ** — ✅ DONE + now all LIVE on staging.
6. **Greener competitor proposal** — ✅ already used in Zoom notes to verify tier adders (Caribbean
   $290/Med $365/Modern $485/sq). No separate PDF needed.
7. **Branding style guide (#7)** — ⛔ BLOCKED: the email is just the DeGenito logo + social logins;
   no formal style guide (colors/fonts/rules) exists yet. NEED Wendy's guide before adjusting the
   settings page or scanning the site.
8. **WP "Integration BROKEN"** — ✅ resolved (Wendy's temp-domain/live-vs-staging discussion).

## PRICING TIERS (Tim asked "did you frame them?") — YES, mostly
Config (Exhibit B-2026-07): `profit_scale [[1,400],[4,200],[7,160],[14,140],[20,120],[29,110],[null,100]]`
(margin-by-size: small jobs 4× margin), `profit_floor_pct 0.13`, `profit_plus_oh_floor_pct 0.33`.
Zoom-spec'd: PROTECTOR/PREFERRED/3-PREMIUM tiers + $2,500/on-site-week + per-job small-roof minimums.
The days/SQ RANGE = economy-of-scale (small roofs higher per-SQ), which the min-margin rules cover.

## NEXT ACTIONS
1. Verify + commit the #3 lumber changes (check the pytest result first).
2. Marketing meeting **7/27 2pm EST** — build a content/SEO status brief (375 articles, metal live,
   llms.txt/AIO, hub). Confirm agenda/owner (DeGenito vs Wendy).
3. Tim-gated: apply #1 daily_series + PREFERRED $165 + run gutter seed (`scripts/seed_gutters_config.py`).
4. Get Wendy's style guide → do #7.
5. Prod cutover + paid 3k run (Jon-gated).

## ENV RECIPE (articles): see docs/continuations/CONTINUATION-2026-07-24.md. EMBED_BACKEND=vertex; parallelize with
separate processes not --workers>1; Cloud SQL proxy up. R6: commits update docs + memory.
