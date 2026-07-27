# Spec — copy a pricing config to other branches (with per-key exclusions)

**Status:** proposed, not started. **Asked by:** Jon, 2026-07-27 —

> *"We need a copy config button to copy to the other branches, so we only have to do it once. Some
> things need to be excluded, like the cost per day — we need that to stay. How do we choose what to
> exclude in the UI?"*
>
> *"Material cost should be shared by default, overhead and labor costs are branch specific. Can we
> toggle that shared|branch scope somehow? How do we know which are branch and which are shared from
> the UI?"*

## The problem, sized

Every config change this week was applied three times. `seed_pm_incentive_axes.py` writes the same
twelve paths to jupiter, miami and naples in a loop, and `seed_min_margin.py` does the same. That is
fine in a script and impossible in the UI — an admin editing WinterGuard in the Quoting config panel
changes it for one branch and silently leaves the other two on the old number. **Config drift between
branches is currently invisible until a quote comes out wrong.**

But a blanket copy is worse than no copy, because some values are *supposed* to differ per branch —
office burn, crew day rates, demo labour. The next section is the rule for telling them apart.

## The classification rule (Jon, 2026-07-27)

> *"Material cost should be shared by default, overhead and labor costs are branch specific."*

That is the right axis and it is better than my first proposal (default everything to `branch`).
Materials come from ABC and Beacon on negotiated price lists — one company, one price. Labour and
overhead are what the branch's own crews and office actually cost, and Tim has said as much: *"Miami's
overhead is more than Jupiter's and Naples has zero overhead right now"* (7/17 [40:20]).

Applied to the real config, with two categories his rule doesn't name:

| category | scope | keys |
|---|---|---|
| **Material / product** | `shared` | `cuts_calc` tile brands, `specialty_tile_upgrade`, `winterguard_add`, `secondary_water_barrier_add`, `ridge_vent_per_lf`, `penetration_each`, `stucco_metal_per_lf`, `tile_pointing`, `delivery_plywood_vents`, `new_bonus_values`, `permit_processing`, `tile_dumpster_cost` |
| **Labour / overhead / time** | `branch` | `daily_overhead_rates`, `sloped_overhead`, `office_daily_overhead`, `office_men`, `office_oh_basis_reference`, `tile_demo_add`, `metal_demo_add`, `roof_height`, `roof_cuts`, `pitch_7_12_add`, `repair` |
| **Business rules / policy** | `shared` | the whole profit block (`profit_scale`, `profit_floor_*`, `weekly_profit_floor`, `job_profit_floor`, `enforce_profit_floor`, `profit_mode_default`), band-boundary flags, `pm_incentive`, `tile_dumpster_threshold`, `daily_overhead_day_model`, `daily_overhead_weeks_rounding_mode`, `line_items`, `cost_category_tags`, `schema_version` |
| **Geography** | `shared` | `zones`, `counties`, `county_overrides` — **correcting my first draft.** These are a county→zone map, the same table on every branch. The branch differentiation happens because Miami *operates* in HVHZ counties, not because Miami holds a different map. |
| **Neither — wrong shape** | — | `commission_pct`. Keyed `(slope_type)` today; it is per **salesperson** (7/20 [03:49]). It must not be classified until it is re-keyed, or the copy tool will propagate a shape we already know is wrong. |

### The rule exposes a key that cannot be classified as it stands

`sloped_base_cost_lm` is literally **"base cost (L & M)"** — labour *and* material fused into one
number per roof type. Jon's rule cuts straight through it: the M half is shared, the L half is
per-branch, and today it is a single figure applied identically to all three branches. `gutters` and
most of the `low_slope` block have the same problem.

**The data to split them already exists.** 29 of Tim's 273 cell comments carry an explicit
component breakdown:

```
Add $200 for 7/12+   →  Demo L $70 · Tile L $70 · M $40 · OH $90 · P $35
$140 per Sq. to add MTS → L $20 · M $67 · OH $32 · P $18 · Total $140
HVHZ Upgrade         →  L $20 · M $60 · OH $30 · P $15 · Total $125
```

