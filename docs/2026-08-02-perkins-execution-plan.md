# Perkins — execution plan, 2026-08-02 (v2, post-ralplan)

**Status: PENDING APPROVAL.** Revised after a three-pass consensus review (planner → architect →
critic) that returned **REJECT** on v1. Every finding below was independently verified against the
code or the prod database before it was accepted into this document; the passes disagreed with each
other twice and were wrong twice, and both cases are recorded.

---

## §0 — Provenance, and what this plan cannot see

**v1's first line was false.** It claimed to be built from "every open Perkins task in Jarvis" —
true, and that was the defect. Jarvis is lossy in one direction: *anything learned and written down
but never filed as a task is invisible to a plan built from the tracker.* Three passes each found a
different instance of exactly that, which makes it a sourcing error, not three mistakes.

**This plan's input set is therefore: Jarvis ∪ the open sections of the current continuation docs ∪
`docs/PRODUCTION_CUTOVER_PLAN.md`.** Reconciling those is a step *in* the plan (§6), not a one-off.

**Known blind spots, stated so the next reader can attack them:** `docs/BACKLOG.md` (scoped, unfiled),
`docs/KNOWN_GAPS.md`, anything in a subagent transcript that never reached a file, and the eleven
cutover gates whose owners are not us.

---

## §1 — What the sweep established (unchanged from v1, still verified)

Six duplicate Jarvis project records became one, now named **`perkins-roofing-video-archival`** —
the repo — with all 63 open tasks re-filed **keeping their numbers** (idempotent `external_id` upsert, verified no duplicates);
the other five archived. **The naming rule is now enforced in code** so it cannot re-fragment:
`jarvis@b1add89` makes `memory-mcp`'s `add_task` derive the project from the git remote when none
is given, and warn (never silently override) when a caller names one that differs from the repo.
A convention in a doc would have been ignored by exactly the callers that caused the problem. **13 tasks closed as already-done**, each against the code
— #430/#449, #418, #385/#386, #320, #383, #445, #350, #351, #374, #377, #440, #376, #325. **8 marked
honestly partial.** **Two greps lied and were caught**: `#331`'s "solar" is solar panels as a roof
*feature*, not the Google Solar API; `#410`'s "placeholder" is prompt text, not the guard. A keyword
hit is not a done task.

**54 open**: 19 wait on a person (13 on Tim), 9 are Jon's decisions, 26 are buildable.

---

## §2 — THE LIVE DEFECT (found by the review, filed by it, not by the backlog)

Neither v1 nor the planner found this. The architect found it one layer above where the planner
grepped, and the critic then found that the architect's fix was aimed at the wrong layer.

**`web/src/pages/Quoting.tsx:699-704, 1203`** — when a measurement has `pitched_sq`/`flat_sq` NULL,
the SPA sends `num_squares = selectedMeasurement.total_sq`, and `total_sq` is **ambiguous**: Tim's
sheet means sloped-only, a RoofR transcription means pitched+flat. The flat box then falls through
to manual entry, and **`core/estimator.py:1373` is additive** — `total_sq = num_squares +
(flat_squares or 0)`. Fill the box and the flat area is billed twice; leave it blank and it is
billed once at the *sloped* rate with no flat line.

**Measured against prod, not asserted:**

| | |
|---|--:|
| measurements with a NULL split | **13 of 42** |
| estimates quoted off a NULL-split measurement | **10** |
| estimates actually at risk of a double-bill | **0** |

**Severity, honestly:** a latent trap, not an active fire. Nobody has typed into the flat box on a
NULL-split measurement yet. It is still customer money and it is silent, and this exact class has
reached a customer once before (`core/bid_project.py:318-324`: a 20+15 roof reported as 20 squares
against a total that priced 35 — 75% high, and it reached a customer through `project_snapshot`).

