# CONTINUATION 2026-07-28 — seven commits, and the overhead model changed underneath us

**HEAD `5219dd9`**, pushed. **Deployed image `platform:372be23`** — the three commits above it are
NOT deployed. Prod configs **jupiter v25 / miami v27 / naples v25**. `drift_check` clean.

Seven commits today. The estimator's profit and overhead mechanisms both changed, six stale "open
items" were deleted from prod config, and three of Tim's nine open questions were answered from his
own documents without asking him.

---

## 0. Read these first

| | |
|---|---|
| `docs/R2-2026-07-27.md` | the R2 record + §5, how the nine open items resolved |
| `docs/email-drafts/2026-07-28-tim-overhead-and-pricing.md` | drafted, **UNSENT**, sitting in Jon's DeGenito Outlook |
| `docs/knowify-scrape-plan-2026-07-28.md` | what Tim asked us to scrape, and proof Josh's catalog is stale |
| `docs/meetings/2026-07-27-transcript.txt` | Whisper renders "Knowify" as **"notify"** — search both |

---

## 1. What shipped

```
5219dd9  overhead as ONE daily number per branch, behind a config switch
a058945  #437 crane flag, accessibility dollars, waterfront gate + #436 day-model refit
372be23  finish the open items — OI-5 plywood, OI-3 insulation, OI-11 zones
a90a894  #434 repair profit + prune six stale open items from prod config
78f3557  #432 profit as an operator percentage, server-side, floor enforced
7d0ed22  fold the bonus line, stop synthesising a per-square rate
450e206  #433 fold PM Incentive out of the customer view          <- deployed, defect closed
```

**#433 is live in prod.** A customer-mode proposal no longer prints PM Incentive. Verified on a
RENDERED document, not the template: 35 sq Miami tile → 6 customer rows, one all-in $40,400 line,
same $45,200 total as internal.

**#432** — `profit_mode="percent"`: profit = pct × `eligible_base`, using the same definition the
margin badge reports so the operator's 20% and the badge cannot disagree. The Quoting slider WAS
already computing this in the browser and posting it as `flat` — which meant the $2,500 floor only
warned instead of applying. Now server-side, floor enforced, "Min $" raises it and can no longer
quote under $2,500.

**#434** — repairs returned COST only. Tim's live example (shingle, 1 day, 1 man, $500 material)
now returns **$1,935**, not $1,685. ⚠️ Every repair quote rises by at least $250 once deployed.

**#437** — two of his four asks were already built (Resi/Commercial select; COASTAL already a tier
on tile $47.50 / shingle $215 / metal $430). The real gaps: `crane_threshold_stories` was 3 in
config and **nothing read it** (both paths hardcoded a 6+ raise), and accessibility needed the flat
half — `roof_cuts_per_sq` already WAS the per-square half.

**#436** — stories/accessibility take the day model 83% → **86%** within a day out-of-sample. A flat
leaderboard said 90%; nesting the feature-set choice inside each fold costs 4 points. **86% is the
number to quote.** No coefficients shipped — see §4.

---

## 2. ⚠️ The overhead model changed — and the number is NOT settled

Jon, 2026-07-28: *"we are not doing per sq for job costs unless an upgrade on material is per sq…
we need a daily OH number for branch… monthly overhead calculated externally, divided by 20.
Estimator picks number of days and OH x days is what's used. Margin is the sliding lever that's
negotiated, materials costs and OH cannot be reduced."*

Confirmed in the transcript. `overhead_basis: "branch"` is BUILT and tested: `OH = total days ×
office_daily_overhead`, both roof paths, `office_men` ignored entirely, raises rather than
inheriting another branch's rates.

**It defaults to `"series"` and nothing repriced.** Do not flip it without Tim. The evidence:

| overhead model | vs his 21 actual sold prices |
|---|--:|
| per-series daily rates (today) | **+1.0%** median, 86% within 10% |
| flat $1,400/day | **+13.3%** median, 43% within 10% |

Solving for the margin his real prices leave under flat $1,400/day: **median −0.4%, worst −19.7%,
and 19 of 21 below his own $2,500/on-site-week floor.** His prices recover **$840–950/day**; his
7/24 per-series rates average $798. The $1,400 is the outlier.

That gap is either the margin squeeze in **Jarvis #431** (materials +8% YoY, realised prices −24%
from the 2024 peak) or a misread of what the branch number covers. **It is a business decision.**

