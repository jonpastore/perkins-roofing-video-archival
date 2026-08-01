# CONTINUATION — 2026-08-02 (eve)

**All four directives from `CONTINUATION-2026-08-02-pm.md` §0 are BUILT.** Uncommitted at the time
of writing on `docs/2026-08-02-tim-answers`; migration `0054` written and applied by hand; R2 run
with BOTH reviewers and every HIGH/CRITICAL finding fixed.

---

## §0 — THE HEADLINE: ONE OF THE FOUR WAS ALMOST SHIPPED HALF-BUILT

Tim's commission sentence is *"…and that's how we default **the sliders**."* The fix went into
`config.commission_rate()`, the tests went green, and `PRICING_RULES.md` was updated to say
SHIPPED — and **the sliders still said 30% and 10%**. `web/src/pages/Quoting.tsx` sends
`commission_rate` on *every* quote, so `body.commission_rate is not None` is always true and the
new server default was unreachable from the only screen that shows a commission. The deliverable
was a number on a screen; the screen was untouched.

Both reviewers led with it independently. It is now
`COMMISSION_DEFAULT_PCT = { profit: "50", job: "15" }` at `Quoting.tsx:275`, referenced by the
initial state and by the basis toggle, with a pointer in both directions between it and
`core.pricing_config.COMMISSION_DEFAULT_RATE`.

**The lesson worth keeping: changing a DEFAULT at the layer that owns it does nothing if a caller
always supplies a value.** Follow the value to the layer that actually supplies it.

---

## §1 — WHAT SHIPPED, ITEM BY ITEM

### 1. Commission rate from the BASIS — `job` → 15% of gross, `profit` → 50% of net

`config.commission_rate(basis)` replaces `commission_rate(slope_type, zone)`, which returned
`{"sloped": 0.10, "low_slope": 0.15}` — a dimension Tim's rule has no term for. On the default
`profit` basis we reported **10% of net against his 50%: five times under**.

- **Still a REPORTING error, not a pricing one.** Traced end to end for the review: `comm_rate` has
  exactly two consumers (`core/estimator.py:1612` and `:1641`), `commission` reaches only
  `EstimateResult.commission` / `estimated_commission`, it is not a `LineItem`, and neither
  `_compute_margin` nor `_apply_project_floor` sees it. **No customer price moves.**
- The `#422` floor note now takes the **effective** rate (override included) and fires **only on
  the `profit` basis** — a commission on gross does not move when the profit line does. It also
  got twice as expensive to be wrong about: at 50%, "is the $2,500 floor before or after
  commission?" is the difference between $2,500 and $5,000.
- **Not config-keyed.** `commission_pct.gross`/`.net` was built, then deleted in review: no seeder
  writes it and no screen sets it, so it was a lever prod could not pull. One company-wide rule,
  overridden **per quote** (`commission_rate_override`), which is where a negotiated
  per-salesperson split belongs.
- The old `commission_pct.sloped/low_slope/sloped_hvhz` keys stay in every live config (removing
  them is a data change) and are now read by **nothing** —
  `test_commission_rate_ignores_the_old_slope_keyed_config` pins that they cannot come back to
  life through the config.

⚠️ **STILL OPEN FOR TIM — Josh's 7.5%.** Marco's 15% is 15%-of-gross and fits. Josh's 7.5% fits
neither option. Nothing was deleted; ask whether it is a negotiated split (a per-quote override) or
a stale cell. Second, by implication: **is General Conditions commissionable?** `price_project`
counts its markup as profit (`out.profit += item.amount - item.cost`), so under 50%-of-net the
salesperson takes half of Tim's $4,770 GC margin. Put it to him as that number, not as a category
question.

⚠️ **A multi-building bid reports no commission at all** — `price_project` never computed one, and
this change did not add one. On an Evergrene-shaped bid the salesperson is shown nothing. Not built
(nobody asked); flagged because it is the same surface.

### 2. `permit_count` = BUILDING COUNT — **Evergrene measured at +2.3% → +4.2%**

Ran `scripts/validate_against_evergrene.py` against the live jupiter config rather than estimating:

    PROJECT TOTAL   ours $   397,230   Tim $   381,288   +4.2%     (was $390,230, +2.3%)
    PROFIT          ours $    30,790   Tim $    30,363   +1.4%     (unchanged)
    Permit Processing x8   $8,000   8 permit(s) — one per building (Tim, 2026-08-02)

