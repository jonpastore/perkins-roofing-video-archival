# Continuation — 2026-08-11 (evening)

Follows [CONTINUATION-2026-08-11-pm.md](docs/continuations/CONTINUATION-2026-08-11-pm.md). That session shipped five
PRs; this one **reviewed them adversarially and found eleven real defects, three of them mine from
the same day**, then applied Jon's answers to six open questions.

---

## §0 START HERE — STATE

**Three commits on `main` are UNPUSHED and NOT DEPLOYED:**

```
ae949d3  fix(estimator): refuse a geocoded city centroid, and set Wendy's gallery bounds
4988fa7  fix(security): one upload could stall the whole API; internal pricing was on a public page
13366a8  fix: R2 review findings — a 500, a truncated link, and a stale answer on the wrong contract
```

Prod is running the earlier state (revision `api-00254-nvk`, created 21:31, from the last pushed
commit). **So every fix below is written and green but NOT live.** Decide whether to push+deploy
before doing anything else.

⚠️ **Jon's working tree has SIX uncommitted files** — `core/article_criteria.py`,
`core/article_repair.py`, `jobs/article_job.py`, `scripts/backfill_wendy_compliance.py`,
`tests/core/test_article_{criteria,repair}.py`. They are his in-progress Wendy "Related links x3"
fix. **Leave them alone.** I swept them into a commit with `git add -u core/` and had to reset and
recommit to get them back out — never stage by directory in this repo.

Full suite green: `pytest exit 0` captured directly, **0 FAILED**, 5 skips with stated reasons.

---

## §1 THE PATTERN THIS SESSION — EVIDENCE THAT CANNOT ANSWER THE QUESTION

The morning's pattern was "a write path with no reader". This session's is subtler and cost more:
**I checked things three times with a method that could not have detected the failure**, and
reported the conclusion confidently each time.

| claim | what I actually checked | why it could not work |
|---|---|---|
| "CompanyCam tag filtering is broken — BLOCKER" | `?tag_ids[]=…&per_page=5` returned 5 photos with `tags: []` | `per_page=5` returns 5 either way, and tags are not inlined. **Never compared counts.** The filter works: 100 → 9. |
| "suite green, exit 0" | `pytest … \| tail -N` | a pipeline's exit code is **tail's**. It could never report a failure. |
| "Jon's files are untouched" | did not check | `git add -u core/` swept in four of them |

The fix in all three cases is the same: **check the thing that would change if you were wrong.**
Compare filtered against unfiltered. Capture `$?` before the pipe. `git log --name-only` after
committing. A test fixture in `tests/api/test_squares.py` had the same shape — no `location_type`
at all, so the geocode gate had nothing to look at and passed for the wrong reason.

---

## §2 THE R2 PANEL — WHAT IT FOUND

Ran architect + critic + code-reviewer + security (deepsec), all opus, on `a32de84..HEAD`. Every
finding was reproduced by executing the code before acting; one had already been fixed. **Three of
the four agents went idle without reporting and had to be chased** — do not assume silence means
"nothing found".

### Fixed in `13366a8`
- **CRITICAL** `lru_cache` memoised the RESULT but not the COMPUTATION. 4 concurrent cold requests
  each parsed the 22 MB tidal layer: **801 MB peak against a 1 GiB limit**. Locked; 250 MB.
- **CRITICAL** A thousands separator crashed the upload endpoint — `"Two story area: 1,250 sq ft"`
  raised `ValueError` out of an unguarded handler (**500** on any two-storey report over 1,000 sq ft).
- **HIGH** `adapters/llm.py` — the removed vertexai SDK **raised** on a blocked candidate;
  google-genai returns **None**, and `app/llm.py:57` calls `.find()` on it across ~35 call sites.
- **HIGH** `(?<![\w#])#\w+` counted a URL fragment as a hashtag, so a caption with 5 tags plus a
  booking link **truncated the link**.
- **HIGH** A stale salt-water answer could be frozen onto **another customer's contract** —
  `setSelectedPropertyId` had 6 call sites, `checkSaltWater` had 1.