So the honest sequencing is: **classify what can be classified, and mark the fused keys
`_scope: "mixed"` with a pointer to the comment that splits them.** A `mixed` key is never copied and
shows in the UI as work outstanding. Splitting L from M is its own task and probably the more
valuable one — it is what would let Miami carry Miami's labour against the same ABC material price.

## What today's data actually looks like — and why this matters more than it sounds

I diffed the three active configs before writing this. **All 50 shared-shaped keys are byte-identical
across jupiter, miami and naples.** Only three keys exist on one branch alone
(`office_daily_overhead`, `office_men`, `office_oh_basis_reference`, jupiter only).

The branches are clones. So the first job of this feature is not propagating changes — it is
answering **which of those 50 identical values are identical on purpose, and which are identical by
accident.** The flagship accident is right there in the labour column:

> `daily_overhead_rates = {tile: 745, metal: 850, shingle: 700, demo_dry_in_flat: 1050}` — identical
> on all three branches. These arrived with **30 Palm Beach homes**, so they are Jupiter's. Miami and
> Naples are quoting Jupiter's crew cost today, and Naples is supposed to carry **zero** overhead.

Classifying that key `branch` doesn't fix the number, but it makes the gap visible instead of
invisible, which is the whole point.

## What to build

### 1. `_scope` declared per key, and editable

Scope lives next to the value, in the same config the numbers live in — so it versions, diffs and
rolls back with everything else, and there is no second source of truth to drift:

```json
"daily_overhead_rates": { "_scope": "branch", "tile": 745, ... },
"profit_scale":         { "_scope": "shared", "bands": [...] },
"sloped_base_cost_lm":  { "_scope": "mixed",  "_split_hint": "Tim comment: L/M/OH/P", ... }
```

**Default for an unclassified key is `branch`** — fail closed. A new key nobody thought about is
never copied silently; worst case it has to be set three times, which is today's behaviour anyway.

### 2. Yes, scope is toggleable — but the two directions are not symmetric

This is the part worth designing carefully, because one direction is safe and the other can destroy a
branch's number.

**`shared` → `branch` is safe.** The value forks: every branch keeps what it has, and they are now
free to diverge. Nothing changes on any quote. Allow it inline, one click.

**`branch` → `shared` is a merge, and merges need a winner.** The moment a key is shared, the next
copy overwrites the other branches with the source's value. If the branches already hold *different*
values, promoting silently picks one and discards two. So promotion must:

1. **Show the current values side by side** and require an explicit choice of which becomes the
   shared value — no default, no "source branch wins" convention that people stop reading.
2. **Refuse if any branch's value is missing** rather than treating absent as agreeing.
3. Write the choice into `_source` on the key, as the configs already do for every sourced number, so
   six months from now the reason is attached to the value.
4. Take effect as a **new config version per branch** via the existing immutable-version path — so
   `git`-style rollback of a bad promotion is one activation away.

Where all branches happen to agree (which today is all 50), promotion is a no-op on the numbers and
the dialog says so — that is the common case and should be one confirm.

Restrict scope changes to the same admin role that can edit prices, and log them to the config's
`created_by`. Scope is a money decision, not a display preference.

### 3. How you can tell from the UI

Three levels, cheapest first — I would build them in this order:

**a. A badge on every row in the config editor**, always visible, never behind a hover:

```
  Daily overhead rates          [ BRANCH ]  tile $745 · metal $850 · shingle $700 · demo $1,050
  Profit scale                  [ SHARED ]  30+ sq @ $100/sq  …
  Base cost (L & M)             [ MIXED  ]  needs L/M split before it can be classified   ⚠
```

`SHARED` in a neutral grey, `BRANCH` in Perkins light blue (`#41B1E5`) to read as "this one is yours",
`MIXED` in amber with the warning. Clicking the badge is how you toggle it, which answers "how do we
change it" with the same affordance that answers "how do we see it".