⚠️ At $4,250/day an 8-day Miami job carries **$34,000 of overhead on a $65,900 quote — 52%**. Put
that in front of Tim before flipping anything.

**Miami v27** carries `office_men: 14` (his CURRENT detail rows; row 1's 12 is stale — Jon:
*"miami grew and row 1 not updated"*), worth $1,512 on a 30 sq job. That scaling goes **inert** the
moment `overhead_basis` flips to branch, so no cleanup is needed either way.

---

## 3. Open items: 9 → 5, and three were answered from his own documents

Six were **stale** — OI-2/4/6/8 claimed nulls that prod had carried for weeks. Then:

- **OI-3 insulation** — CLOSED. His rows: 1" $255 / 1½" $275 / 2" $310, all `-no P`.
  `insulation_by_thickness` already held exactly that; the checker was reading the dead key.
- **OI-5 plywood** — CLOSED, and it was never a missing number: the **unit was wrong**.
  `deck_types` bills per SQUARE; his Lumber Schedule prices plywood per **SHEET** (⅝" $120, ½" $110,
  ¾" $145, first 2 free). Filling the old key with 120 would have billed $120/sq.
- **OI-11 zones** — NARROWED. Same prices; the split is **availability** — two BUR wood systems are
  "not HVHZ" on his sheet. Now data, and the engine warns.

`scripts/prune_stale_open_items.py` regenerates the list from the live config every run, so an entry
cannot outlive its blocker. All config work applied at **$0.00 price delta**, verified per branch.

**Still needs Tim (Jarvis #448):** OI-10 dumpster boundary (zero hits across 273 comments, both
transcripts AND the proposals — a genuinely real question) · OI-11's price check against his live
calculator. Not blocking: OI-7 needs a per-salesperson re-key, OI-9 is near-moot after #432.

Also fixed: **the Lumber Schedule exhibit on every proposal stated NO PRICES** — an exhibit to the
contract that a customer signed without being able to read the rates.

---

## 4. THE REMAINING WORK

### 4a. Knowify → Jupiter  (#439, unblocked — Jon now has access)

Tim, 7/27: *"I would scrape **my** notify… I update my catalog all the time, way more than Josh
does… Sometimes I'll even forget [to tell Josh]."*

**Scrape:** scope-of-work templates · accent items (skylight / solar vent / chimney) ·
PROTECTOR/PREFERRED/PREMIUM per roof type · repair scopes by type.
**Apply to:** the scope-of-work section on BOTH re-roof and repair, as a type-ahead template
drop-down — one or two letters auto-populates the whole scope.

**The MCP is still bound to the WRONG tenant** — Perkins Roofing Corporation, 575 NW 152 St Miami,
Company 11267 / Tenant 9258. That is Josh's. Two separate credentials:

1. **The MCP** (`mcp__knowify__query`, what actually returned data) — Claude Code's own MCP OAuth.
   Re-auth with **`/mcp`** → `knowify` → log in as Jupiter. **This is the proven path.**
2. **Our REST client** (`core/knowify/`, `~/.config/knowify/tokens.json`) —
   `scripts/knowify/knowify_oauth.py`. ⚠️ Knowify's authorization server returns `server_error`
   when the RFC 8707 `resource` parameter is present, and 401s tokens minted without it. Reproduced
   2026-07-28. A `resource`-free link was generated; if it also fails this is a Knowify support
   ticket. Fresh-client helper: `scratchpad/kw_auth.py` (registers, prints URL, listens on :8765,
   exchanges → `~/.config/knowify/tokens_jupiter.json`).

**Miami baseline captured before switching** (a connection sees ONE tenant):
`~/perkins-corpus/knowify/miami_catalog_perkins_items_2026-07-28.json` — 26 tier items, **54,307
chars of pre-written scope text**, 561 catalog items. The scope text IS the proposal body from the
golden PDFs.

**Already proven from the baseline:** Josh's catalog untouched since **2026-05-07**; the accent
items Tim named (Skylight, Chimney Cap/Repair/Restoration, Turbine Vent, Ventilation, Vent Stacks)
are **$0.00 placeholders** last edited 2024-10-23; and **21 of 22 tier prices match our config** —
the exception being **tile/PREFERRED, ours $165 vs Josh's $160**, where our 165 is annotated
*"verified Greener proposal 7/17: $7,095/43sq"* = $165.00 exactly. Tim's catalog settles it.

### 4b. CompanyCam — creds + their API, for project posts

Buildout plan P4-13: *"Project posting UI: post projects to the project page; auto-extract from the
PROPOSAL + CompanyCam to build a project gallery with a page-per-project."*

**Built ahead of the account and inert** (commit 0c35be9): `core/companycam/{rest,mirror}.py`,
`adapters/companycam.py`, `api/routes/companycam.py` (HMAC webhook), `jobs/companycam_sync.py`,
migration **0043_companycam.sql**, advisory lock **8274126**, tenant-1 scoped. API base
**`https://api.companycam.com/v2`**. Gated on **`COMPANYCAM_PAT`** — `adapters.companycam.configured()`
returns False and the sync job no-ops.

**To do:** get the PAT into Secret Manager + the deploy env · confirm the webhook envelope and
signature format against live traffic (never verified) · the mirror is **write-only today** (deep
review 2026-07-19) so reads need building · then the project-gallery extraction.

### 4c. #430 — the project dimension (biggest, design settled)

Jon, 2026-07-28: a **project** owns a **collection of estimates and proposals**; the $2,500 floor
becomes **per SITE per week**; fixed fees charge **once per project**, not per building; General
Conditions is a **project-level block**. Jarvis **#449**.

Evergrene is 9 buildings at one address: we quote each as a standalone job, so ~$2,500 of fixed
fees AND the $2,500 floor apply nine times. Bus Stop 3sq: Tim $4,763 vs ours $9,995 (+110%);
Gazebo +69%; Clubhouse −20.6%; total nets to −7.8% only because the errors offset.

**Open question before the migration:** is a *site* the same as a *project*, or can one project span
several sites? site==project is one table and fixes Evergrene today; multi-site is two tables and
every fixed fee must declare its level. Jarvis #431 also carries **per-building base cost**
($750–930 on Evergrene) and **Verea Caribbean/Spanish $230/$275 vs our $120/$195** — both only
appear on multi-building projects, so they belong to this work.

### 4d. Smaller, ready to go

- **Deploy `5219dd9`** — carries #437 + #436 + the overhead mechanism. Nothing in it moves an
  existing price (new inputs default off, basis defaults to series). The repair increase already
  went out with `372be23`.
- **Send the Tim draft** — and consider folding in tile/PREFERRED and OI-10 so it is one email.
- **cerberus `gmail-enhanced`** — git pull + restart; the box serves old code (fixes in d656cdd).
- **#435/OI-12 Naples** — still no office burn, silently inheriting Jupiter's rates.

---

## 5. Gotchas earned today

- **`pkill -f <pattern>` matches your own shell** when the pattern appears in your command line —
  it killed the shell mid-command and the heredoc after it never ran. Same family as the documented
  `pgrep -f "pytest tests/"` trap. Use `Write` for scripts, and don't pkill on a string you just typed.
- **Python buffers stdout when it is not a TTY** — a backgrounded script that prints a URL logs
  NOTHING until it exits. Use `-u`.
- **o365 MCP's Graph token expired** (issued 2026-04-23, 90-day inactivity). `gmail-enhanced` with
  `account: jon@degenito.ai` reaches the SAME Outlook mailbox on a different token and works. Try
  that before requesting a re-auth.
- **jon@perkinsroofing.net is READ-ONLY** — access/auth control. All customer comms go from
  **jon@degenito.ai**.
- **Verify a negative before reporting it.** The local sweep of all 273 cell comments returned
  NOT FOUND on all five questions and was **wrong on three** — the answers were in the row CONTEXT,
  not the comment text, and OI-5's answer was in a PDF it never saw. Deterministic greps caught it.
  Cheap bulk reading is worth running; it is not worth trusting on a negative.
- **Nesting matters more than the model.** Choosing the best feature set by reading a leaderboard
  computed on all 29 homes cost 4 points of honesty (90% → 86%), exactly as it once cost 10 (93% → 83%).
- A config change is still FOUR places: fixture, prod, tests, and any seeder that could replay it.

---

**Standing archive directive:** `CONTINUATION-2026-07-26.md` archived to `docs/continuations/`,
latest three kept at top level, README pointer refreshed.
