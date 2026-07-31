# CONTINUATION — 2026-07-30

**HEAD `e97686b`, pushed, CI green, deployed `platform:60a06a9`** (e97686b is docs-only).
Prod migrations applied through **0051**. Working tree clean.

---

## §0 — THE HEADLINE: THE OVERHEAD MODEL IS NOT SETTLED, AND TWO INDEPENDENT REVIEWS SAY THE
## ANALYSIS BEHIND IT WAS CIRCULAR

Jon sent the day's overhead analysis to **ChatGPT and Grok** for adversarial review because
this assistant "keeps inventing and missing things." Both reviews are saved verbatim at
`~/perkins-corpus/ai-reviews/{gpt_review.txt,grok_review.txt}` with the exact brief at
`~/perkins-corpus/ai-reviews/brief.md`. **Read them before touching overhead.** They agree on
the big things and Grok's is the sharper of the two.

### What they overturned — each independently re-verified in this session

**1. "The four rates are just crew size × per-man-day" is FALSE for installs.**
This assistant put `$210/man × 5-man demo crew = $1,050/day = his emailed demo rate exactly`
in a client email draft as the convincing evidence. Grok killed it: if rates were
`per_man × crew`, the demo/install ratio *must* equal 5/3 = 1.667. Verified here:

```
demo/tile    = 1050/745 = 1.409   NOT 1.667
demo/shingle = 1050/700 = 1.500   NOT 1.667
demo/metal   = 1050/850 = 1.235   NOT 1.667
```

It holds for demo alone and coincidentally. **Decoration presented as load-bearing.**

**2. Tim's own rates UNDER-RECOVER his own stated burn.** Nobody had checked this. Under his
stated "1.5 crews (one demo + one other)", his emailed rates collect:

```
0.5 x 1050 + 1.0 x 745 (tile)    = $1,270  vs $1,470/day  ->  -$200/day  (-13.6%)
0.5 x 1050 + 1.0 x 700 (shingle) = $1,225  vs $1,470/day  ->  -$245/day  (-16.7%)
0.5 x 1050 + 1.0 x 850 (metal)   = $1,375  vs $1,470/day  ->   -$95/day   (-6.5%)
```

Grok: *"the single most important arithmetic fact in the file."* His four numbers and his
$1,470 burn cannot both be right.

**3. THE LARGEST CONCEPTUAL HOLE — parallel-job double counting.** The branch burn is **per
branch calendar-day, not per job-day**. Tim's sheets are single-job calculators that silently
assume the job owns the day. At his own 1.5 concurrent jobs, charging each job a full day of
burn collects **$2,205/day against a $1,470/day office — +50% over-recovery**. The estimator
has no rule for this. Neither model under discussion addresses it. *This was missed entirely.*

**4. Productivity error dwarfs the entire rate debate.** Metal: sheet says 5.5 sq/day, his
actual jobs say 8.0 — a **45%** error in days, hence 45% in overhead. The rate-model argument
that consumed the session moves metal by **~3%**. Grok: *"sweating the 3% while the 45%
elephant sits in the room."*