- MEDIUM ×5 — prefilter mismatch with checker.js (Clewiston/Orlando read "no salt water"),
  COASTAL_TRIGGER comment/UI contradiction, address parser writing a wrong city, `fixes`/`problems`
  returned but never rendered, stranded punctuation.

### Fixed in `4988fa7`
- **HIGH, exploitable** `parse-roofr` was `async def` calling pypdf synchronously — CPU work **on
  the event loop**, with `uvicorn` started without `--workers` (one loop for the whole API) and
  `max_instance_count = 4`. Measured: a **44,594-byte** PDF → **32,000,003 chars, 40.5 s blocked**.
  A trickle wedges the platform for everyone. Now `run_in_threadpool` + bounded (60 pages/200k
  chars). **Residual: one page still costs ~9.5 s CPU** — off the loop, capped, behind
  `estimating_manage`.
- **CRITICAL** The public warranty page printed Perkins' internal per-square upcharge
  (`$45.00 per SQ`) and named Tim's proposal — from a provenance note I added the same day.
- **HIGH** The debug trace persisted where `sales` can read it. `_freeze_calc_breakdown` returned
  the snapshot **unmodified** unless the breakdown box was ticked (default off), and the strip sat
  inside that branch — so `calculation_trace` and per-line `explain` (profit_scale, pm_incentive)
  landed permanently in `quote_snapshot`, returned by `GET /quoting/proposals/{id}` under
  `quoting_view`, **which `sales` holds and `estimating_manage` it does not**.
- MEDIUM — `quoteWaterfront` only ticked ON (display right, price wrong); Roofr re-upload kept the
  previous roof's measurements.

### Checked and CLEAN (do not re-audit)
Jinja is genuinely `SandboxedEnvironment` + autoescape, no `|safe`/Markup around `metal_warranty`
or `scope_of_work`. No SSRF into geocoding (URL is a module constant, params encoded). No XSS sink
for `videos.description` (only a `<textarea>`). RLS/tenancy correct on all three new endpoints. No
prompt-injection path (the seeder reads a committed file, fails closed). CORS widened by exactly
one method. No secrets logged. The prod pricing-config rewrite: exactly one key differs per branch,
rates preserved, old versions retained.

---

## §3 JON'S DECISIONS, 2026-08-11 EVENING

| Q | Decision | State |
|---|---|---|
| Q1 competitor uplift rows | **Ask Tim/Marco/Josh** | Draft in Outlook, **UNSENT** — see §4 |
| Q2 Coastal auto-tick | **Keep it** | Done + geocode confidence gate (`ae949d3`) |
| Q3 where project pages live | **KEEP the nine `/portfolio/` pages** | ⚠️ NOT BUILT — publisher must move off the Avada CPT |
| Q4 videos per project | **Up to 4, fix the schema** | ⚠️ NOT BUILT |
| Q5 gallery bounds | **Max 20 hard, floor 1** | Done (`ae949d3`) |
| Q6 client permission | **All properties cleared, but MASK the address** — neighborhood or town/city, never the exact address | Largely already the design; one gap, see §5 |
| draft T&C row | **Delete** | Done — deleted from prod |

---

## §4 NEXT ACTIONS, IN ORDER