**The fix is server-side, not in the SPA.** `api/routes/estimator.py:275-282` already resolves
`cut_lfs` and `pitch_primary` from the measurement under an explicit-wins rule — and passes
`num_squares`/`flat_squares` through from the body verbatim (`:301-302`). The server holds the
authoritative split and ignores it. Worse, `flat_squares: float = Field(default=0, ge=0)` (`:137`)
makes *"no flat section"* and *"split unknown"* the same value on the wire, so the API cannot
represent the state the defect is about. And `infra/migrations/0046_measurement_pitched_flat_split.sql:12-13`
documents the contract as *"when pitched_sq/flat_sq are present the quote builder uses them and the
ambiguity is gone"* — true of `Quoting.tsx` only. That is a migration describing server behaviour
the server does not have.

A guard in `Quoting.tsx` fixes one screen and leaves `/estimator/project-quote`, `scripts/`, and
every direct API caller exposed. **One guard where all callers route through is the smaller diff.**

---

## §3 — Wave 0: dispatch (human latency)

Everything with a person on the other end goes out in one sitting. A dispatch item is **done when
`sent`**, with a stated default that unblocks downstream work regardless of reply — an item whose
downstream work has *no* survivable default is not a dispatch item, it is a critical-path
dependency with an owner and a date (only `#451` qualifies).

### 3.1 The letter to Tim — rebuilt on the rule that actually worked

