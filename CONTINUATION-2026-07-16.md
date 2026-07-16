# Continuation — 2026-07-16 (article grounding, audit trail, claim verification)

**Branch:** `main`, pushed, clean. HEAD `23572e5`. Suite **4000 passed / 8 skipped / 0 failed**.
**Migrations applied to prod:** 0036 (audit_log), 0037 (articles.updated_at), 0038 (platform_audit_log).

---

## 1. THE ONE THING THAT MATTERS

Articles were **~90% invented**. Measured: 45,945 published words rested on **4,564 words** of
retrievable source. Not a model failure — **starvation**: the generator retrieved
`hybrid_search(k=4)` and truncated each chunk to `[:300]`, so ~200 words of Tim went in and
1800+ were demanded out. The expansion prompt then said *"Rewrite it LONGER … add specific
costs"* with no grounding requirement — an explicit instruction to fabricate prices.

**Fixed (`b9a0b65`)** — `jobs/article_job.source_transcripts()`: retrieve wide (k=40), map each
hit onto the **topic window** it sits in (`content_graph` kind=topics, 8,724 rows: a topic's
start → the next topic's start), return every chunk in that window. Topic slices, **not whole
videos** (Jon's call, correct — "How to Install a Metal Roof" is 14,834 words of which ~3 min is
on point).

| | before | after |
|---|---|---|
| Tim's words given to the writer | ~200 | **4,500–19,300** |
| article ÷ source | ~10× invented | **0.11–0.50×** |
| prose | "peace of mind", "superior protection" | termination bars, drive pins, 45° laps, Polyflash 1C |

**This upstream fix is what actually works.** Everything else is a check on the remainder.

---

## 2. STATE RIGHT NOW

### Articles: 31 in DB, all 31 linked to WordPress
- **27 new drafts + 4 live posts** (7887, 7890, 7896, 7897). **123 pre-existing published posts
  untouched** — that was Jon's guardrail and it held.
- WP site is `https://1205166.us6.myftpupload.com` (`jhk.14f.myftpupload.com` redirects to it).
  **Only ONE site exists** — production (`perkinsroofing.com`) is on AWS and is NOT reachable
  from this repo. See [[perkins-wp-creds]] memory.

### ⚠️ A REGEN WAS RUNNING WHEN THIS WAS WRITTEN — CHECK IT FIRST
18 articles, two halves, launched ~00:14. Logs:
```
/tmp/claude-1000/-home-jon-projects-perkins-roofing-video-archival/6fc87d04-.../scratchpad/regen3_a.log
/tmp/claude-1000/.../scratchpad/regen3_b.log      # A3 1/9, B3 1/9 done at hand-off, 0 errors
```
The scratchpad is session-scoped and **may be gone**. If so, just re-check state from the DB
(§5) and re-run what still fails. Nothing is lost — regen is idempotent.

### Rank Math: 13/31 passing (was 31/31)
**That drop is correct, not a regression.** The old 31/31 was manufactured — literal
`wall flashings wall flashings wall flashings` filler blocks plus one stock image
(`perkins-roofing-seo-guide.jpg`) reused across unrelated posts, injected by
`scripts/repair_article_seo_aio.py` (deleted in `d29ec11`). The spam is gone, so the score fell.

---

## 3. THE UNFINISHED THING: `rm_kw_density`

**Do not tune this on n=2. I did that three times.**

| attempt | prompt said | result |
|---|---|---|
| 1 | "repetition past ~1% is over-optimisation" (ceiling only) | 0.16–0.48% — under the floor on 12/31 |
| 2 | ratio **+ "~18-22 times in a 2,000-word article"** | model anchored on the count: 23 into a 1,440-word piece = **1.60%** |
| 3 (current) | pure ratio, worked at two lengths | acrylic **0.96% IN BAND** ✓ · dealing-with-insurance **0.22%** ✗ |

**The measured diagnosis for the failure case** (`dealing-with-insurance-denial-for-old-roofs`,
1834 words):

| candidate keyword | words | occurrences | density |
|---|---|---|---|
| `dealing with insurance denial` | 4 | 5 | 0.22% |
| `insurance denial` | 2 | 6 | **0.22%** ← shortening does NOT help |
| `insurance` | 1 | 56 | 2.67% |

The prompt asked for ~17 mentions; it wrote 5. **It ignored the ratio by 3×** — almost
certainly because the same prompt also says *"at most two headings"* and *"use semantic
variants for everything else"*. **Contradictory pressure in my own prompt** (`_expand`/refine
in `jobs/article_job.py`, search `KEYWORD DENSITY`).