1. **Decide: push + deploy the three commits?** They are green and unpushed. `§6` has the commands.
2. **Send the Q1 email** (draft is in Jon's Outlook, unsent): asks Tim/Marco/Josh for FL approval /
   NOA numbers and test conditions for the Gulf Coast and Englert rows, or agreement to publish
   Perkins-only. Also asks Tim to confirm the warranty terms from his 5/26 proposal are current.
3. **Phase 1 — wire the tag reads.** Independent of every open question; unblocks the Building 77
   demo. `adapters/companycam.py:91` reads `raw.get("tags")`, **a key absent from every payload**,
   and `core/companycam/mirror.py:61` writes the resulting `[]` — that column has ALWAYS been empty
   and nothing reads it. Fetch with `?tag_ids[]=` instead. Put the tag ids in config, not literals.
4. **Q3 publisher rework** (~1 day) — hold until Wendy replies, in case her answer moves the target
   again.
5. **Q4 multi-video schema** — single `youtube_url` becomes a proper relation.

---

## §5 BLOCKED ON OTHER PEOPLE

- **Wendy** — the Q1 email above. Also still unanswered from the morning thread: nothing.
  Q3/Q4/Q5 are now answered by Jon.
- **Tim** — Q6 is answered in principle (all properties cleared, mask the address) but the three
  per-project permission flags `check_project` reads still have to be SET on each project.
- ⚠️ **Q6 GAP TO CLOSE BEFORE ANY PROJECT PUBLISHES: CompanyCam burns GPS into the PIXELS.**
  Masking the text is not sufficient. `core/portfolio_media.py:137` shows the burned-in stamp was a
  known issue; confirm the sanitiser actually covers it before publishing. The text side is already
  right: location links are built from the **city slug**, `portfolio_facts._address_number_risk`
  refuses any line opening with a street number, and project titles that read as a person's name
  are blocked.

---

## §6 COMMANDS

```sh
# push + deploy the three unpushed commits (deploy.sh REFUSES a dirty tree, and Jon's is dirty)
git push origin main
git worktree add -q --detach /tmp/deploy-wt origin/main && cp .env /tmp/deploy-wt/.env
cd /tmp/deploy-wt && bash scripts/deploy.sh && git worktree remove --force /tmp/deploy-wt
cd web && npm run build && npx firebase deploy --only hosting:app --non-interactive

# ⚠️ the suite's exit code, captured BEFORE any pipe
.venv/bin/python -m pytest tests -q -p no:warnings > /tmp/suite.log 2>&1; echo "EXIT=$?"
grep -cE "^FAILED|^ERROR" /tmp/suite.log      # expect 0

# prod DB (ADC is stale — --gcloud-auth borrows the CLI account)
~/bin/cloud-sql-proxy --gcloud-auth video-archival-and-content-gen:us-central1:video-archival-and-content-gen-pg --port 5432 &
export DB_URL="postgresql+psycopg://app:$(gcloud secrets versions access latest --secret=db-password)@127.0.0.1:5432/perkins"

# CompanyCam — ONLY the plural bracketed form filters. tag_id=/tags[]=/tag= are silently ignored.
export COMPANYCAM_PAT="$(gcloud secrets versions access latest --secret=companycam-pat)"
curl -s -H "Authorization: Bearer $COMPANYCAM_PAT" \
  "https://api.companycam.com/v2/projects/79260538/photos?tag_ids[]=26926152&per_page=500" | jq length
# Projects tag id 26926152 · ProjectsVideo tag id 26926154 · Building 77 project id 79260538
```

⚠️ `npm run build` is the gate, not `tsc --noEmit`.
⚠️ Commit hook needs `Refs #N <pct>%` / `Closes #N` / `No-Task: <reason>` ALONE on its line.
⚠️ **Never `git add -u <dir>`** — Jon's uncommitted work lives in `core/` and `tests/core/`.
⚠️ `session.info["tenant_id"] = 1` before the first query, or `platform_scope = True`.

---

## §7 PROD STATE CHANGED THIS SESSION (config/data, not code)

| what | change |
|---|---|
| `VIDEO_DESCRIPTION_PROMPT` | seeded, 9,544 chars (Josh's prompt, strict-5 hashtags) |
| `repair.roof_types` ×3 branches | + `metal_standing_seam`, `metal_5v_crimp`, `metal_corrugated`, `metal_tile` |
| `tc_versions` | **deleted** the empty `v0.1-DRAFT` row (id 2); terms resolve to Josh's 42,042-char doc |
| warranty plugin | **1.7.1** installed on staging |

---

## §8 ARCHIVE DIRECTIVE (STANDING — PERFORM ON EVERY CONTINUATION)

When writing a new session continuation/handoff `.md`: move the **oldest** top-level
`CONTINUATION-*.md` into `docs/continuations/` so only the latest **3** remain at top level, fix
every inbound link to the moved file, refresh the docs index's "most recent" pointer, and update
related docs.

Performed this session: `CONTINUATION-2026-08-04.md` → `docs/continuations/`; inbound links
repointed; README "most recent" pointer refreshed. Top level now holds **08-11, 08-11-pm,
08-11-eve**.