v1 theorised that ten separate emails went unanswered *because they were separate*, and proposed
merging them. **The review falsified that with a measured result.** The 2026-08-01 six-question ask
scored **4 of 6 answered within ~24h** — and both failures were about *phrasing*, not ordering or
length: Q3 failed because the term "General Conditions" did not land (*"what do you mean general
conditions?"*), Q5 failed because he wanted a pointer (*"give me a link and I will look"*).

Ordering was not the variable. The planner proposed ordering by *ease of answering*; the architect
proposed *irreversibility of the default*. **Both are wrong, and the critic's adjudication holds:**
Q3 was simultaneously the highest-dollar *and* the most irreversible item and sat third of six —
comfortably inside either ordering — and failed anyway.

**The two rules the corpus actually validates:**
1. **Inclusion — corpus exhaustion.** `docs/2026-08-01-six-questions-for-tim.md:5-7`: *"Zero hits for
   each. He has never stated any of them, which is the test for asking rather than defaulting."*
   That rule went 6/6 on inclusion. **Run all ten through it and delete any with a non-zero hit
   count in HIS corpus** — his sheets, comments, proposals, emails. Nothing else counts as a hit.
   ⚠️ **v2 misapplied its own rule twice and this is the correction.** `#441`'s "% of profit or
   contract" *is* answered ("15% of gross or 50% of net") — but its *per-salesperson rate* half is
   NOT, which is why Josh's 7.5% is question 2 below. Deleting `#441` wholesale removes a live
   question and then re-adds it three lines later. And `#446`(1) — the HVHZ +$100/sq adder — was
   filtered on **our** measurement, not on a statement of his; that is a **different, second
   filter** ("we can default this from our own data"), and if it is used it must be named as such.
   Conflating them leaves `PRICING_RULES.md` promising an adder no config implements, with the
   question that would settle it deleted.
2. **Phrasing — his own artefact, never our vocabulary.** Every question carries his cell
   reference, his attachment filename, or his number. `#451` goes as *"D19 = SUM(B19:B20)×1.15 —
   $22,800 green fence/telehandler + $9,000 full-time PM"*, not as "General Conditions".

**Structure:** ≤6 questions, ≤400 words of question body, each ≤3 lines (question / dollar
consequence / **what we do if you say nothing**). That last line is the load-bearing addition —
it converts silence from a block into a decision he has declined to overrule. Open with three lines
on what his last answers already changed; reciprocity is the cheapest thing in the letter.

**Contents after filtering** — note three of these are **not currently Jarvis tasks**, which is §0
in miniature:
1. The four cell refs `K33`/`L33`/`K35`/`L35` + the attachment filename — "what do these cover?"
2. **Josh's 7.5%** — negotiated or stale? (*unfiled*; `97f66df`: deleting it silently would be worse)
3. `#451` — does the client see D19, and is its ~$4,770 margin commissionable (≈$2,385 at 50% net)?
4. `#422` — is the $2,500 floor before or after commission? Now a $5,000 question.
5. `#448`(1) — the tile-dumpster boundary square. Zero hits across 273 comments.
6. **The week/inspection allowance** (*unfiled*) — "when you say 2–2.5 weeks including inspections,
   how many days is the inspection/cleanup allowance?" `_apply_project_floor` does
   `ceil(total_days / profit_floor_days_per_week)` (`core/bid_project.py:405-406` — the divisor is
   CONFIG-driven, not the literal 5 quoted in the continuation doc), which measures crew-days on
   site, a different quantity from schedule time. His answer may be a config value, not code.

**Sent separately, with no question mark in it** — a *telling*, not an *asking*: the permit
divergence we owe him (`permit_count` shipped as building count; Evergrene +2.3% → **+4.2%**,
further from his own bid) and `#431`'s margin-squeeze findings. Mixing tellings and askings is what
makes a letter feel like homework. **`#442`/`#443`/`#408` are Marco/Wendy/Jon items and do not ride
in Tim's letter** — different people, different clocks.

### 3.2 Everything else with a human on it
`#319` (start the four platforms that don't need Josh) · `#315` Josh's creds · `#324` Roofr quotes
from Josh · `#317` Tim's clips · `#439` Tim's Knowify login · Tim's CompanyCam PAT (gates `#360`'s
second half) · `#88` ToS opt-in (legal, not defaultable) · `#407`'s Tim question, pulled out of
Wave 4 · `#408` Wendy+Eli invite, promised 7/20 · **and the cutover items in §5.**

**Close on existing evidence:** `#318` is resolved by `docs/2026-07-08-tim-requirements.md:73` and
memory `perkins-pricing-verified` — it survived the sweep only because the sweep verified against
*code* and this one was resolved against *documents*.

---

## §4 — Wave 1: start the long pole (external calendar)

`#319`, unchanged from v1 and the best call in it. 2–4 weeks optimistic, 6–10 realistic. Nothing
engineering does shortens it; only starting it earlier does.

⛔ **BLOCKING DECISION, owner Jon, needed before the first form is submitted** (also listed in §8):
under whose identity do the dev apps get registered — Tim's business accounts or DeGenito's? That
decides who owns the audience and who survives the engagement ending, and an afternoon of forms
creates that fact permanently. §12 says start this week, so this decision is due **before** it.

**Done when** each of six platforms has a recorded state — `submitted` / `in review` /
`rejected: <reason>` / `approved` — with a date. **"Started" is not a state**; a task at 30% hides
five platforms at zero.

---

## §5 — Wave 2: money correctness, re-ordered by customer exposure

v1 led with `#429` on a $-magnitude reading (890 contracts, 36%). That was anchoring: **`#429`'s
Knowify half cannot change a price.** But the review's first correction over-generalised —

**`#429` is two populations fused into one task, and all three passes inherited the fusion:**
- **`#429a` — `measurements.pitched_sq/flat_sq` backfill (13 of 42 rows). MONEY.** The complement of
  §2's guard, not an alternative: the guard makes a wrong quote impossible, the backfill makes it
  unnecessary.
- **`#429b` — the 890 Knowify contracts** (`scripts/mixed_roof_sold_analysis.py:56,61` iterates
  `entity='deliverables'` / `ContractId`). **ANALYSIS.** Wave 5.

Shaped by the phrase "pitched/flat split" instead of by the table it lives in — which is this
project's own recurring defect, recorded in memory as *config keys shaped by source, not dimension*.

**Order, and why:**

| # | item | why here |
|---|---|---|
| 1 | **§2's server-side split resolution** | the only live customer-price defect; stops the bleeding; ~a dozen lines in one route |
| 2 | `#451` GC itemised or excluded | the only item reaching a **contract document**; "one line either way" |
| 3 | `#452` commission on a project bid | gated on #451's *base*; today it computes nothing at all |
| 4 | `#422` floor vs commission | a **formula**, not a value: if post-commission the target is `2500/(1-rate)` |
| 5 | `#429a` measurements backfill | money, but bounded by the guard above it |
| 6 | `#436` day model | needs #429a first — the comparison scripts read those columns |
| 7 | `#417` thirteen low-slope gaps | catalog completeness |

### Acceptance criteria — falsifiable, per item

1. **Split resolution — all THREE cases, because the defect has two failure modes and v2 first
   specified only one:**
   - NULL split **+ explicit `flat_squares > 0`** → **422** naming both readings of `total_sq`.
     (0 live instances today.)
   - NULL split **+ flat omitted** → **proceeds**, and stamps `split_unknown` on the estimate.
     This is the case **all 10 measured estimates are in**, and a blanket 422 here would refuse
     every legitimately all-sloped legacy quote. Without this line the wave's #1 item ships
     believing it closed a defect whose only live instances it never touched.
   - **Populated split** → the **measurement wins** and a conflicting body value is ignored.
     ⚠️ This is deliberately the **opposite** of the `cut_lfs`/`pitch_primary` rule three lines
     above it (`api/routes/estimator.py:279-281` is explicit-body-wins), and the plan must say so
     or two developers will implement opposite resolutions from one document. The reason for the
     asymmetry: a cut LF is a measurement an operator may legitimately correct; the pitched/flat
     split is *money*, and the body demonstrably cannot be trusted to know it — that is the entire
     defect. The operator's escape hatch is to fix the measurement, not to out-argue it per quote.
   `flat_squares` becomes `float | None = None` so "unknown" is expressible (today
   `Field(default=0)` makes "no flat section" and "split unknown" the same wire value). Callers
   that omit the field entirely must NOT start 422-ing — verify that explicitly.
   Proven by a **route-level** test, not a frontend one. The SPA guard stays as UX, not as the fix.
2. **`#451`:** a rendered proposal whose **printed lines sum to its stated total** — GC either
   itemised or excluded, never silently inside it.
3. **`#452`:** an Evergrene-shaped bid reports a commission equal to
   `decided_base × decided_rate` **computed independently in the test** — "non-null" passes on any
   number, including a wrong one — and a single-roof quote is byte-unchanged.
4. **`#422`:** the basis is explicit in code *and* in `PRICING_RULES.md`, with a test at the 10sq
   HVHZ tile case re-derived at 50%.
5. **`#429a`:** row counts **in both directions** (R10) — how many backfilled, how many left
   ambiguous and *deliberately excluded*.
6. **`#436`:** 95% measured **out-of-sample with rule selection nested inside the CV**, reported with
   n and fold count. In-sample against the same 27 homes is the method that already turned an 83%
   into a "93%" that reached a client subject line (memory `in-sample-headline-93-vs-83`).

### Non-regression signals — every merge in this wave
1. `scripts/validate_against_evergrene.py` — total and profit divergence recorded **as numbers and
   compared to the previous merge's numbers.** Divergence must be tracked in aggregate, not per
   change; three individually-correct changes can drift the whole.
   ⚠️ **This is a HUMAN step in the R2 checklist, not a CI job.** The script needs a live DB
   (`scripts/validate_against_evergrene.py:15` — it reads the active jupiter config over the Cloud
   SQL proxy) and CI has neither the database nor a credential for it. The "previous merge's
   numbers" need a store, and a CI job is stateless. **The store is a committed
   `docs/divergence-log.md`** — one line per money-path merge (`commit · total % · profit % · what
   moved`), appended by whoever merges and read by the R2 reviewer. Do not write "reported in CI"
   for a script that cannot run there.
2. The 30-home comparison — per-home distribution, not a mean.
3. `_PDF_TEMPLATE_VERSION` bumped if `DEFAULT_TEMPLATE_HTML` changed, or the customer's document
   silently keeps the old bytes.
4. **Follow every default to the layer that supplies it.** A changed default in `core/` proves
   nothing if `Quoting.tsx` sends a value on every request — the CRITICAL both reviewers led with on
   2026-08-02.

### Remediation, already run — and the query, written down

```sql
-- the double-billed set: split unknown AND an explicit flat section was typed
select count(*) from estimates e
join measurements m on m.id = (e.input_json->>'measurement_id')::int
where e.input_json->>'measurement_id' is not null
  and m.pitched_sq is null
  and coalesce((e.input_json->>'flat_squares')::float, 0) > 0;   -- prod 2026-08-02: 0
-- the wrong-rate set: split unknown, flat omitted, billed at the sloped rate
select count(*) from estimates e
join measurements m on m.id = (e.input_json->>'measurement_id')::int
where e.input_json->>'measurement_id' is not null and m.pitched_sq is null;  -- prod: 10
```

Pasted here because "re-run the query" without the query is §0's own thesis applied to this wave's
exit assertion. **`0` is a point-in-time measurement of operator behaviour, not a property** — a
salesperson can make it non-zero before the guard lands. **If it returns non-zero, stop:** each row
is a quote that double-billed a flat section, and any that reached a customer as a sent proposal is
a commercial decision, not a code fix.

---

## §6 — Wave 3: hardening · §7 — Wave 4: growth, **gated**

**Wave 3:** `#409` 8 hanging tests · `#410` the real generation-side video-id guard (validated
against the metal-benefits case: emitted `example`, true sources `AnotOjX6eCA` + `DJlwSeF8lTQ`) ·
`#359`'s branch FK (66%) · `#360`'s reader — *the PAT half stays in Wave 0* · `#444` GCP budget.
**Non-regression:** `pytest tests/` — the **whole tree**. (`ci.yml` already runs exactly that on
every push with no branch filter, and there are no local git hooks installed — so the often-repeated
"the pre-push set does not reach `test_f2_engine.py`" is the right RULE with the wrong REASON.
Run the whole tree because CI does; not because a hook exists.)

**Wave 4 entry gate — non-negotiable, and the finding that rejected v1.**
`docs/PRODUCTION_CUTOVER_PLAN.md` has **11 unchecked gates**, including *PROD WP Application Password
(Owner: Jon)* and the `perkins-jsonld` mu-plugin re-install; **Wendy owns three.** Prod's newest post
is **2026-07-02**; everything the platform publishes lands on the staging GoDaddy domain
(memory `platform-publishes-to-staging`, which predates and duplicates this finding).

The tracker holds `#379`, the work that *feeds* the cutover, and **none of the cutover's own gates** —
which is worse than holding nothing, because it makes Wave 4 look started.

- **Entry gate:** `PlatformConfig.WP_URL` read from the **prod DB** is `perkinsroofing.net`. Do not
  trust `resolved_wp_url()` — it swallows every exception and returns `""`.
- **Done when:** the newest post date on perkinsroofing.net has **advanced**, verified by fetching
  the live site — not by a 200 from the publish call. JSON-LD read-back confirms `_perkins_jsonld`
  is stored (it silently returns `jsonld_stored: false` when the mu-plugin doesn't cover the type).
- **PII gate, which no task carries:** every published image must be WP-hosted with the CompanyCam
  capture band cropped. `core/pii.py` is **text-only** and structurally cannot see 6-decimal
  coordinates burned into pixels (memory `companycam-burns-gps-into-pixels`). `#384`/`#407` are
  exactly that publish surface.

Contents: `#378` · `#379` · `#382` (+`#402`) · `#384` (40%) · `#407`.

---

## §8 — Wave 5: decisions, then the tail

**Overdue:** `#339` MTA-STS, due 2026-07-21 — a *task* dressed as a decision. Read the TLS-RPT
reports in dmarc@; zero real failures means drop it and close. 20 minutes.
**Jon's calls:** **the social-app registration identity (§4) — due BEFORE §12's "this week", and
the only one of these that blocks other work** · `#323`/`#329` Ez-Bids · `#327` Google Earth ·
`#363` four B6 items · `#352` B10 · `#328` 1Password · `#400` GitHub org · `estimating_view` on a
writing endpoint · **the dead `commission_pct` config surface**: the key is still in
`_REQUIRED_KEYS` and `web/src/pages/EstimatingConfig.tsx` renders live sliders writing
`commission_pct.sloped`/`.low_slope`, which `scripts/prune_stale_open_items.py:73` records as "no
longer read at all". An operator moving that slider changes nothing. No customer price moves, but
it is rework waiting for whoever builds `#452`.
**Deferred by size:** `#331` SquareQuote on the Google Solar API — a project, not a task.
**Tail:** `#429b` · `#387` `#388` `#389` `#345` `#326` `#375` `#397`.
**Newly surfaced, unplaced:** Miami charges a whole office day per job (~$2,087/sq vs $1,113
accepted, ~1.9x) — a live per-branch pricing anomaly absent from a plan whose centre of gravity is
money correctness.

---

## §9 — Gates, parallelism, and rollback (all absent from v1)

**Per wave, every wave:** R1 ≥97% on `core/` **plus** a behavioural validation for new I/O · **R2
BOTH architect and critic**, `run_in_background: false` · R4 `scripts/drift_check.sh` clean · R10
report what the change moved **and what it left alone**.

**Parallelism is a worktree question, not a lane question.** The review disputed this twice and both
sides were half right: `ci.yml` runs the coverage gate on every push with no branch filter, so
`core/` is *not* serial per repo (PRs #8/#9/#10 merged in parallel inside 48h). But **R7 is a
single-workstation mutex** — the 40–60 minute gate maps line numbers from the file on disk at report
time, so editing the tree while it runs invalidates it. Parallel work therefore goes in separate
worktrees on separate branches, with `ci.yml` as the authoritative gate. **Never `git add -A` with
shared-checkout agents.**

**Rollback, assembled from machinery that already exists:**
1. A wave's exit is a merge to `main`, and `main` auto-deploys. **Therefore the rollback unit is a
   commit and the mechanism is `git revert` through the same pipeline.**
   ⚠️ **A revert is gated on infra being drift-clean.** `deploy.yml` runs the Terraform drift gate
   *before* `scripts/deploy.sh` and `exit 1`s on drift — on `workflow_dispatch` too. So an
   emergency revert can be blocked by unrelated infra drift, in a repo where R4 exists precisely
   because drift recurs. If that happens: `cd infra && terraform apply` first, then re-run the
   deploy. **A manual `scripts/deploy.sh` is NOT sanctioned break-glass** — R3 forbids it and it
   races the Cloud Run optimistic lock. Fix the drift; do not go around the gate.
2. **Two things `git revert` does not undo.** *Migrations* — the runner has no ledger, ignores
   `DB_URL` (always prod) and replays from 0013; 0040's unguarded `ADD CONSTRAINT` already silently
   blocked 0041–0052 once. **No wave ships a destructive or unguarded migration.** *The `#429a`
   backfill* — write the pre-image (`id, total_sq, pitched_sq, flat_sq`) to a shadow table before the
   UPDATE, and make the script idempotent. The shadow table is `CREATE TABLE IF NOT EXISTS` **inside
   the backfill script — NOT a migration**, or the ledger-less runner replays it from 0013. ~5 lines, and it is the complete rollback for the only
   irreversible item in Wave 2.
3. **Abort rule:** a wave that goes wrong stops at its last merged commit; no fixing forward past a
   red gate. This requires **slice-sized merges** — the pattern #430/#449 already used across four
   commits — so an abort's blast radius is one slice, not one wave.

---

## §10 — Pre-mortem: it is 2026-09-02 and the quarter went badly

**S1 — "The letter was read and not answered."** It went out 08-05; Tim decided it deserved a proper
sit-down and never got one. `#451` stayed open, so `#452` never got a base, so the flagship
multi-building feature still cannot report a commission, and the September call had no new
capability to show. *Root cause:* yield assumed rather than measured, and no fallback for silence.
*Leading indicator, checkable 08-08:* **answers per question at 72 hours.** Baseline is 4/6 in ~24h.
Below 50% at 72h the format failed — switch to one question per message on a 48-hour cadence. Second
indicator: every question ships with a stated default, so no-reply resolves to a decision.

**S2 — "A quarter of content on a domain nobody visits."** Wave 4 ran, everything rendered and
published — to `1228404.us6.myftpupload.com`. In September Tim asked why perkinsroofing.net looks
unchanged since July; the answer was a prod application password nobody generated. *Root cause:* the
plan was built from the tracker and a markdown checklist is not a schedule. *Leading indicator,
weekly, one query:* **the newest post date on perkinsroofing.net**, plus `PlatformConfig.WP_URL` read
from the prod DB. If it does not advance within two weeks of a content wave starting, that wave is
producing shelfware. *Runner-up:* `#319` started on time and three platforms rejected for a missing
privacy policy or demo video — 2–4 weeks became a 10-week resubmission loop. Indicator: **per-platform
review state**, not "#319 started".

**S3 — "Every rule was his, and the estimator drifted anyway."** Each of Tim's rules shipped with its
divergence reported — permits +2.3%→+4.2%, then the GC slider, then a low-slope adder, then the day
refit. Nobody re-ran the *whole* golden set after the third. By late August a real Evergrene-shaped
job quoted ~10% above what Tim would have bid and Perkins lost it. *Root cause:* divergence tracked
per change, never in aggregate. *Leading indicator:* **one tracked number per commit** — the
Evergrene validation plus the 30-home comparison, reported in CI as a metric, not a pass/fail gate.
If |divergence| grows across two consecutive money-path merges, stop and reconcile.

---

## §11 — ADR

**Decision.** Keep thematic waves as the unit R1/R2/R4 attach to. Re-order Wave 2 by *customer
exposure* rather than dollar magnitude, led by a server-side fix for a live pricing defect the
backlog never contained. Gate Wave 4 on the WordPress cutover. Rebuild the Tim letter on
corpus-exhaustion for inclusion and his-own-artefact for phrasing. Express parallelism as worktrees.

**Drivers.** (1) External calendar latency — two clocks are running, platform review and the
cutover, and only one was in v1. (2) Tim's attention, a measurable budget at ~4–6 answers per ask.
(3) Cost of a wrong answer *reaching a customer*: proposal text > quoted price > reported payout >
historical analysis.

**Alternatives considered.** *Option B, money-first* — rejected: its premise ("a pricing engine wrong
about 36% of the book") described `#429`, whose Knowify half cannot change a price. *Option C,
directory-shaped lanes* — rejected: this repo's coupling crosses directories, proven by §2, a task
filed under data/scripts whose money defect lives in `web/`. Its **dispatch day survives** and is
adopted as §3. *Option D, strict critical path* — rejected: the path is 6–10 weeks of waiting, so it
would leave engineering unallocated for two months.

**Why chosen.** It is a re-cut of the same 54 items, not a rewrite, and it fixes the two defects the
review proved: a mis-ranking and a structural blind spot.

**Consequences.** `#451` is a genuine critical-path dependency on one person with no survivable
default — no structure removes that. Wave 4 cannot start on schedule if Wendy's three gates slip.
`#429` becomes two tasks and the Knowify half moves to Wave 5.

**Follow-ups (file as tasks — three are the review's own output).** Server-side split resolution +
nullable `flat_squares` + 422 · `#429` split into `#429a`/`#429b` · Josh's 7.5% · the week/inspection
allowance · the permit divergence report owed to Tim · the Miami office-day anomaly · a client-facing
milestone, of which 54 tasks contain exactly zero.

---

## §12 — Sequencing, in one line

Send Tim one filtered letter and start the social registrations **this week**; both are pure
calendar. Land the server-side split guard **first** in code, because it is the only thing here
presently able to misprice a customer. Then `#451` → `#452` → `#422`.
