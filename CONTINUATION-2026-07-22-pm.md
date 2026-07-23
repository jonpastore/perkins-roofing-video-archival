# CONTINUATION — 2026-07-22 PM (second session of the day)

Built queue items #1–#3 to the binding routing policy, deployed prod twice-total today, then a
deep multi-pass audit of the 61 staging articles found and fixed systemic content rot — and the
correction passes are now BUILT INTO the generative loop. Wendy reply drafted, verified, and
recreated with the prefill CSV attached — **Jon sends it**. Read this + `prompt.txt` to resume.

## Deployed state
- **Prod image `platform:1a96dda`** (API + all jobs; `prod_smoke.py` PASS; SPA redeployed to
  Firebase). Prod stays `LLM_BACKEND=vertex`. **HEAD (`ac9f2f1`) is AHEAD of prod** — the
  article_repair pipeline (6657a7d) + portfolio pipeline (ac77a44) are committed but NOT
  deployed. **Deploy before any bulk article generation** (repair pass must be live first).

## Shipped this session (all pushed)
- **llms.txt / AIO (4f80702)** — plugin v1.2.0 serves `/llms.txt` (physical-file write beats
  the static-file shadow; option fallback) + `robots_txt` filter AI-crawler allowlist (never
  Rank Math). `jobs/llms_txt_job.py` appends the article index to Wendy's hand-written
  preamble (`PlatformConfig LLMS_TXT_PREAMBLE` — FAIL-SAFE: no preamble → no push). Wired
  into promote_job. LIVE on staging: 61 entries, preamble byte-identical, cache flushed.
- **WP_URL env purge (25b41ff)** — zero env reads anywhere (jobs, faq gate, install script,
  5 stale tests now exercise the PlatformConfig resolver).