**+$7,000, and it moves us FURTHER from what he actually bid** — his own Evergrene sheet charges
one permit. The pm doc estimated ~+4.4% for 9 × $1,000; the script prices the **8 tile** buildings,
so it is 8 × $1,000 against the $1,000 charged before. Shipping his stated rule and reporting the
divergence, per the standing instruction not to quietly pick.

`permit_count=None` now means "one per building" in `price_project`, the **effective** count is
returned in the roll-up and persisted into every audit row, and an explicit integer still wins.
On the legacy `floor_basis="building"` the count is forced to the building count, because nothing
is suppressed there and every building already pulled its own permit inside its own estimate.

### 3. Per-building addresses (#6) — migration **0054**, `estimates.structure_address`

A **COLUMN**, not a snapshot key, exactly as directed: the snapshot is what
`validate_project_snapshot` exists to police. Optional end to end (SPA capture field → API
`BuildingInput.address` → `core.bid_project.Building.address` → column → re-price → render), read
back on `GET /estimator/estimates` so a typo is visible somewhere other than the PDF.

The render is the interesting half. `core.proposal_render.structure_groups()` groups buildings by
their **effective** address — absent means the bid's property — so nine Evergrene buildings on one
parkway print **one** line and the two gates on different roads print their own. Insertion-ordered,
so it reads in bid-capture order like every other per-building list. New "Structures Covered"
section in `DEFAULT_TEMPLATE_HTML`; single-roof proposals render byte-identically.

⚠️ **`_PDF_TEMPLATE_VERSION` bumped to `perkins-scope-v4`.** A cached PDF is only re-served while
that string matches, so a template change without the bump would have kept serving pre-change bytes
— the new section silently missing from the document the customer receives. Caught in review.

### 4. GC markup slider — `bid_projects.general_conditions_markup` is real now

It was written as a hard `1.0` that nothing read. `ProjectQuoteRequest.general_conditions_markup`
is now the project-level default for any block naming no markup of its own; a block that names one
keeps it. The **effective** markup is what gets priced *and* persisted, so the re-price in
`/quoting/proposals/from-project` (which reads `float(b["markup"] or 1.0)`) cannot silently drop
the slider.

⚠️ The SPA change that made this dangerous: the per-block markup box now defaults **blank**
(= inherit), so the project field carries Tim's ×1.15 on every ordinary bid — and it shipped
without the guard the per-block field has. `"1,15"` and `"115%"` are `Number()` → `NaN`, which
coerced to 1.0 prices his $31,800 block at cost. That is the identical $4,770 silent under-charge
the per-block comment documents. Validated in `priceProject` now, and added to the customer-switch
reset beside `permitCount` for the same reason: **it multiplies money.**

---

## §2 — R2 (rule R2: BOTH reviewers, `run_in_background: false`)

Independent architect + critic. They agreed on the top three, and each found something the other
did not.

| | finding | fixed |
|---|---|---|
| CRITICAL | commission slider never defaulted; `PRICING_RULES.md` claimed SHIPPED | ✅ `COMMISSION_DEFAULT_PCT` |
| MAJOR | project GC markup unvalidated → silent under-charge | ✅ guarded in `priceProject` |
| MAJOR | project GC markup not reset on customer switch | ✅ reset with `permitCount` |
| MAJOR | `_PDF_TEMPLATE_VERSION` not bumped → stale cached PDFs | ✅ v4 |
| HIGH | re-price fell through to the per-building default on an estimate with no stored count | ✅ falls back to **1** |
| MAJOR | no behavioural test that a proposal reproduces its quoted total | ✅ added |
| MEDIUM | `structure_address` write-only | ✅ in the estimates list |
| MEDIUM | blank Address cell when the property has no street | ✅ prints `—` |
| MEDIUM | `permit_count` reported on a basis that never priced a permit | ✅ forced to the building count |
| LOW | `commission_pct.gross`/`.net` written by nothing | ✅ deleted |
| LOW | bid signature: blank vs `"1"` hashed differently | ✅ hashes the effective count |

**The re-price finding is the one worth remembering.** `permit_count` went from a total function
(`int`, default 1) to a partial one (`None` = derive from the bid shape). On a fresh quote that is
right. On a **reproduction** path it is the one answer that is never right, because the bid was
already priced against a concrete number. A proposal reproduces a bid; it does not re-decide it.

---

