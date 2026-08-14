# Open decisions from the 2026-08-13 audit — proposed resolutions

Everything here was found and verified during the 4-agent audit (`b480627`, §6 of
CONTINUATION-2026-08-12-eve.md) and **deliberately not patched**, because each one is a decision
about behaviour rather than a defect with one right answer.

Each item: what breaks today, the options, **a recommendation**, and the effort. Recommendations
are mine; the call is Jon's.

---

## 1. 🔴 `"promoting"` is an orphan state — rows can strand permanently

**Today.** `jobs/promote_job.py` claims a row by setting `status="promoting"`.
`core/scheduler.CLAIMABLE` is `("scheduled", "error")`. Nothing else in the codebase reads
`"promoting"` — no reaper, no release. The `except` handles *exceptions* (sets `error`, increments
`attempts`), so the exposed case is the **process dying** between the claim commit and the final
commit: OOM, a Cloud Run revision swap, or `/internal/promote` outliving its request timeout. The
row then becomes invisible to every future run, `attempts` is never incremented, and the job
reports success. This is the 277-stranded-rows incident one state further along.

### Option A — `claimed_at` column + stale-claim reaper  ⭐ **RECOMMENDED**

Add `claimed_at TIMESTAMP NULL`, set it in the same UPDATE as the claim, and make the selector
treat `status='promoting' AND claimed_at < now() - interval '30 minutes'` as claimable, logging
and incrementing `attempts` when it reaps.

- **Why:** it is the only option that distinguishes "a sibling run holds this" from "a dead run
  held this". Everything else guesses.
- **Cost:** one migration, ~20 lines, plus the same treatment for `social_job`'s `"publishing"`,
  which has the identical hole behind a `finally` that process death also skips.
- **Risk:** the migration runner has a known ledger defect (it replays from 0013 and ignores
  `DB_URL`) — so apply this one deliberately and verify, don't let it ride along with a deploy.
- **Threshold:** 30 min is comfortably above the promote cron's 15-min period and any real run.

### Option B — claim-as-error (no migration)

Set `status="error"` **and** `attempts += 1` *before* doing the work; set `"published"` on success.
Process death leaves the row in `error`, which is already claimable, and `attempts` bounds the
retries.

- **Pro:** no schema change; strictly better than today immediately.
- **Con:** changes what `attempts` MEANS — it becomes "attempts started", not "failures", so the
  "published after N earlier failure(s)" log line becomes wrong, and `PROMOTE_MAX_ATTEMPTS` starts
  counting successes-in-progress. That is a state-machine change on the publishing path.

### Option C — leave it, add an alert

A daily query for rows in `promoting`/`publishing` older than an hour, mailed to jon@.

- **Pro:** zero risk, catches it the next day.
- **Con:** detection, not prevention. Given this exact class already cost 277 rows, detection alone
  is not enough.

**Recommendation: A**, and do `publishing` at the same time — they are the same bug in two jobs.
If the migration runner makes A unattractive this week, **C now, A when the runner is fixed**.

---

## 2. 🟡 `render_job` has no single-flight — a double-click burns two hours and 2 GB

**Today.** `ingest_worker`, `knowify_sync` and `companycam_sync` all wrap their body in
`with _single_flight() as ok:`. `render_job` does not, and it is externally triggerable per series
via `POST /clips/{id}/render` with no dedupe. Two executions both pass the `gcs_url` idempotency
check, both pull a ~2 GB source into memory-backed `/tmp`, and both spend ~an hour; the loser then
violates `uq_social_series_part_platform` and its render is discarded. `ScheduledContent` is
inserted unconditionally (not get-or-create), so an interleaving can leave two promote rows for one
reel.

### Option A — per-series advisory lock  ⭐ **RECOMMENDED**

`pg_advisory_lock(hashtext('render:' || series_id))` held for the render. Postgres releases it
automatically if the connection dies, which is exactly the property item 1 has to work for.

- **Cost:** ~10 lines, no migration, no schema.
- **Effect:** the second click returns "already rendering" instantly instead of burning an hour.
- **Note:** the repo already uses advisory locks elsewhere (CompanyCam uses 8274126).

### Option B — wrap `run()` in the existing `_single_flight`

- **Con:** its lock is **process-wide**, so this serialises ALL renders, not just duplicates of one
  series. That is a throughput regression nobody asked for.

### Option C — make `ScheduledContent` insert a get-or-create and accept the wasted work

Fixes the duplicate promote row but still burns the second hour.

**Recommendation: A.** B is the wrong shape and C only fixes the symptom.

---

## 3. 🟡 The e-signature IP is possibly forgeable — and it is now answerable, not arguable

**Today.** `_client_ip` takes the **leftmost** `X-Forwarded-For` entry. That is a deliberate
contract (record the SIGNER, not the proxy) pinned by
`TestESignIP::test_client_ip_uses_x_forwarded_for_leftmost`. Every hop *appends* to XFF, so
leftmost is client-supplied **unless the ingress overwrites it**.

**Established during the audit:** `proxied = false` on every Cloudflare record
(`infra/cloudflare.tf`), and line 232 says it must stay false until Firebase cert provisioning
completes. So Cloudflare is **not** fronting the app and `CF-Connecting-IP` is unavailable. Traffic
goes client → Google Front End → Cloud Run/Firebase.

### Proposed resolution — measure it, then decide (½ hour) ⭐

1. Log the **raw** `X-Forwarded-For` header (not the parsed value) on the accept endpoint, behind
   a flag, for one deploy.
2. Accept one test proposal from a browser, and one via `curl` with a forged
   `X-Forwarded-For: 1.2.3.4` prepended.
3. Compare. If the forged value survives at position 0, leftmost is forgeable **here** and the
   correct read is "the entry Google appended". If Google overwrote it, today's code is already
   correct and the finding is closed.
