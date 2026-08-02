# CONTINUATION — 2026-08-02

**`main` = `be59ad5`, pushed, tree clean. CI green. Deployed and VERIFIED in prod: API image
`platform:8b3f5cd` (SHA matches), SPA bundle `/assets/index-DSRtfOBu.js` serving the new UI.**
Migrations through **0053**, all applied.

**#430/#449 IS DONE** — all four slices shipped: pricing, persistence, the proposal surface, and
the SPA that builds a bid. What follows is what Tim's answers now change.

---

## §0 — TIM ANSWERED THE SIX QUESTIONS. THREE OF THEM CHANGE CODE.

Jon relayed these 2026-08-01. Verbatim, then what each one does.

| # | Question | Tim's answer |
|---|---|---|
| 1 | Permit per structure or per site? | **"1 per building/structure"** |
| 2 | `new_bonus_values` per mobilisation or per roof? | **"per site"** |
| 3 | Commission on General Conditions? | **"what do you mean general conditions? comission is paid usually 50/50 on net project profits"** |
| 4 | Is the GC markup always 1.15? | **"we have a slider for this"** |
| 5 | What are the bare +4,250 and +2,550? | **"give me a link and I will look"** |
| 6 | Must a proposal list each building's address? | **"yes but they can share"** |
| 7 | Day rates — his $885/$735 vs our $1,050/$850? | **"follow the more conservative"** |

### ⚠️ Q1 IS THE BIG ONE, AND HIS RULE DISAGREES WITH HIS OWN BID

`permit_count` defaults to **1**. His answer makes it **one per structure** — 9 on Evergrene.

    now (1 permit):   $500 base + $500 commercial adder            =   $1,000
    his rule (9):     9 x $500  + 9 x $500                         =   $9,000
                                                                     +$8,000

That is **+2.05% on a $390,230 bid**, taking the Evergrene score from **+2.3% to roughly +4.4%**
— i.e. further from the number he actually bid. **His own Evergrene sheet charges one permit.**

This is the [[tims-stated-numbers-are-the-input]] pattern exactly: a back-test that disagrees with
a number from his own books is the margin squeeze, not a gate. **Report the divergence and ship
the change** — but say plainly in the same breath that it moves us away from his bid, because he
may have discounted permits on Evergrene deliberately.

Also note the commercial adder now multiplies: `_fixed_once` applies
`permit_commercial_add * min(commercial_count, permit_count)`, so 9 permits on a site with 9
commercial structures charges the adder 9 times. That is correct under his rule and worth showing
him as a line, not burying in a total.

### Q2 — no change. Confirms the shipped default

`new_bonus_values` is already in `DEFAULT_ONCE_PER_PROJECT`. ✓

### ⚠️ Q3 IS NOT ANSWERED, AND HIS REPLY OPENS A BIGGER QUESTION

He asked **"what do you mean general conditions?"** — so the term did not land, and the answer he
gave describes a different model from ours.

**Answer him with his own sheet.** On the Evergrene bid, `D19 = SUM(B19:B20)*1.15`:

    B19  green fence + telehandler   $22,800
    B20  full-time project manager    $9,000
    D19  x 1.15                      $36,570   <- referenced by NO total formula on his sheet

That block is what we call General Conditions.

**And "commission is paid usually 50/50 on net project profits" does not match what is built.**
`commission_pct` is a RATE applied to profit or job total, configured at **15% (Marco) / 7.5%
(Josh)** — see [[commission-is-per-salesperson]]. "50/50" is an order of magnitude away. Three
readings, and we should not guess:

1. 50% of net profit to the salesperson (vs the 15%/7.5% configured),
2. a 50/50 split between two people out of a normal commission pool,
3. 50/50 company/salesperson on what is left after all costs.

If commission is a share of **net** profit, then the original question answers itself — GC is a
**cost**, so it reduces net profit and therefore reduces commission; it is not a commissionable
revenue line. But the **rate** is now the open item, and it is worth more than the original
question was. **Ask before touching `commission_pct`.**

### ⚠️ Q4 REVERSES A PENDING RECOMMENDATION — DO NOT DROP THE COLUMN

I had flagged `bid_projects.general_conditions_markup` for deletion: always written `1.0`, read by
nothing, with the real markup carried per-block in `ProjectItem.markup`.

**"We have a slider for this" means the column is the right home after all.** It is a per-bid
operator rate, not a per-block constant. **Do not drop it.** Instead:

- wire a project-level markup control in the SPA (today only per-block markup is settable),
- have `price_project` apply it to the General Conditions block,
- keep the `CHECK (1.0..3.0)` — it matches a slider's range.