**Do NOT "fix" this by picking a keyword that hits the band.** Measured: the candidates that
land in band are `'in'`, `'new'`, `'season'`, `'business'`. That is gaming the metric — the
exact thing this whole day was spent undoing.

**Next step: let all 18 finish, measure all 18, then decide.** Possibly the honest answer is
that awkward 4-word slug-derived keywords cannot hit density without absurd prose, and the
model is right to refuse.

---

## 4. LAWS LEARNED (violating these is how today went wrong)

1. **Token presence is not claim support.** "Tim recommends replacing all shingles every 10
   years" is 100% his vocabulary and 100% invented. Any vocabulary-overlap check has a low
   precision ceiling *by construction*. → [[grounding-vs-vocabulary]]
2. **A noisy detector must never drive automated edits.** I shipped a guard that told an LLM
   reviser to strip 'Costs', 'Risk', 'Value' (Title-Case headings + plural mismatch). Articles
   got worse, timed out at 30 min, and every check reported success. Now report-only (`93dcf0a`).
3. **Use the council BEFORE building.** GPT-5 + Grok, independently, in ~90 seconds, killed
   both the guard and my *planned fix for it*. → [[use-the-council]]
4. **A deterministic fix can satisfy its checker while destroying meaning.** Four instances in
   one day: two title trimmers cut mid-clause; a density de-repeater rewrote the keyword inside
   `<img alt>`; my own guard's `_normalise` deleted hyphens and reported "L-flashing" as a
   hallucination when Tim says "L flashings". **Re-score ALL checks after any fix, and read the
   output.** → [[article-regen-bugs]]
5. **Measure the detector, not the flags.** "Flags == 0" is what got a guard tuned on 3
   hand-picked articles and enforced on 28 nobody had measured.
6. **I was wrong out loud 5+ times today** (the "blind" critic — I passed `db=None`; "Polyblast
   is fabricated" — Tim says it, video `WK6ufUjnicc` t=57; route registration — FastAPI 0.139
   `include_router` is lazy so `app.routes` holds `_IncludedRouter` wrappers; the guard's own
   false positives). **Every one died to checking, none to reasoning.** Verify the real call
   path before calling anything broken.

---

## 5. HOW TO GET BACK IN (verified recipes)

```bash
cd /home/jon/projects/perkins-roofing/video-archival

# Cloud SQL proxy (no binary on this host by default — it was downloaded to the scratchpad)
curl -sL -o /tmp/cloud-sql-proxy \
  https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.14.1/cloud-sql-proxy.linux.amd64
chmod +x /tmp/cloud-sql-proxy
/tmp/cloud-sql-proxy video-archival-and-content-gen:us-central1:video-archival-and-content-gen-pg --port 5432 &

set -a; source .env; set +a
export DB_URL="postgresql+psycopg://app:$(gcloud secrets versions access latest --secret=db-password)@127.0.0.1:5432/perkins"
export WP_APP_PWD="$(gcloud secrets versions access latest --secret=wordpress-app-password)"
export LLM_BACKEND=vertex EMBED_BACKEND=vertex PERKINS_ENV=prod
unset GOOGLE_APPLICATION_CREDENTIALS      # .env points it at infra/vertex-dev-sa.json, which does NOT exist and overrides ADC

.venv/bin/python -m jobs.regen_articles_seo --slug <slug>     # ~12-15 min/article, ~$0.33
```

**Gotchas that cost real time today:**
- `articles` is **RLS-protected**: `session.info["tenant_id"] = 1` or every query errors with
  *unrecognized configuration parameter "app.tenant_id"*. Only tenant 1 exists.
- **`ALTER TABLE articles` needs ACCESS EXCLUSIVE**, and `regen_articles_seo` holds a
  transaction open across its ~12-min LLM call (`idle in transaction`). The ALTER queues, and a
  *queued* ACCESS EXCLUSIVE blocks every later query. **Killing the migration client does NOT
  kill the server-side statement** — it sat as a zombie that would have stalled both batches.
  Cancel with `pg_cancel_backend`. **Apply DDL only when regen is stopped.**
- `pgrep -f "regen_articles_seo"` matches **this shell's own wrapper**. Use
  `ps -eo cmd | grep "[r]egen_articles_seo" | wc -l`.