**b. Group the editor by scope, not by alphabetical key.** Two collapsible sections — *"Shared across
all branches"* and *"Specific to {branch}"* — so the question "what is mine?" is answered by where a
field sits, before anyone reads a badge. A third section for `MIXED` doubles as the to-do list.

**c. An inline banner when you edit a `shared` field:** *"This changes all three branches."* The
badge tells you the state; the banner catches you in the act.

For the copy modal itself, keep the preview-first design: it shows what **will** copy and what
**won't**, with `[why?]` on each excluded row linking to the `_source`. It never asks you to tick 50
boxes.

### 4. The "branches differ" badge

Unchanged from the first draft and still the highest-value piece: flag any `shared` key whose value
differs between branches. Today that count is zero — which is exactly why it is worth adding now,
while the baseline is clean and any future divergence is real news.

### 5. Server side

`POST /admin/pricing-config/{branch}/copy-to`
`{"targets": ["miami","naples"], "exclude_paths": [...], "dry_run": true}`

`PATCH /admin/pricing-config/{branch}/scope`
`{"path": "daily_overhead_rates", "scope": "branch", "winner_branch": null, "dry_run": true}`

Both reuse the immutable-version pattern the seeders use — read active, merge, write a new version,
activate; never mutate in place. `dry_run` returns exactly what the modal renders, so the preview and
the write are the same code path. Idempotent: no change means no new version.

## Test plan

- **The one that matters:** copy jupiter → miami and assert every `branch`-scoped key is
  **byte-identical** to miami's previous version — `daily_overhead_rates`, `sloped_overhead`,
  `office_*`, `tile_demo_add`, `metal_demo_add`, `roof_height`, `roof_cuts`, `repair`. This is the
  test that fails when someone reclassifies a money key by accident.
- `commission_pct` and any `mixed` key are refused by the copy, not silently skipped — a skip that
  looks like success is how the old shape would propagate.
- Scope toggle, `shared` → `branch`: all three branches keep their value, no new divergence, no quote
  moves.
- Scope toggle, `branch` → `shared` **with divergent values**: refuses without an explicit winner;
  with a winner, the two losers change and the choice lands in `_source`.
- Scope toggle, `branch` → `shared` **with a value missing on one branch**: refuses. Absent must not
  read as agreeing.
- Unit: unclassified key defaults to `branch`; a shared nested path merges without clobbering a
  sibling branch-scoped key under the same parent.
- Round-trip: copy, then diff — zero `shared` differences, all `branch` differences preserved.
- Idempotency: a second copy writes no new version.
- Regression guard on today's baseline: the 50 keys currently identical across branches must still be
  identical after a classify-only pass. Classifying changes scope, never a number.

## Rollout

1. **Classify only, change nothing.** Annotate `_scope` across
   `infra/fixtures/pricing_config_exhibit_b.json` per the table above, `mixed` where L and M are
   fused, evidence in `_source`. Seed to all three and assert no number moved.
2. The **"branches differ"** badge and the scope badges — read-only, no write path yet. This alone
   surfaces that Miami and Naples are running Jupiter's crew rates.
3. Scope toggle, `shared` → `branch` first (the safe direction), then promotion with the winner
   dialog.
4. Copy modal, preview-first.
5. Separately, and probably worth more than all of the above: **split L from M** on
   `sloped_base_cost_lm`, `gutters` and the `low_slope` block, using the 29 comments that carry the
   breakdown. Until that lands, Jon's rule can only be applied to about half the money.

R2 (architect + critic) before it touches prod — this writes to the money path on three branches at
once, which is precisely the blast radius that rule exists for.

## Open question for Jon

Naples currently carries **zero** overhead deliberately. When the copy tool lands, should Naples be
treated as a real branch that has opted out, or as **not yet configured**? They look identical in the
data and behave differently: the first should never be "fixed" by a copy, the second should be flagged
as incomplete. Suggest an explicit `"_status": "not_configured"` on a branch so the badge can tell
them apart. See `PRICING_RULES.md` §3.
