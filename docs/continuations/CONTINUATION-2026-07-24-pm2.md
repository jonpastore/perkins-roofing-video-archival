# CONTINUATION 2026-07-24 pm-2 — Tim's list closed out (estimator day model deployed)

Resume after restart. **HEAD == `eae22f1`** + this doc. 4 commits this session, all pushed.
SCRATCH = `/tmp/claude-1000/-home-jon-projects-perkins-roofing-video-archival/4ae4b530-a625-4d02-b0cf-a814c54f5c9a/scratchpad`

## WHAT SHIPPED (Jon's call: "deploy + seed both")

### 1. Estimator: labor days auto-fill from squares (`24f0700`)
`overhead_mode="daily"` with no days used to fall back **silently** to per-square OH, so "By time
(days)" only worked if the estimator guessed the days — the root of the ~$2k PROTECTOR delta.
- `config["daily_overhead_day_model"]` = `{demo_series, install_series_by_roof_type, series:{setup,
  rate}}`, the least-squares fits from Tim's 30-home TIME LEARNING log (tile 0.45+0.129/SQ R² 0.70,
  metal 0.59+0.106/SQ R² 0.66, demo/shingle noisy at R² ≈ 0.37).
- `core.estimator.derive_daily_series(config, q)` → half-day-rounded days; `estimate()` fills them
  **only when the caller supplied none** (typed days always win) and returns `result["daily_series"]`.
- **Guard 1:** a roof type with no fitted install model (every low-slope system) derives NOTHING and
  keeps per-square OH. Demo days alone would replace OH with a fraction of it → job quoted under cost.
  A test caught this during implementation; keep the test.
- **Guard 2:** auto-filled estimates carry a `daily_days_auto_filled` warning (amber box in the SPA).
- PREFERRED tile adder needed no change — already $165, verified vs the Greener 7/17 PDF.

### ⚠️ 2. THE OPEN QUESTION — the two OH modes disagree (Tim must settle it)
by-days $/sq vs configured per-square OH, measured on Exhibit B:

| Roof (HVHZ)     | 20 SQ     | 43 SQ            | 80 SQ     |
|-----------------|-----------|------------------|-----------|
| 13" tile        | 217 / 270 | 177 / 270 (−93)  | 168 / 270 |
| **barrel tile** | 217 / 420 | **177 / 420 (−243/sq ≈ −$10.4k on one roof)** | 168 / 420 |
| standing seam   | 211 / 280 | 172 / 280 (−108) | 161 / 280 |
| shingle         | 158 / 125 | 106 / 125 (−19)  | 92 / 125  |

**Pre-existing** (any hand-typed by-days quote already produced this), but an order of magnitude past
the $2k the Zoom was chasing. Either the day rates ($745–1,050/day) carry less than per-square OH, or
per-square OH holds fixed costs the day rates omit. Full table + reasoning in
`docs/ROOFR_OVERHEAD_TIERS.md`. **Do not make by-days the default, and do not remove the warning,
until Tim answers.** Margin floors (13% / 33%, $2,500 per job and per on-site week) are the only
backstop today.

### 3. Proposals: optional T&C + contract FAQ (`3bab031`)
`quote_snapshot.include_terms` / `include_contract_faq`, **default ON** (absent flag = included — a
proposal that silently drops its T&C is a contract defect). Custom DB templates can read
`tc.include_terms` / `tc.include_contract_faq`. Closes the aside flagged while shipping 738b638.

### 4. Articles: last 53 linked to their source videos (`692a367`) — **375/375 done**
An SEO focus_keyword is rarely a verbatim topic label, so exact-match left 53 unlinked.
`scripts/backfill_article_videos.py --retrieval` asks `source_transcripts()` — the SAME grounded
retrieval the generator was given — instead of fuzzy-matching an SEO headline to a topic label.
Applied to prod. Needs `GOOGLE_APPLICATION_CREDENTIALS="$(scripts/fetch_vertex_sa.sh)"` (the `.env`
default path `./infra/vertex-dev-sa.json` does not exist → "Unable to authenticate your request").