- WP: `.env WP_PWD` is the **web login**; REST needs `WP_APP_PWD` from Secret Manager
  (`wordpress-app-password`). 401 on REST with the web password is *by design*.
- `AUDIT_ENABLED=0` under pytest (`tests/conftest.py`): audit writes open a second connection
  so rows survive a rollback — fine on Postgres, and SQLite (single-writer) instead waits out a
  lock, which turned a ~6-min suite into >30 min.

---

## 6. WHAT'S BUILT (all pushed)

| commit | what |
|---|---|
| `d29ec11` | killed the rank-math gaming (spam script deleted), real images (video thumbnails), honest titles |
| `b9a0b65` | **the grounding rework** — topic-slice retrieval. The real win. |
| `d269c07` | audit trail: middleware over all 86 mutating endpoints + ORM before/after (migration 0036) |
| `93dcf0a` | grounding guard demoted to report-only |
| `2b86f64` | `articles.updated_at` with `onupdate` (0037) — provenance on all 7 write paths |
| `191c739` | platform audit trail (0038), tiered grounding severity, density band |
| `1122504` | density is a ratio, not a count |
| `23572e5` | typed claim-grounding — **measurement layer, gates nothing** |

### Audit trail (live in prod, verified)
- `AuditMiddleware` → one row per mutating request (actor, action, entity, status, request_id).
  Written **after** the response in its **own transaction** so a 403/500 survives the rollback.
- `core/audit_orm.py` → SQLAlchemy `before_flush`/`after_commit` = **before/after values for
  revert**, on every code path, not per-route (86 endpoints; #87 would be forgotten).
- `GET /audit?scope=tenant|platform|all` — admin-only (`manage_config`), joins on `request_id`.
- **Platform rows are a SEPARATE table on purpose.** `audit_log` is RLS tenant-scoped; a
  nullable tenant_id would need `OR (platform_scope AND tenant_id IS NULL)`, putting "who was
  granted platform_admin" behind a GUC the app sets on itself inside the table every tenant
  reads. Merging buys one query; getting it wrong is a breach. Union at the **read** layer.

### Claim-grounding (`core/claims.py`, `core/claim_verify.py`, `scripts/eval_claims.py`)
Spec: **`docs/superpowers/specs/claim-grounding.md`** — read it before touching this.
- **Never ask a model "does this support the claim?"** The model reports what a span *states*
  into typed slots; **code** compares. That is the whole design.
- adversarial set **13/13**; extraction **698 candidates / 31 articles** — `modal` is **43%**,
  the over-firing shape, and the type both reviewers said must never gate.
- **Gates nothing, edits nothing** until precision is hand-labelled.

---

## 7. NEXT, IN ORDER

1. **Check the regen** (§2). Measure all 18 for density; **only then** touch the density prompt.
2. `rm_external_link` (2 articles): the honest fix is already there — **Tim's own source video
   is the external citation**. Nothing in the generator guarantees an `<a href>`; the YouTube
   citation should be one. (The spam script faked this with a NOAA link.)
3. Remaining title checks (`title_power_word` ×4, `title_number` ×2, `title_kw_position` ×2).
   **Never invent an item count** ("8 Signs") unless the article really is a listicle.
4. **Hand-label `scripts/eval_claims.py --verify` for precision per claim type** (~$1 for all
   31). Nothing gates until that number exists.
5. **Evidence-first generation** — both reviewers, independently: post-hoc verification fights
   entropy. The writer should emit claim + source span + prose. **Council-review that design
   before coding it.**
6. 4 stray trashed WP posts (7876 "Perkins API test", 7878, 7880, 7882) — ours, left alone.

**Cost, measured from Cloud Monitoring (not estimated):** 12.09M Vertex tokens for the day =
**~$19** across ~58 article generations, **~$0.33 each**. `gemini-2.5-flash` $0.30/M in,
$2.50/M out — **output is 92% of spend**. The 7-13k-word transcripts are input at 1/8th the
price, so **grounding is nearly free; the writing is what costs.**

---

## Archive directive (standing, performed this session)
Keep only the latest 3 `CONTINUATION-*.md` at top level; the oldest moves to
`docs/continuations/`, inbound links get fixed, and the docs index's "most recent" pointer is
refreshed. **Done this session:** `CONTINUATION-2026-07-11-pm.md` → `docs/continuations/`.