### Q5 — he needs a pointer, and here it is

The file is **his own attachment**: email 2026-07-24 18:58, subject *"TIME LEARNING (Overhead) for
AI Systems"*, attachment **`Evergrene Project Bid Spreadsheet.xlsx`**, sheet **`Bid Sheet`**.
Local copy: `~/perkins-corpus/roofr-attachments/2026-07-24__Evergrene_Project_Bid_Spreadsheet.xlsx`.

Both bare numbers are appended inside a specific building's row:

    K33  =(G33*J33)+D22+D25+4250     <- row 33 is the 206-square building (Clubhouse)
    L33  =(H33*J33)+D22+E25+4250     <- the metal alternate carries it too
    K35  =G35*J35+2550               <- row 35 is the 21-square building
    L35  =H35*J35                    <- the metal alternate does NOT

So +4,250 rides on the Clubhouse row next to the add-on blocks (D22, D25), and +2,550 rides on
the 21-square row with no counterpart in the metal column. **Send him those four cell refs**, not
a question — he can answer in seconds from his own file.

### Q6 — a proposal lists each building's address, and they may share one

**"Yes but they can share."** So the model needs an OPTIONAL per-building address defaulting to
the project's property. Today `bid_projects.property_id` is one site and buildings carry no
address of their own — which is right for Evergrene's shared entries but cannot express the two
gates on different roads.

Not yet built. It is the next proposal-render slice.

### Q7 — "follow the more conservative" = NO CHANGE, and that is worth stating

Conservative here means the **higher cost** assumption, so a bid cannot silently under-charge:
our config's **demo $1,050 / metal install $850**, not his Evergrene actuals of $885 / $735.
Tile install already matches exactly at $745.

**The estimator already uses the config rates** — so this confirms current behaviour rather than
changing it, and the +2.3% Evergrene match was achieved WITH the conservative numbers. Nothing to
do; recorded so nobody "fixes" it toward his actuals later.

---

## §1 — WHAT SHIPPED (all verified running, not just green)

| | evidence |
|---|---|
| API | `platform:8b3f5cd` — image SHA matches `main` |
| `/estimator/project-quote`, `/quoting/proposals/from-project` | live, **401**-gated (a fake route 404s) |
| SPA | served bundle contains `Multi-building bid`, `Add this roof`, `SAME property`, `own block` |
| Money path | Evergrene **$390,230 vs $381,288 (+2.3%)**, profit **$30,790 vs $30,363 (+1.4%)** |
| Backend | `PYTEST_EXIT=0`, coverage **97.89%** |
| Frontend | build clean, **26 vitest**, now CI-gated |

Slices: 1 pricing · 2 persistence (`bid_projects` + ORM + `POST /estimator/project-quote`) ·
3 proposal surface (edit gate, send-gate reads every building, `from-project`) · 4 the SPA.

---

## §2 — THE THREE FINDINGS WORTH KEEPING

**R2 caught defects inside R2's own fixes.** The architect found a CRITICAL (switching customer
left the previous customer's bid on screen and would file a proposal against the new one). My
fixes to it introduced two MAJORs — a save button that deadlocked the only edit path, and a
proposal reading its property from the wrong source — which the critic then found. **One reviewer
would have shipped them.** Run both, and run them with `run_in_background: false` or they return
nothing at all.

**An ungated test is a suggestion.** CI ran `npm ci && npm run build` and `npm audit` but never
`npm test`. Adding it turned the frontend job red within minutes — on my own work: the tests
passed locally only because `web/.env` supplies `VITE_FIREBASE_API_KEY`, which CI never sees, and
`src/auth.ts` calls `getAuth()` at MODULE SCOPE. Fixed at the cause (pure logic moved to
`web/src/lib/projectQuote.ts`, **zero imports**), verified by deleting `.env` and re-running.

**CI does not deploy the SPA.** `deploy.yml` builds the API image and never touches `web/`. Slice
4's entire UI was merged, CI-green and invisible until a hand-run
`npx firebase deploy --only hosting:app`. **"Deployed" in a commit message is a claim about the
API only.**

⚠️ Also: **`npx tsc --noEmit` is NOT the build gate.** It passed twice on code `npm run build`
(`tsc -b`) rejected.

---

## §3 — OPEN, IN PRIORITY ORDER

1. **Q1 permits → `permit_count` = building count.** Ship it, and report the +2.3% → ~+4.4%
   divergence from his own bid in the same message.
