# CONTINUATION 2026-07-23 pm — Vertex flip + compliant-article generation pipeline

Resume after /clear. HEAD == `3faba8a` (clean tree, all pushed to origin/main).

## ⛔ TWO VALIDATION FINDINGS — READ BEFORE ANYTHING (this is the real state)
Two separate compliance realities, both proven by running `core.article_criteria`:

1. **NEW pipeline (fresh generation through the gate) = 8/12 compliant** (val5, measured).
   The 4 failures were ALL `seo_ranking` — the loop correctly BLOCKED them (not
   published), but the LLM re-refine isn't reliably clearing the ranking-tier
   Rank Math checks within the 4-iter cap. So the gate is safe (blocks misses) but
   NOT yet at 100% first-pass. FIX: strengthen the seo_ranking close (more
   deterministic ensures for kw-density/content-length/external-link, and/or raise
   the re-refine budget) → re-validate until 12/12.

2. **EXISTING staging articles = 0/12 pass the full checklist** (validated the 12
   most-recent DB rows). Breakdown — DON'T conflate real vs artifact:
   - REAL gaps: **Subscribe CTA missing on 7/12**; **absolute (not relative) internal
     links on 7/12** (fail rm_internal_link); 2 short CF-degraded stubs
     (metal-roof-fasteners, roof-inspection-after-hurricane).
   - ARTIFACTS (my checker, not the content): **9/12 have focus_keyword=NULL in the
     DB** → all rm_kw_* fail as an artifact (real keyword may be in WP Rank Math);
     **video_embed regex false-negatives** (DB shows youtube.com/embed on all 12).
   These OLD articles predate today's gate (made by the prior pipeline + backfill).

## ⛔ NEXT ACTIONS (in order)
1. **Fix the checker** so verdicts are trustworthy: core/article_criteria.py
   `_VIDEO_EMBED_RE` (false-negatives on real embeds) + keyword resolution when the
   article's focus_keyword is NULL (derive/skip rather than use the hyphenated slug).