- **Repair/re-roof toggle + SOW AI rewrite (95de3cf)** — Quoting.tsx mode toggle, shared
  scope-of-work textarea + "Rewrite with AI" → `POST /estimator/scope-of-work/rewrite`
  (app.llm.chat — CF llama after the flip), repair proposals now send-valid
  (repair-quote returns pricing_config_hash+floors), config `scope_of_work.default_template`
  editable in EstimatingConfig. Residual (#387 @80%): SOW text not yet in the contract PDF.
- **Portfolio automation (ac77a44)** — core/portfolio.py + scripts/portfolio_{prefill,publish}.py:
  13 Avada Portfolio DRAFTS on staging (8287–8299, 10 Commercial/3 Residential, tags=city,
  skills=roof-type), CF llama write-ups grounded in Knowify+video data, Wendy's 30-field sheet
  prefilled → `docs/portfolio/wendy-sheet-prefill-2026-07-22.csv`. 9/13 Knowify-matched
  (doc-only: River Place, Abacoa, SL Construction, Malooly). Publisher targets admin-config
  WP_URL (post-cutover reruns would draft on prod — human-gated, fine).
- **article_repair pipeline (6657a7d)** — THE BIG ONE: every one-off correction pass from
  tonight's audits productionized as `core/article_repair.py` (pure, 51 tests, 100% cov,
  idempotent) wired fail-open at both generation choke points: video-id fuzzy-fix (≥0.85 vs
  the 841-video library), invented-image strip + real-thumb restore, dead-link
  pillar-rewrite/unwrap, `*.myftpupload.com` host rewrite, VideoObject↔content sync, service
  links, TOC H2-only, + optional wp-field hooks (category/featured warns when publisher
  passes them). Regression 414 passed (8 pre-existing test_topics live-LLM hangs → #409).

## The staging audit (data-side fixes — LIVE on staging + DB, no commit needed)
Two independent validation passes over ALL 61 articles found and fixed:
FAQPage 61/61 · **VideoObject 61/61** (was 0/61! backfilled from embedded videos; 4 corrupted
ids were 1-char typos of real ids — fuzzy-matched: gtbkLgg_G9o, E_X65i3xQO0, tpxdWz4Oqnw,
SxdHJZbyO78; the "video-less" article's real sources recovered via `source_transcripts()` —
AnotOjX6eCA Evergrene + Roofing 301 restored) · service links 61/61-relevant · 17 invented
images stripped/replaced · 95 dead cluster links unwrapped, 20 dead-host links rewritten ·
**categories: all 61 out of the default bucket** into the 28-cat taxonomy (CF llama classified)
· **featured images 60/61** (thumbnails sideloaded to WP media) · TOC H2-only verified ·
llms.txt preamble byte-identical · robots allowlist live · 13 portfolio drafts verified.
Validator patterns live in the session scratchpad (validate_all.py / second_pass.py) — the
committed core/article_repair.py encodes the same checks for the future.

## Wendy email — DRAFT READY, JON SENDS
Threaded reply draft in Jon@DeGenito.ai Outlook (to Wendy + Eli, `RE: Meeting notes and info`)
with `Perkins-project-sheet-prefill-2026-07-22.csv` ATTACHED. Content 13-point verified:
61 articles + VideoObject-on-every-article + categories/featured/TOC, llms.txt + robots,
bot-blocking = CF Browser Integrity Check ("we'll take care of getting that fixed" — **we do
NOT manage the zone**, Jon corrected; #403 decision still his), portfolio with the
feelings-safe 4-tier fill order + 5 cited sources (Google E-E-A-T update, helpful-content,
Whitespark 2026, review-recency, Rater Guidelines PDF) + GBP-review nudge, residential/Jupiter
gaps, 1-2 live test posts. GOTCHA: Outlook autosave CLOBBERS Graph-side edits when the draft
is open in the client (ate one fix; draft was later deleted + recreated fresh).

## Cost analysis (Jon asked; sources in session log)
3,000 articles to our standard: **CF llama draft + Vertex validate ≈ $145** (validator ≈$40 is
constant); Gemini-only ≈$165 (batch ≈$85); Haiku 4.5 ≈$295 (batch ≈$170). CF free tier =
10k neurons/day ≈ **only ~3 articles/day free** (~3.1k neurons each) — bursts run on paid
overage ($0.011/1k). Parallelism changes wall-clock only: ~15h at 20 workers. Publishing
cadence stays 10/day per cutover plan (3,000 at once = spam-classifier risk).

## Jarvis
#374/#385/#386 shipped earlier · **#387 80%** (SOW→contract-PDF residual) · **#384 60%**
(portfolio backend done, UI remains) · #396–#403 new 7/20-Zoom gaps (price book tab, license
placeholder, YT comments, go-live banner, GitHub org, lumber PDF—Tim, aluminum YT link,
**#403 CF browser_check decision—Jon**) · #404 o365-api stale refresh-token (direct-Graph
workaround works; bind-mount inode gotcha) · #405/#406 DONE (repair pipeline) · #407 extend
Wendy's candidates doc + Tim residential/Jupiter ask · **#408 Jon: send Wendy+Eli the
app.perkinsroofing.net webadmin invite (promised 7/20)** · #409 test_topics live-LLM hang ·
#410 generation-side placeholder-video-id guard.

## Waiting on
- **Jon**: SEND the Wendy draft · CF prod-flip go (§2 cutover plan) · CompanyCam creds ·
  #403 browser_check decision · #408 webadmin invite · prod WP app password at cutover ·
  SEO submission creds (IndexNow key + Google Indexing SA).
- **Wendy**: review staging (email pending send) · criteria list · parity confirm · prod
  Rank Math config.
- **Tim**: portfolio punch-list answers (tier-1 fields + permissions) · residential/Jupiter
  candidates · 6 pricing items · lumber-schedule PDF.

## Key recipes / gotchas (details in auto-memory `llms-txt-and-sow-shipped-2026-07-22`)
- DeGenito Outlook via cerberus `~/gmail-enhanced-mcp` msal token + Graph (scope must be
  fully-qualified `https://graph.microsoft.com/Mail.ReadWrite`); pull FULL untruncated bodies
  before auditing a thread; drafts: createReply → insert above quote; attachments via
  `/attachments` fileAttachment.
- Staging WP 429s under fast crawls (throttle + backoff); GoDaddy gateway cache 31d on static
  files — flush via wp-admin admin-bar nonce URL (Playwright navigate, the link is hidden);
  edge caches `?v=` keys — fresh buster per validation run; llms.txt served without charset —
  byte-compare, never requests `.text`.
- Corrupted video ids are ~1-char typos of real ids — difflib fuzzy-match before scrubbing;
  placeholder ids (embed/example) mean the generator LOST the linkage —
  `source_transcripts(keyword, db)` recovers the true grounding videos.

## Operate
- Deploy: `set -a; source .env; set +a; export GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/perkins-deploy-sa.json; bash scripts/deploy.sh` (CLEAN tree). Smoke: `.venv/bin/python scripts/prod_smoke.py`.
- SPA: `cd web && npm run build && firebase deploy --only hosting:app`.
- Cloud SQL proxy + DB recipe, CF creds, WP creds: see prompt.txt.

---
Archive directive applied: moved `CONTINUATION-2026-07-20-pm2.md` → `docs/continuations/`
(top level keeps 07-21, 07-22, 07-22-pm); README index updated.