### 5. SPA (`eae22f1`): "Labor days used" row, blank-days-auto-fill note, two new proposal checkboxes.

## TIM'S 8 ITEMS — now closed except Wendy's guide
1. Overhead/time-learning — ✅ built + deployed. Open: which OH mode wins (above).
2. Gutters — ✅ **already seeded in prod** (all 3 branches, values match his 7/17 email). The
   "TO GO LIVE: run seed_gutters_config.py" note in the previous doc was **stale**. Open questions:
   downspout unbundling / hangers / $14.70 upgraded DS, and copper K $50/$70 (never on his sheet).
3. Lumber chart attachment — ✅ (738b638) · 4. Warranty checker — ✅ · 5. Metal series + FAQ — ✅ LIVE
6. Greener — ✅ used to verify tier adders · 8. WP "integration broken" — ✅ resolved
7. Branding style guide — ⛔ BLOCKED on Wendy (the email held only the DeGenito logo).

## EMAIL TO TIM
Drafted, **not sent**: `<scratch>/tim_email_draft.md`. Leads with the OH-mode question, then the
demo-tear-off split and the two gutter gaps. Outbound gate is still `EMAIL_SEND_MODE=test`.

## VERIFICATION
- `tests/core` + `tests/api/test_estimator_f2.py` + proposal suites green; only pre-existing failure
  is `tests/core/test_avatar_script.py::test_gate_passes_professional_script` ("no such table:
  tenants" — fails on stashed HEAD too).
- `cd web && npm run build` clean (tsc). Lint: the 2 ruff findings in `test_estimator_v2.py`
  (unsorted imports, unused `math`) pre-date this session.
- Prod seed: `scripts/seed_daily_overhead_config.py` adds only `daily_overhead_day_model` (v6→v7 per
  branch); it is idempotent **per key** now, so re-running is safe. Ran it: jupiter/miami/naples v7
  (ids 26/27/28).
- **DEPLOYED + prod-smoked** (`<scratch>/smoke_daydays.py`, API revision `api-00134-4xn`, image
  `platform:eae22f1`; SPA release `9a651df8332c9103` on Firebase Hosting). Miami HVHZ 13" tile 43 SQ
  over tile:
  - auto-fill → `daily_series=[tile 6.0d, demo_dry_in_flat 3.0d]`, OH **$7,620 ($177.21/sq)**,
    total $51,380, `daily_days_auto_filled` warning present
  - typed `tile=6.0d` → OH $4,470, no warning (typed days win, nothing auto-added)
  - `per_sq` baseline → OH $11,610 ($270/sq), total $55,370 → **−$3,990 on this job**, and Tim's own
    PROTECTOR figure ran *below* the engine's, so the direction matches his number.

## NEXT ACTIONS
1. Marketing meeting **7/27 2pm EST** — content/SEO status brief (375 articles, metal live,
   llms.txt/AIO, hub). Confirm agenda owner (DeGenito vs Wendy). **Not started.**
2. Send Tim the draft (Jon's call) and get the OH-mode answer.
3. Wendy's style guide → then #7 (settings page + site scan).
4. Jon-gated: prod cutover (staging→perkinsroofing.net); paid 3k article run.

## GOTCHAS
`EMBED_BACKEND=vertex` + the `fetch_vertex_sa.sh` creds for anything retrieval-shaped; parallelize
with separate processes, never `--workers>1`; Cloud SQL proxy on 127.0.0.1:5432; `articles` is keyed
by **slug**, there is no `id` column; `scripts/deploy.sh` needs `bash scripts/deploy.sh` (not
executable) and refuses a dirty tree (R3-ENFORCE).

**Standing archive directive:** when writing the next continuation doc, move the OLDEST top-level
`CONTINUATION-*.md` into `docs/continuations/`, keep only the latest 3 at top level, fix every
inbound link to the moved file, refresh the README "most recent" pointer, and update related docs.
Done here: `CONTINUATION-2026-07-23-pm.md` archived.