4. Remove the debug log.

**Do not change the parsing before step 3.** Taking the trailing hop on an assumption would record
the load balancer for every legitimate signer — breaking the ordinary case to harden the
adversarial one. I made exactly that change during the audit and the existing test caught it.

**If it turns out forgeable:** store both (`observed` + `claimed`) in a new column rather than
reinterpreting `accepted_ip`, so historical records keep their meaning.

---

## 4. 🟡 `core/caption_output.py` gates nothing — an unreachable content-safety check ✅ DONE

Wired 2026-08-13 (`social_job._publish_verdict`). MISSING_LICENSE blocks as of 2026-08-14
(`require_license=True` on the publish path) — decided before social credentials land.

It parses the **social-caption-v5** JSON contract. The live path is
`social_job._caption_for → clip_select.parse_title_output`, whose prompt returns
`{title, hashtags, description}` — no `status`, no `flags`. They are not compatible.

### Option A — move the caption path onto the v5 prompt  ⭐ **RECOMMENDED, but not urgent**

Josh's master prompt (`docs/josh-social-caption-master-prompt-2026-08-11.txt`) is already the v5
register. Switch `generate_titles` to request the v5 JSON contract, then gate with
`gate_caption`.

- **Pro:** turns on real content safety, and unifies two prompt formats into one.
- **Cost:** a prompt change plus parser swap, ~half a day, and it changes published copy — so it
  wants a review pass on sample output before it ships.
- **Timing:** nothing publishes today (no IG/TikTok creds), so this can land safely *before* creds
  arrive. **That is the ideal window and it closes the moment publishing goes live.**

### Option B — delete the module

Honest, and removes a false sense of safety. But it throws away working, tested gating logic that
becomes valuable the moment publishing is real.

**Recommendation: A, scheduled before social credentials land.** Until then it is correctly
documented as unconnected.

---

## 5. 🟡 `seo_hard_failures` blocks nothing

**Today.** No caller. `jobs/article_job.py` imports only `is_duplicate` and `verdict`. The only
thing asserting otherwise was a **test class name** — `"Tests for
core.qa_gate.seo_hard_failures() integration"`.

### Options

- **A ⭐ — wire it as a WARNING first.** Log hard failures on every article publish for two weeks
  without blocking. Then look at the rate: if it is near zero, promote it to a block; if it fires
  constantly, the checks are miscalibrated and blocking would have halted content.
- **B — wire it as a block now.** Risks stopping the article pipeline on rules never validated
  against real output.
- **C — delete it.**

**Recommendation: A.** It is the only option that produces the information needed to choose between
B and C, and it cannot break anything.

---

## 6. 🟡 `abstain_threshold` — a per-tenant field shadowed by one deployment-wide value

**Today.** `core/tenant_settings.KbSettings.abstain_threshold = 0.35` is **read by nothing**. The
live value is `app.config.ABSTAIN_THRESHOLD` (env, default **0.71**, "calibrated via app.eval, 94%
sep"), read at `app/answer.py:110` and `:164`. The two disagree by **2×**.

⚠️ **Do not resolve this by wiring the tenant field.** 0.35 is half the calibrated threshold; the
assistant would start answering where it currently abstains, degrading grounding — the opposite of
what the setting appears to promise.

### Options

- **A ⭐ — delete the tenant field.** One deployment, one calibrated value. Matches the
  `DEFAULT_ADMINS` precedent, where the fix was to collapse to a single path and delete the
  duplicate.
- **B — make the tenant value an override that DEFAULTS to the env value** (`ts.kb.abstain_threshold
  or settings.ABSTAIN_THRESHOLD`), and change the seeded default from 0.35 to 0.71.
  Only worth it if a second tenant will genuinely need a different threshold.

**Recommendation: A** unless multi-tenant is imminent, in which case **B with the default
corrected**. Either way the 0.35 must go — it is a trap for the next reader.

---

## 7. 🔴 Pre-production gate — profit readable by `quoting_view` / `estimating_view` ✅ DONE 2026-08-14

Closed: `api.routes.estimator._public_estimate` strips profit/margin/commission and internal
calc_lines on every read unless the caller holds `estimating_manage`. Persist is unchanged.

---

## 8. 🟢 Small / low-risk

| Finding | Proposal |
|---|---|
| `broll.query_auto` has no reader — `render_job` always derives the keyword | Either honour it (~3 lines) or delete the field. **Delete** — nothing has ever set it to false. |
| 7 tenant-settings knobs with UI writers and no readers (`kb.faq_policy`, `marketing.publish_cadence_days`, `marketing.seed_pct`, `marketing.royalty_free_music_catalog`, `marketing.caption_prompt_version`, …) | Each is a small UI promise nothing keeps. **Audit as one batch**: wire the ones that matter, delete the rest from the screens so the UI stops claiming them. |
| `platform_config` is untenanted, and `EMAIL_HTML_HEADER` is prepended to every outgoing email | A second tenant's admin could inject HTML into tenant 1's customer emails. **Inert while single-tenant.** Add `tenant_id` to the PK, or gate the global keys on `platform_admin`, **before onboarding a second tenant.** |

---

## Suggested order

1. **Item 7** before anyone outside the current group sees the tool — it is the only one with a
   live confidentiality consequence.
2. **Item 1 (Option A)** — it silently loses customer content and has already cost 277 rows once.
3. **Item 4 (Option A)** — the free window closes when social credentials arrive.
4. **Item 2 (Option A)** — cheap, and prevents an hour of wasted compute per misclick.
5. **Item 3** measurement, **item 5** warning mode, **item 6** deletion — all low-risk cleanups.
6. **Item 8**'s `platform_config` fix is gated on the second tenant, not on time.