## §3 — VERIFICATION

    .venv/bin/ruff check core adapters api jobs      All checks passed
    .venv/bin/python -m pytest tests/ --cov=core --cov-fail-under=97
    cd web && npm run build && npx vitest run        30 tests
    scripts/validate_against_evergrene.py            +4.2% / +1.4% (see §1.2)

⚠️ Run the Evergrene script as `PYTHONPATH=. DB_URL=postgresql+psycopg://app:$(gcloud secrets
versions access latest --secret=db-password)@127.0.0.1:5432/perkins` — the user is **app**, not
postgres, and the module path is needed because `scripts/` is not a package.

---

## §4 — STILL OPEN

1. **Josh's 7.5%**, and whether General Conditions is commissionable (§1.1) — both for Tim.
2. **The `week` profit-floor basis measures the wrong thing.** Tim 2026-07-28 counts schedule time
   *including inspections*; `_apply_project_floor` does `ceil(crew_days / 5)`. No price moves today
   (default `project`, the SPA cannot select `week`) but #449 is written in those terms. His
   inspection/cleanup allowance is **not a number we have** — ask, do not invent.
3. **Wire the SPA deploy into `deploy.yml`.** Unchanged from the pm doc: `deploy.yml` never touches
   `web/`, so a merged UI change is not live until someone hand-runs `firebase deploy`. This
   session's SPA changes are subject to exactly that.
4. **Jon's calls:** `estimating_view` on a writing endpoint; whether to expose `floor_basis` at all.
5. Curate 5 ready portfolio projects (human: photos AND alt text) — isola 1,452 · olsen 802 ·
   fisher-7900 311 · fisher-77 285 · pinnacle 186.
6. `api-run-sa` cannot create a secret (OAuth 502s); `#444` budget blocked on the Billing API;
   `REACH_MI` 8 of 18 gauges unsnapped; Miami charges a whole office day per job.

---

## §5 — GOTCHAS (cumulative; new ones first)

- ⚠️ **A default is only a default where nothing supplies a value.** The SPA sends
  `commission_rate` on every quote, so `config.commission_rate()` has no production caller from
  that screen. `COMMISSION_DEFAULT_PCT` (TS) and `COMMISSION_DEFAULT_RATE` (Python) must track each
  other; each names the other in a comment.
- ⚠️ **Bump `_PDF_TEMPLATE_VERSION` whenever `DEFAULT_TEMPLATE_HTML` changes**, or already-rendered
  proposals keep serving the old bytes and the change is invisible on the document that matters.
- ⚠️ **A reproduction path needs a different default from a creation path.** See §2.
- ⚠️ **Knowify: deliverables carry `ContractId`, NOT `ProjectId`.** The wrong join returns a clean,
  confident, wrong answer.
- ⚠️ Knowify mirror deliverable money is in **CENTS**.
- ⚠️ **CI runs `pytest tests/`** — the whole tree; the pre-push set does not reach
  `tests/test_f2_engine.py`.
- ⚠️ **CI does not deploy the SPA.** Verify the SERVED bundle, not "Deploy complete!".
- ⚠️ `npx tsc --noEmit` is NOT the build gate; `npm run build` (`tsc -b`) is.
- ⚠️ `test_schema_maxlength` binds on IMPORTED CLASS NAMES, not on writes.
- ⚠️ **Migrations are applied BY HAND**; `apply_migrations_adc.py` ignores `DB_URL` (always prod)
  and has no ledger — it replays from 0013 every run. Confirm it reaches DONE.
- ⚠️ `tile_dumpster_count` is a `ceil()` — per-building calls over-count.
- ⚠️ **Reviewer agents must run with `run_in_background: false`** or they return nothing, and R2
  needs BOTH: each found what the other missed again this session.
- ⚠️ **Local models were net-negative on review** — `docs/2026-08-01-local-model-review-postmortem.md`.
- ⚠️ Do NOT `source .env` before GCS work. Use `$HOME/.config/gcloud/perkins-deploy-sa.json`.
- ⚠️ `DB_URL` in `.env` is sqlite; app code needs `postgresql+psycopg://…` over the proxy as user
  **app**, and sessions must set `db.info["tenant_id"]` or `["platform_scope"]`.
- ⚠️ **Search the mailbox, not just transcripts.**

---

## ARCHIVE DIRECTIVE (standing, performed for this doc)

**Performed:** `CONTINUATION-2026-08-01-pm.md` archived to `docs/continuations/`, keeping the
latest three at top level. Inbound links repointed and README's "Most recent" refreshed.
