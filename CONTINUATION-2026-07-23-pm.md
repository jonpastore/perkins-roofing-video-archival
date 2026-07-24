# CONTINUATION 2026-07-23 pm — Vertex flip + compliant-article generation pipeline

Resume after /clear. HEAD == `ad502e5` (clean tree, all pushed to origin/main).

## ⛔ THE ONE THING THAT MUST BE TRUE BEFORE SPENDING ON THE 3K RUN
**Every generated article must pass ALL compliance checks (the full Wendy checklist)
before it ships.** The pipeline now enforces this in a loop, but it has NOT yet been
proven at 100% end-to-end. The last validation (val3) exposed a regression I fixed;
val4 is the re-validation. DO NOT run the paid 3k generation until a validation batch
shows `compliance_rate == 1.0` with empty `criteria_failures`.

## CAN WE CLEAR NOW? — YES.
The val4 validation batch is a **detached nohup process** (measure-mode, ephemeral
articles — nothing persisted, DB still 66) that writes its report to a FILE that
survives /clear:
- Report:  `<SCRATCH>/val4_report.json`
- Log:     `<SCRATCH>/val4_run.log`
- SCRATCH = `/tmp/claude-1000/-home-jon-projects-perkins-roofing-video-archival/a9f99bd5-709e-494b-a155-babbcc42071b/scratchpad`

After resume: read val4_report.json. If not there yet, `grep -c compliant= val4_run.log`
(x/12). No keeper work is at risk — val4 is a compliance probe, not the real run.

## FIRST STEPS ON RESUME
1. Cloud SQL proxy (check `pgrep -f cloud-sql-proxy` first; likely still up):
   `GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/perkins-deploy-sa.json /tmp/cloud-sql-proxy video-archival-and-content-gen:us-central1:video-archival-and-content-gen-pg --port 5432 &`
   `PW=$(gcloud secrets versions access latest --secret=db-password)` →
   `DB_URL="postgresql+psycopg://app:${PW}@127.0.0.1:5432/perkins"`
2. Read `<SCRATCH>/val4_report.json` → the authoritative compliance verdict.
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
