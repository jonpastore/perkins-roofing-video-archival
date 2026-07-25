# CONTINUATION 2026-07-24 — deterministic gate + grounding critic + 100-run + 210-run

## ⚡ LATEST STATE (end of 2026-07-24 session) — HEAD `187b65b`, clean, pushed
**Library = 374 articles on STAGING** (120 pillar / 252 cluster / 2 standalone; 373 topics;
322/374 linked to source videos). All compliant. Prod perkinsroofing.net untouched (Jon-gated).
Done since the 100-run below: **one calibrated grounding critic per generation iteration**
(9ba04a9 + 0ae4607 — Tim's videos are the spine, accurate general/scientific enrichment ALLOWED,
only hallucinations/invented metrics block); **valid_video_ids auto-heal** (187b65b — strip a
hallucinated video id and embed a real grounded one instead of blocking); **DB video linkage**
(20014ba, migration 0045 + scripts/backfill_article_videos.py); **de-dup** of 27 restart-cruft
rows (WP trashed, reversible — the ~122 non-DB WP posts are WENDY'S, off-limits); and a **210-run**
(scripts/plan_coherent.py: 70 pillars × 2 clusters, deduped, clusters by video co-occurrence, 20
metal pillars, 10 parallel processes) → 209/210 + the 1 miss recovered.

**WHAT'S LEFT:** fill each pillar's clusters out to 5-7 + cover the remaining ~1700 harvested
topics (repeat plan_coherent → 10-way run → backfill); prod cutover + paid 3k (Jon-gated); optional
polish: fuzzy-backfill the 52 unlinked originals, persist source_video_ids inline in _publish_fields,
run the calibrated critic over the pre-calibration 100-run articles. New generation self-heals
video hallucinations and runs the calibrated critic, so future batches land clean.

---

# (earlier in the session) deterministic compliance gate + grounding critic + 100-run

Resume after a restart. **HEAD == `4a01cd7`** (superseded — see LATEST STATE above).
SCRATCH = `/tmp/claude-1000/-home-jon-projects-perkins-roofing-video-archival/fc25f81c-006d-444d-a7cf-26ac94fa2737/scratchpad`
(NOTE: scratch is per-session; on a fresh session it changes. The durable state is the DB +
git. The plan/report files below live in the 07-24 scratch above — copy any you still need.)

## ⛔ WHAT'S LIVE RIGHT NOW (check on resume)
- **A 100-article generation run is in flight** — 5 parallel `python -m jobs.batch_article_job`
  processes (detached under **systemd**, PPID 1508 — survives Claude exit; dies only if morpheus
  sleeps/reboots). Plan slices: `$SCRATCH/plan_100_s{0..4}.json`. Logs: `$SCRATCH/run100_s{0..4}.log`.
  - CHECK: `pgrep -af '[j]obs.batch_article_job'` ; count done:
    `for i in 0 1 2 3 4; do grep -c generate_scored_article $SCRATCH/run100_s$i.log; done`
  - This is a LOCAL orchestrator calling **Vertex** (Gemini 2.5 Flash) for inference. NOT a
    GCP-hosted job. Only inference is on GCP; the loop runs on morpheus.
  - Target: STAGING WP (WP_URL=`https://1228404.us6.myftpupload.com`) + ScheduledContent
    target="staging". Does NOT touch prod perkinsroofing.net. Prod cutover + paid 3k = Jon-gated.
  - Known run block: `valid_video_ids` on a few articles (e.g. 'high-pitched shingle roof' embedded
    id `Zo1e6eLZO4s` not in known_video_ids). This is a NON-fixable criterion by design (can't
    fix an ungrounded video) — the gate correctly blocks + does NOT publish. Tally at the end;
    these need a generation-side fix (only embed grounded ids) to reach a literal 100/100.

## THE BIG WIN TODAY: the compliance gate is now FULLY DETERMINISTIC
val5 was 8/12 (all 4 fails = seo_ranking). Root cause across the board: **a criterion guaranteed
keyword/element PRESENCE but not the FORMAT constraint, so it leaned on the stochastic LLM
re-refine.** Every one fixed with a deterministic ensure. The whole DB reaches 100% with ZERO LLM
re-refine. Commits (all pushed):
- `bb843d1` — rm_kw_in_intro (new `_ensure_keyword_in_intro`), rm_kw_in_meta (keyword-aware
  `_clamp_meta`), rm_kw_in_slug (alphanumeric-tolerant — fixes parenthetical keywords).
- `35e776b` — rm_slug_length (replace verbose LLM slug ≥75 chars with the short keyword slug),
  rm_title_kw_position (pull a buried keyword to the title's front).
- `17bc445` — answer_first: the criterion pulled the STRICT aio_answer_first (≥70% of H2s open with
  30+ words), unsatisfiable even by the LLM; its label says "lede" and core.seo calls AIO advisory,
  so it now checks the LEDE (matches `_ensure_answer_first`). Detector window 200→300 in BOTH the
  ensure and the checker (a normal opening sentence's period landed at 201). Also `wordpress.update()`
  gained category_ids + featured_media.
- Lesson (write it on the wall): **every gate criterion needs a deterministic ensure that guarantees
  BOTH presence AND the format constraint, and the checker's window must match the ensure's.**

## EXISTING LIBRARY REPROCESSED TO 100% (done, on staging)
`scripts/reprocess_articles.py` (`89b6950`): loads every article failing core.article_criteria, runs
the gate PRESERVING the slug/permalink, updates the WP post + DB row in place. **66/66 pre-gate
backfill articles fixed deterministically (no LLM).** Whole DB verified 113/113 compliant. All 61
`status=published` posts confirmed live on staging WITH the compliant content (subscribe CTA + video
iframe, still published). Internal status "scheduled" → WP "draft" (WP only accepts
publish/future/draft/pending/private). Dominant gaps were subscribe_cta (36), VideoObject schema
(needs `_apply_repair`, not just ensures), toc, seo_ranking.

## PARALLELISM: N independent PROCESSES, not `--workers>1`
The documented wedge is the in-process ThreadPoolExecutor. 5 separate procs over disjoint plan
slices (whole campaigns each, so pillar↔cluster links resolve) = ~5x, no wedge. Split with a tiny
python loop; see `$SCRATCH/plan_100_s*.json`.

## GROUNDING CRITIC — 1 critic per generation iteration (`9ba04a9`)
User asked for exactly ONE critic (not the 3-lens panel) at the end of each generation-loop
iteration. `jobs.article_job._grounding_critic_pass`: the grounding lens only (SEO is already
guaranteed by the deterministic gate; grounding is the moat — invented price/code is the worst
failure). Wired into `generate_scored_article`'s score/refine loop; revises once on a blocking
finding; no-op without a transcript; fail-open.
- **Vertex bug fixed in passing:** Vertex `response_schema` demands UPPERCASE OpenAPI type names and
  KeyErrors on core.article_critique's lowercase JSON-Schema — which is why the existing 3-lens
  `_run_critics` silently yielded nothing on Vertex. The single critic uses `want_json` only
  (parse_findings is fail-closed on shape). Verified: it caught an invented "$4,732/linear foot" +
  fake code section and revised them out.

## ⛔ OPEN DECISION: the grounding critic is AGGRESSIVE — calibrate before mass-regen
`scripts/validate_run_with_critic.py` (`4a01cd7`) validates already-generated articles with the
critic and regenerates ONLY the flagged ones. Dry-run smoke on ONE article
(`concrete-tile-moisture-absorption`) returned **20 blockers** — including general explanatory prose
(concrete microstructure/curing), NOT just fabricated specifics. So as-is it would flag ~every
article and `--apply` would regenerate nearly all 100 (expensive, uncertain benefit — the base model
re-adds general knowledge). **DO NOT run `--apply` across the batch until the critic is calibrated**
(e.g. only treat truly-invented specifics — prices/codes/measurements absent from the transcript — as
blocking; keep general roofing education as `minor`). This is a `blocking()`/severity + prompt-tuning
decision in core/article_critique.py. NEXT: tune the grounding prompt to distinguish "fabricated
specific" from "uncited general knowledge", re-smoke, then validate → regenerate the true offenders.

## NEXT ACTIONS (in order)
1. Confirm the 100-run finished: `pgrep -af '[j]obs.batch_article_job'` empty; read
   `$SCRATCH/run100_s*_report.json` for compliance_rate + criteria_failures.
2. Verify whole-DB compliance (fast, no LLM):
   run the check_compliance loop over all articles (see the recipe in HOW TO VALIDATE below).
3. **Calibrate the grounding critic** (OPEN DECISION above) before any regeneration.
4. Handle the `valid_video_ids` blockers (generation should only embed grounded ids) for a literal 100/100.
5. THEN, if wanted, `validate_run_with_critic.py --apply` on the (calibrated) critic; and the
   Jon-gated prod cutover + paid 3k run.

## HOW TO VALIDATE (env recipe — used everywhere above)
```
cd /home/jon/projects/perkins-roofing/video-archival
set -a; source .env; set +a
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/perkins-deploy-sa.json
PW=$(gcloud secrets versions access latest --secret=db-password); export DB_URL="postgresql+psycopg://app:${PW}@127.0.0.1:5432/perkins"
export PYTHONPATH=$PWD EMBED_BACKEND=vertex GOOGLE_CLOUD_PROJECT=video-archival-and-content-gen GCP_REGION=us-central1 LLM_BACKEND=vertex LLM_MODEL=gemini-2.5-flash
# whole-DB compliance: python one-liner over articles running core.article_criteria.check_compliance
# (kw = focus_keyword or slug de-hyphenated). Cloud SQL proxy already up (pgrep cloud-sql-proxy).
.venv/bin/python -m scripts.reprocess_articles           # dry: lists any non-compliant
```
GOTCHAS: EMBED_BACKEND=vertex required for grounding retrieval; batch `--workers 1` per process
(parallelize with SEPARATE processes); repair whitelists SERVICE_SLUGS + the pillar slug — don't
regress; GoDaddy WAF blocks Cloud-Run→WP but morpheus is fine (the batch runs on morpheus).

## STATE / COMMITS TODAY (all pushed, HEAD 4a01cd7)
bb843d1 · 35e776b · 17bc445 (gate deterministic) · 89b6950 (reprocess_articles) ·
9ba04a9 (grounding critic) · 4a01cd7 (validate_run_with_critic).
Tests: core + jobs suites green; new tests for every fix (seo, criteria, expand, critique).

---
Archive directive applied: moved `CONTINUATION-2026-07-22.md` → `docs/continuations/`
(top level keeps 07-22-pm, 07-23-pm, 07-24). README "most recent" pointer + links refreshed.