2. **Q3 commission.** Explain General Conditions with his `D19` block, and ask what "50/50 on net
   project profits" means against the configured 15% / 7.5%. **Do not touch `commission_pct`
   until he answers** — this is the largest money item still open.
3. **Q4 GC markup slider.** Keep `general_conditions_markup`; wire a project-level control.
4. **Q5** — send the four cell refs above.
5. **Q6 per-building addresses** on the proposal render (optional, defaulting to the project
   property).
6. ⚠️ **The `week` profit-floor basis measures the wrong thing.** Tim, 2026-07-28: *"how long it
   ties up the schedule... including inspections so if it's 3 days demo and 4 days tile install,
   we still call that 2 - 2.5 weeks"*. `_apply_project_floor` computes `ceil(crew_days / 5)`.
   Changes no price today (default is `project`, and the SPA cannot select `week`), but #449 is
   written in those terms. **His allowance for inspections/cleanup is not a number we have** —
   ask, do not invent one.
7. **Two decisions still Jon's:** `estimating_view` on a writing endpoint (matches `/quote`
   precedent; blast radius reduced — `persist` defaults False, `buildings` capped at 50), and
   whether to expose `floor_basis` in the UI at all.
8. **Wire the SPA deploy into `deploy.yml`** so the two halves cannot drift (changes the deploy
   path, so R3 says decide it deliberately).
9. **Curate the five ready portfolio projects** (needs a human — pick photos AND type alt text):
   isola 1,452 photos · olsen 802 · fisher-island-7900 311 · fisher-77 285 · pinnacle 186.
   Still blocked separately: `jim-malooly-delray-beach-roof` trips `title_not_a_person` (rename);
   `abacoa` and `miami-warehouse` have no CompanyCam url; 6 match no Knowify scope; 4 are under
   120 words.
10. Older: `api-run-sa` cannot create a secret (OAuth connect 502s); `#444` GCP budget blocked on
    the Billing API; `REACH_MI` 8 of 18 gauges unsnapped; `#447(3)` commission keyed by slope not
    salesperson; Miami charging a whole office day per job (~$2,087/sq vs $1,113 accepted).

---

## §4 — GOTCHAS (cumulative; the ones that cost real time)

- ⚠️ **CI runs `pytest tests/`** — the whole tree. The pre-push set
  (`tests/api tests/core tests/adapters tests/jobs tests/tenancy`) does NOT reach
  `tests/test_f2_engine.py`, which is how main stayed red for three commits.
- ⚠️ **CI does not deploy the SPA** (above). Deploy it by hand and verify the SERVED bundle.
- ⚠️ **`npx tsc --noEmit` is not the build gate**; `npm run build` (`tsc -b`) is.
- ⚠️ **`test_schema_maxlength` binds on IMPORTED CLASS NAMES**, not on writes — adding an import
  can newly bind an unrelated Pydantic field. Bound the field; do not add an `ALLOW` entry.
- ⚠️ **Migrations are applied BY HAND** and `apply_migrations_adc.py` **ignores `DB_URL`** (always
  prod) with **no ledger** — it replays everything from 0013 each run. `0027`'s UPDATE is
  unguarded and re-asserts on every run; harmless only while tenant 2 does not exist.
- ⚠️ **`tile_dumpster_count` is a `ceil()`** — anything calling it per building over-counts.
- ⚠️ **Local models were net-negative on review** — qwen3.6-think fabricated a CRITICAL against
  code that does not exist; gpt-oss-120b-think produced 1 real finding in 12. See
  `docs/2026-08-01-local-model-review-postmortem.md`. Never gate on them.
- ⚠️ **Reviewer agents must run with `run_in_background: false`** or they emit idle notifications
  and no report.
- ⚠️ Do NOT `source .env` before GCS work (sets `GOOGLE_APPLICATION_CREDENTIALS` to a file that
  does not exist). Use `$HOME/.config/gcloud/perkins-deploy-sa.json`.
- ⚠️ `DB_URL` in `.env` is sqlite; app code needs `postgresql+psycopg://…` over the proxy, and
  sessions must set `db.info["tenant_id"]` or `["platform_scope"]`.
- ⚠️ `resolved_wp_url()` swallows every exception and returns `""` — empty means a config error,
  usually sqlite `DB_URL`.
- ⚠️ **Search the mailbox, not just transcripts.** Tim's week definition and several pricing
  answers were sitting in email the whole time.

---

## ARCHIVE DIRECTIVE (standing, performed for this doc)

**Performed:** `CONTINUATION-2026-07-31-pm.md` archived to `docs/continuations/`, keeping the
latest three at top level. Inbound links repointed and README's "Most recent" refreshed.