**5. The validation was circular and the metal result is unusable.** Sold prices already embed
Tim's own overhead assumption, so matching them proves `our OH + our profit ≈ his OH + his
profit` — passable with wrong OH and compensating profit. The "+0.8% metal" figure rests on
**n=3 homes priced at 2024 levels** against a 2026 benchmark. Both reviewers say withdraw it.
Grok flagged motivated reasoning: the comparison table makes `$210/man` look best, and $210 is
also the config's pre-existing assumption — *"convenience, not evidence."*

**6. MIAMI IS THE LEAD FINDING, NOT A FOOTNOTE.** Both reviewers independently say this should
have led. Miami burns **$4,257/day (2.9× Jupiter's $1,470)** and is priced on a flat
**$1,400/day** with **Jupiter's identical four roof-type rates**. It recovers roughly **1/2.9**
of the office it should. Tim: Miami "has literally lost money or broken even every quarter
since Q2 2024." ChatGPT: *"catastrophic mispricing risk… directly explains losing money."*
Grok: *"the smoking gun."*
⚠️ Grok's explicit warning: **do NOT fix it by scaling Jupiter's four rates by 2.9** — that
preserves the folklore ratios and multiplies them. Use flat branch `$4,257 × days` until a
Miami breakdown exists.

**7. The only non-circular test nobody proposed: the RECOVERY IDENTITY.**
`Σ(OH charged across a month) ÷ (1,470 × working days) ≈ 1.0`. Independent of sold prices
entirely — uses accounting burn and estimator-charged days. **This is the gold standard test
and it has never been run.**

---

## §1 — WHAT IS ACTUALLY TRUE ABOUT THE ESTIMATOR (verified, survives review)

**Cost and materials reproduce Tim's four sheet quadrants EXACTLY.** Checked line by line
against the live Google Sheets, 25 SQ, per square:

| quadrant | items | L&M | overhead |
|---|---|---|---|
| FBC sloped | 5 roof types | **0.0%** | **0.0%** |
| HVHZ sloped | 5 roof types | **0.0%** | **0.0%** |
| Low slope | 8 systems | **0.0%** | **0.0%** |

His own worked example end-to-end: his sheet **$18,625**, ours **$18,475** (**−0.8%**).
The −0.8% decomposes fully: his example cell uses $125/sq shingle OH while his own OH table on
the same tab says $105 (his sheet contradicts itself); profit $110 vs $100 (our size-sliding
curve at 25 SQ, converges at 29+); plus a $100 PM-incentive line we add and he doesn't.

⚠️ **A mid-session error worth remembering:** this was first reported as "our costs run +10–26%
ABOVE his." That was a comparison mistake — our *all-in* cost/sq against his *base-cost-only*
column. `base_cost_lm` is $420/sq against his $420. The apparent gap was his own project-level
fees (delivery $650, bonus $1,350, permit $500), which his sheet charges on separate lines.

**Jon's directive on the model (2026-07-30):** *"the sheets have his old formula for per sq by
roof type but he uses per day by roof type and that's what we need to achieve."* Tim confirms
the sheets are legacy: *"Before I started using 'days' for more OH accuracy we were using the
tab on the sheets for OH Metrics (which are still a nice, loose guide, but not as accurate)."*
⚠️ This contradicts two earlier instructions in the same conversation ("go with uniform
pricing", and before that "not make it uniform"). **Do not act on any of the three without
re-confirming.**

---

## §2 — VERIFIED SOURCE FACTS (all read from source, not inferred)

**Tim, 2026-07-30 08:30:** Jupiter daily OH **$1,470**; Miami **$4,257**. "My assumption is to
have 1.5 crews on any given day (one demo crew and one other crew)." Miami needs 4 crews/day
min. OH Metrics tab = the older, less accurate method.

**Tim, 2026-07-30 11:40:** the OH Metrics screenshots were **MIAMI**. "The numbers I provided
you are what I use for Jupiter and what any franchisee should use." **Shared the Jupiter OH
sheet**; will not share Miami's (it lists salaries).

**Tim, 2026-07-24:** per-day rates BY ROOF TYPE — tile $745, shingle $700, metal $850,
demo/dry-in $1,050.

**His OH Metrics tab (Miami, legacy):** formula in every cell is
`OH/sq = (daily OH / men) × crew_size / squares_per_day`. Three bases $460@9men, $345@12men,
$275@15men — all resolve to **~$4,140/day**. Crew sizes from his own columns: removal /
demo-dry-in / SA underlayment = **5 men**; every install = **3 men**. Sheet productivity: tile
8 sq/day, shingle 25, metal 5.5, barrel 4.

**His Jupiter "2026 OH Average" sheet (NEW, `1V3uGnb57oo5Kh8IZk7fJSsjjakAmdVeejPisAIouJGc`):**
logs men on site daily — **157 days, mean 6.17, median 6, range 1–12**. His own monthly
averages: 6.8, 5.8, 4.2, 4.8, 6.8. ⚠️ Row with value **968** is a totals row — exclude it or
the mean reads 12.25.

**His actual day counts (30 homes) imply:** tile 7.1 sq/day, shingle 18.8, metal 8.0.

**Sold $/sq, RE-ROOFS ONLY, from `scripts/sold_price_trend.py`:**
2026 tile $1,100 (n=45) · shingle $689 (n=37) · metal $1,252 (n=46).
2024 tile $1,426 · shingle $757 · metal $1,697 (2024 was the spike).

**Sheet IDs:** sloped `1qxfKRRvmQS_NYu3AE2KQgek421Wzftu3xVmGECFH-ig` (tabs: Tim (HVHZ), FBC
(Palm/Lee/St. Lucie), Custom Tile Calc, Marco, Josh, **OH Metrics**, Jupiter) · low-slope
`1hTGWCWzIVLgWwNFln_AYBnEcKkj0tLbaZiv82zHXWWQ` · Jupiter OH `1V3uGnb…` · OH Breakdown (copy)
`1dTn_Qo2A53_1cwAn_L37JFNNjPtwK8j7RBzzAWdiT6A`.
Read via perkins-deploy SA + domain-wide delegation impersonating `tim@perkinsroofing.net`.

---

## §3 — SHIPPED AND DEPLOYED TODAY

Five commits, `ba2f4a1 → e97686b`, all pushed; CI + deploy green; `platform:60a06a9` live on the
API service **and** the Cloud Run jobs.

1. **`0f72e99` fix(wp-plugin)** — the uploadable JSON-LD plugin **did not parse** (unmatched
   brace, undefined `PERKINS_JSONLD_POST_TYPES`, and the post-type fix never applied). It is
   now GENERATED from the mu-plugin with `tests/test_wp_plugin_parity.py` pinning them
   together. ⚠️ Staging runs the **regular plugin**, not a mu-plugin — installing the mu-plugin
   alongside it would duplicate schema on ~60 articles. **Uploaded and verified:** v1.3.0
   active, `_perkins_jsonld` + three `rank_math_*` keys now registered on `avada_portfolio`
   (all four absent before), meta write round-trips, live article still renders exactly 2
   schema blocks.

2. **`7dccf47` feat(portfolio) — THE GPS PRIVACY CONTROL.** CompanyCam burns the capture GPS
   into image **PIXELS** (`Sep 1, 2023 at 12:12:36 PM / 25.858694° N 80.120019° W`, ~0.1 m).
   `core/pii.py` is text-only, so `no_pii` returned **ok** on a gallery that would have
   published a client's exact building. Nothing was ever exposed (0 articles embed CompanyCam
   media; the nine `/portfolio/` pages use 2023 WP-hosted photos; `portfolio_curation` had 0
   rows). Fix CUTS the bottom 20% (band measured, not guessed) and requires every published
   `<img>`/`<video>` src+poster to be WP-hosted (`media_sanitized` blocker). Four defects were
   found and fixed inside this work: videos bypassed the check entirely; raising `STAMP_BAND`
   would silently keep old crops (band now in the filename); sanitizing only at publish left
   the SPA publish button permanently disabled; and attachment reuse never matched because the
   host rewrites uploads to `-scaled.webp` (live proof: media 10466 then 10467).

3. **`e702b27` feat(quoting)** — accent line items selectable in the SPA. `extra_line_items` was
   priced end to end and `/estimator/rates` already returned the catalog, but `Quoting.tsx`
   never rendered a control. Live config has **7** items, not the 3 in `core/_legacy_rates`.

4. **`89472e6` test** — the last five `drop_all` teardowns converted to row wipes. Root cause is
   in-repo: pytest imports every module before running any, so a `drop_all` tears tables out
   from under modules that create at import and only DELETE rows. (Backlog said 4 files; it is 5.)

5. **`31c62a9` + `60a06a9` + `e97686b`** — building numbers stripped from published scope lines;
   `gate_failures` persistence (migration 0051); and engineering rules R7–R10.

**Migration 0051 (`gate_failures`)** — applied to the live DB and verified (both tables, both
columns, both partial indexes) BEFORE the code that reads them deployed. Persists WHY a project
or article was refused. ⚠️ A refused **article** was previously written NOWHERE
(`_publish_fields` only runs when compliant), so its draft was discarded and the reasons
survived as one log line. `NULL` = never gated, `[]` = gated and clean — deliberately distinct.

---

## §4 — OPEN, IN PRIORITY ORDER

1. **MIAMI.** Priced at ~1/3 of its burn with Jupiter's rates. Both reviewers call this the
   lead item. Do **not** scale Jupiter's four rates by 2.9. Interim: flat `$4,257 × days`.
2. **Run the recovery identity on Jupiter.** `Σ OH charged ÷ (1,470 × working days)`. The only
   non-circular test. Never run.
3. **Define the parallel-job rule.** Branch-day burn vs per-job day charging; at 1.5 concurrent
   jobs the current shape over-recovers **+50%**.
4. **Replace sheet productivity with empirical sq/day** (metal 8.0 not 5.5, shingle 18.8 not
   25). Dominates everything else.
5. **`overhead_basis` is still `branch` on all three branches** with a flat $1,400/day. The
   per-day-by-roof-type rates are stored but INACTIVE. Jon's stated target is per-day-by-roof
   -type; nothing has been flipped.
6. **`office_daily_overhead` is stale**: config 1400/4250 vs Tim's stated 1470/4257. `naples`
   still carries Jupiter's 1400 and has `office_men = None`.
7. **Tile prices +10–12% under EVERY overhead model** — not an overhead problem. Unexplained.
8. **Email to Tim is DRAFTED, NOT SENT** (`jon@degenito.ai`, to tim, cc marco+josh, subject
   "The estimator now reproduces your sheets to the dollar…"). ⚠️ **It contains the refuted
   `$210 × 5 = $1,050` claim and must be corrected before sending** — see §0.1. It should also
   gain the under-recovery arithmetic (§0.2) and the parallel-job question (§0.3).
9. **Portfolio still blocked on `permission_property`** — Tim has not answered which projects
   have client clearance. 8 of 13 projects also have zero Knowify scope (6 whose search term
   matches nothing; 2 correctly refused as ambiguous). Only 5 are curatable.
10. **TPO sold history is unusable** — "TPO Maintenance" at $65/sq averaged with a real
    EverGuard re-roof at $1,796/sq, and Fleeceback jobs booked as qty 1. Work-type
    contamination, **not** a unit bug (an earlier claim of a "20× unit error" was wrong).
    Tile/shingle/metal are clean.

---

## §5 — GOTCHAS (new ones from today, all learned the hard way)

- ⚠️ **`pgrep -f "<pattern>"` matches the polling shell's own command line.** Six waiters this
  session deadlocked forever because their `cmdline` contained the very string they grepped for.
  Same family as the documented `pkill -f` self-kill. Poll a status FILE, or use `kill -0 $PID`.
- ⚠️ **The session scratchpad is wiped on restart.** Two long AI reviews and every analysis
  script were lost mid-flight. Durable work goes in `~/perkins-corpus/…`, and long external
  jobs get `setsid nohup` so a restart cannot kill them.
- ⚠️ **Never edit the tree while a long gate runs** (R7). Coverage maps line numbers from the
  file on disk at report time; three consecutive 40–60 min runs were invalidated this way.
- ⚠️ **`cmd | tail -n` returns tail's exit code**, so a failing suite reports success.
- ⚠️ Console output is truncated — never copy an identifier out of a printed table. A
  "CompanyCam URL expired" conclusion came from a URL cut at 70 chars.
- ⚠️ `sold_price_trend.py` already filters to re-roofs for tile/shingle/metal (n=45/37/46);
  TPO is the one series it does not clean.
- Migrations are applied MANUALLY: `MIN_MIGRATION=0051 .venv/bin/python
  scripts/apply_migrations_connector.py`. It strips comments before splitting on `;` — do not
  hand-roll that (a comment containing a semicolon will split mid-statement).
- Cloud Run request timeout is **900s**, so per-photo network I/O inside `PUT /curation` is a
  latency concern, not a failure mode.

---

## §6 — STANDING RULES ADDED TODAY (`docs/ENGINEERING_RULES.md`)

**R7** never edit the tree while a long gate runs · **R8** verify before asserting · **R9**
delegation is best-effort, the work is not (four review agents returned idle with zero output;
the R2 review was ultimately done inline and labelled as self-review) · **R10** corpus-validate
any heuristic touching published text, and refuse rather than guess on ambiguous input.

---

## ARCHIVE DIRECTIVE (standing, performed for this doc)

When writing a session continuation, move the OLDEST top-level `CONTINUATION-*.md` into
`docs/continuations/` (keep only the latest 3 at top level), fix every inbound link to the moved
file, refresh the docs index's "most recent" pointer, and update related docs.
**Performed:** `CONTINUATION-2026-07-28-pm.md` archived to `docs/continuations/`, its `README.md`
link repointed, and "Most recent" moved to this document.