2. **Close seo_ranking in the loop** so new generation hits 12/12 (see finding #1).
3. **Re-process the existing 66 DB articles through the gate** (a job that loads each
   Article, runs _reapply_fixable_ensures + _compliance_gate, re-publishes to WP) so
   the LIVE content Wendy reviews actually meets the standard — before prod cutover.
4. THEN the paid 3k run. DO NOT run it until a validation shows compliance_rate==1.0.

## VALIDATE THE REAL DB ARTICLES (the honest check)
`<SCRATCH>/validate_recent.py` runs check_compliance on the 12 most-recent DB rows.
Re-run it after the checker fix + re-process to confirm the live content passes.

## CAN WE CLEAR NOW? — YES.
val5 finished (8/12). Nothing running that matters; all code committed+pushed; the
DB is the durable store (still 66, unchanged — validation batches were ephemeral).
- SCRATCH = `/tmp/claude-1000/-home-jon-projects-perkins-roofing-video-archival/a9f99bd5-709e-494b-a155-babbcc42071b/scratchpad`
- val5 report: `<SCRATCH>/val5_report.json` (8/12, failures {seo_ranking: 4}).
- DB validator: `<SCRATCH>/validate_recent.py`.

## FIRST STEPS ON RESUME
1. Cloud SQL proxy (check `pgrep -f cloud-sql-proxy` first; likely still up):
   `GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/perkins-deploy-sa.json /tmp/cloud-sql-proxy video-archival-and-content-gen:us-central1:video-archival-and-content-gen-pg --port 5432 &`
   `PW=$(gcloud secrets versions access latest --secret=db-password)` →
   `DB_URL="postgresql+psycopg://app:${PW}@127.0.0.1:5432/perkins"`
2. Read `<SCRATCH>/val5_report.json` → the authoritative compliance verdict.
   - If `compliance_rate == 1.0`: proceed to a small PUBLISH-mode smoke, then the real run.
   - Else: `criteria_failures` names each remaining check → fix the ensure in the loop,
     re-run val (see "how to validate" below). Same disciplined cycle.

## THE COMPLIANCE SYSTEM (what was built today — the core deliverable)
- **`core/article_criteria.py`** = THE single Wendy checklist (16 criteria): faq_ge4,
  faqpage_schema, videoobject_schema, schema_scoped, video_embed, valid_video_ids,
  curated_image (not title card), service_links, pillar_link, no_blog, no_dead_hosts,
  toc (H2-only ≥3 sections), answer_first, meta_len (120–160), subscribe_cta,
  seo_ranking (all ranking-tier Rank Math). ONE definition used by the loop gate, the
  batch validator, and the tests — no drift.
- **`jobs.article_job._compliance_gate`** = a REAL LOOP (up to 4 rounds): each round
  re-applies the deterministic ensures (`_reapply_fixable_ensures`) + `_apply_repair`,
  and when only LLM-fixable criteria remain (seo_ranking/answer_first) it re-refines
  the body via the llm, then re-checks. Exits when fully green, else BLOCKS (attaches
  `fields["compliant"]=False`). Wired into BOTH generate_scored_article (line ~2339)
  AND generate_article publish path (line ~942, blocks live publish).
- **Publish-time criteria** (NOT content, so not in the checklist but wired into publish):
  WP **category** (`core/wp_category.pick_category_name` → real taxonomy, never
  Uncategorized) + **featured image** (curated frame → `wordpress.featured_media_from_url`).
  `wordpress.publish()` gained `category_ids` + `featured_media`.

## THE 3K RUN VEHICLE — the batch planner
- `jobs/batch_article_job.py`: concurrent campaign runner.
  - `--mode measure` (default): generate + report cost/compliance, NO side effects.
  - `--mode publish [--status draft|publish] [--per-day 10]`: for each COMPLIANT
    article → **persist Article row** (durable source of truth) + create WP draft
    (with category+featured) + **ScheduledContent** row at a paced go-live slot
    (10/day, 09:00–17:00 UTC from tomorrow). `promote_job` flips draft→published at
    publish_at. Non-compliant are NEVER published (skipped + reported).
  - Report: `fully_compliant`, `compliance_rate`, `criteria_failures`, `published`,
    `blocked_noncompliant`, cost extrapolation.
- **CONCURRENCY BUG**: 8-worker runs WEDGE (Vertex burst); use `--workers 1` (serial,
  reliable) or a small worker count until fixed. Validation batches ran `--workers 1`.
- Topic planning: `scripts/build_topic_plan.py` (best-grounded topics) OR the
  content-hub-aware `scripts/plan_placement.py` (+`core/topic_placement.py`): decides
  per candidate topic whether it JOINS an existing pillar as a cluster (cosine≥0.72)
  or SEEDS a new pillar — so new generation extends the hub, not dupes it. Plans in
  `<SCRATCH>/topic_plan_300.json` + `placement_plan.json`.

## HOW TO VALIDATE (the disciplined cycle)
```
set -a; source .env; set +a
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/perkins-deploy-sa.json
PW=$(gcloud secrets versions access latest --secret=db-password); export DB_URL="postgresql+psycopg://app:${PW}@127.0.0.1:5432/perkins"
export PYTHONPATH=$PWD EMBED_BACKEND=vertex GOOGLE_CLOUD_PROJECT=video-archival-and-content-gen GCP_REGION=us-central1 LLM_BACKEND=vertex LLM_MODEL=gemini-2.5-flash
# a plan slice (12 articles) → measure mode → read compliance_rate + criteria_failures
python -m jobs.batch_article_job <SCRATCH>/plan_val.json --workers 1 --no-critique --out <SCRATCH>/valN_report.json
```
Each article: ~6 LLM calls, ~1.5–3 min serial. 12 articles ≈ 25–35 min.

## COST (real, measured on 27 articles — Vertex/Gemini 2.5 Flash)
6 LLM calls avg, 43k in / 24k out per article. **3,000 articles: ~$218 standard /
~$109 batch (Flex)**. Use BATCH mode for the real run (< the ~$145 CF split, and no
free-tier wall). CF free tier is dead for volume (10k neurons ≈ 1–2 articles/day).

## STATE / DONE TODAY (all pushed)
- LLM_BACKEND flipped back to **vertex** in deploy.sh (`7d03965`); prod deployed earlier.
- **CI is GREEN** again (`82e0ac1` fixed 7 tests); 81 CI-failure emails trashed.
- **Metal Roof Warranty Checker plugin** (`8e7b835`) installed+active on staging;
  page live at `/metal-roofing-warranty/` (placeholder ELI5/TLDR/tech — Josh's copy
  pending). ONE manual step: add staging + perkinsroofing.net to the Google Maps API
  key's HTTP-referrer allowlist (GCP Console) or geocoding 401s. Closes #382; unblocks #402.
- Email flood fixed (knowify-sync paused, alerts→jon@, DMARC rua/ruf removed);
  Knowify mirror MCP-synced; CF browser_check OFF (#403 done, AI crawlers unblocked).
- Wendy reply DRAFT (with the GoDaddy-WAF note) sits in DeGenito Outlook — **JON SENDS**.

## WAITING ON JON
- Greenlight the real 3k run AFTER val shows 100%.
- Send Wendy draft. Google Maps key referrer allowlist (warranty checker geocoding).
- GoDaddy WAF: still intermittently blocks Cloud Run→WP writes (publish from morpheus
  works; the batch runs on morpheus so it's fine). If prod publish fails, that's why.
- CompanyCam creds, prod WP app pw, SEO creds (unchanged).

## GOTCHAS
- article generation MUST run with EMBED_BACKEND=vertex (grounding retrieval needs it).
- batch `--workers >1` wedges on Vertex; serial is safe.
- measure mode = ephemeral (no persist); publish mode = persist+schedule (durable).
- repair unwraps relative links to non-article slugs; SERVICE_SLUGS + the pillar are
  now whitelisted (core/internal_links + repair extra_valid_slugs) — don't regress that.

---
Archive directive applied: moved `CONTINUATION-2026-07-21.md` → `docs/continuations/`
(top level keeps 07-22, 07-22-pm, 07-23-pm).
