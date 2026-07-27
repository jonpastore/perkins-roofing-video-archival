# Spec — copy a pricing config to other branches (with per-key exclusions)

**Status:** proposed, not started. **Asked by:** Jon, 2026-07-27 — *"we need a copy config button to
copy to the other branches, so we only have to do it once. Some things need to be excluded, like the
cost per day — we need that to stay. How do we choose what to exclude in the UI?"*

## The problem, sized

Every config change this week was applied three times. `seed_pm_incentive_axes.py` writes the same
twelve paths to jupiter, miami and naples in a loop, and `seed_min_margin.py` does the same. That is
fine in a script and impossible in the UI — an admin editing WinterGuard in the Quoting config panel
changes it for one branch and silently leaves the other two on the old number. **Config drift between
branches is currently invisible until a quote comes out wrong.**

But a blanket copy is worse than no copy, because some values are *supposed* to differ per branch.
From the live sheets and Tim's own words:

| genuinely per-branch — must NOT be copied | evidence |
|---|---|
| `office_daily_overhead`, `office_men`, `office_oh_basis_reference` | Miami ≈$4,140/day (9×$460, 12×$345, 15×$275) vs Jupiter ≈$1,400/day (4×$345, 7×$200, 10×$140). Naples zero — *"Miami's overhead is more than Jupiter's and Naples has zero overhead right now"*, 7/17 [40:20] |
| `daily_overhead_rates` (the $1,050 / $745 / $850 / $700 per-day costs) | Jon's exclusion example. These arrived with 30 **Palm Beach** homes, so they are Jupiter's; Miami's are unknown |
| `commission_pct` | per **salesperson**, 7/20 [03:49] — see `PRICING_RULES.md` §11 |
| `zones`, `counties`, `county_overrides` | branch geography |

Everything else — the profit scale, band edges, the weekly floor, PM incentive axes, tile brands,
adders, low-slope values, fixed fees — is a **Perkins-wide rule** that should move together. Those are
exactly the twelve paths I hand-copied three times today.

## What to build

### 1. A `branch_scoped` classification on the config schema, not a UI checkbox list

The naive design is a modal with a checkbox per key. With ~45 top-level keys and nested blocks
(`low_slope.overhead.FBC.tpo_oh`) that is an unusable wall of switches, and it puts the safety of a
money path in the hands of whoever remembers to untick the right box at 5pm.

Instead, **each key declares its own scope in one place**, next to the value:

```json
"daily_overhead_rates": { "_scope": "branch", "demo_dry_in_flat": 1050, "tile": 745, ... },
"profit_scale":         { "_scope": "shared", "bands": [...] }
```

Default for an undeclared key is **`branch`** — fail closed. A new key someone adds without thinking
is never copied silently; the worst case is that it has to be set three times, which is today's
behaviour. A `_scope` key sits alongside the existing `_source` / `_pending_*` convention the configs
already use, so nothing new is introduced.

Add a test that every top-level key carries an explicit `_scope`, so the list cannot rot — the same
shape as the guard in `seed_pm_incentive_axes.py` that asserts prod-only keys survive a merge.

### 2. UI: preview the diff, don't list the keys

`web/src/pages/AdminConfig.tsx`, on the branch selector: **"Copy to other branches…"**.

The modal does **not** ask which keys to include. It shows, per target branch, exactly what would
change, grouped:

```
Copy jupiter v19  →  miami (v20), naples (v19)

  WILL COPY — 4 shared values differ
     profit_scale.bands            miami: 20-29 @ $110   →  @ $120
     winterguard_add               naples: 140           →  135
     pm_incentive.FBC.bands        miami: (legacy shape) →  size bands
     low_slope.overhead.FBC.tpo_oh naples: 135           →  125

  WILL NOT COPY — 3 branch-specific keys, left alone            [why?]
     daily_overhead_rates          miami keeps its own
     office_daily_overhead         miami $4,140/day, naples $0
     commission_pct                set per salesperson

  ✓ miami and naples are already current on 38 other shared values
```

Per-row **opt-out** on the copy list (uncheck a row you don't want this time) — but no opt-*in* on the
excluded list. Overriding a branch-scoped key is a deliberate act that belongs in the per-branch
editor, not in a bulk copy. `[why?]` links to the `_source` string already stored on the key.

### 3. Server side

`POST /admin/pricing-config/{branch}/copy-to`
body: `{"targets": ["miami","naples"], "exclude_paths": ["winterguard_add"], "dry_run": true}`

- Reuses the **immutable-version pattern** exactly as the seeders do: read active, deep-merge only
  the shared paths, write a new version, activate. Never mutate in place.
- `dry_run: true` returns the diff the modal renders — same code path, so what you preview is what
  ships.
- One new version per target branch, labelled `copied shared values from {source} v{n}`, with
  `created_by` = the acting user.
- Requires the existing `billing_manage`-equivalent admin role; refuse if the source config has
  unsaved edits.
- Idempotent: copying twice with nothing to change writes no version and returns "already current".

### 4. Drift visibility, which is the real win

A **"branches differ"** badge on the config page whenever two branches hold different values for a
`shared` key. That is the bug this feature exists to prevent, and it is worth surfacing even before
anyone presses Copy. Cheap to compute — the same diff the dry run produces.

## Test plan

- Unit: `_scope` defaults to `branch` when absent; a shared nested path merges without clobbering a
  sibling branch-scoped key.
- **The one that matters:** copy jupiter → miami and assert `daily_overhead_rates`,
  `office_daily_overhead`, `office_men`, `commission_pct` and `counties` are **byte-identical** to
  miami's previous version. This is the test that fails if someone reclassifies a money key.
- Schema: every top-level key declares `_scope`.
- Round-trip: copy, then diff — zero shared differences, all branch-scoped differences preserved.
- Idempotency: second copy writes no new version.

## Rollout

1. Annotate `_scope` across `infra/fixtures/pricing_config_exhibit_b.json`, defaulting to `branch`
   and promoting to `shared` only with the evidence written into `_source`. Seed to all three.
2. API + dry-run diff.
3. Modal, preview-first.
4. The "branches differ" badge.

R2 (architect + critic) before it touches prod — this writes to the money path on three branches at
once, which is precisely the blast radius that rule exists for.

## Open question for Jon

Naples currently carries **zero** overhead deliberately. When the copy tool lands, should Naples be
treated as a real branch that has opted out, or as **not yet configured**? They look identical in the
data and behave differently: the first should never be "fixed" by a copy, the second should be flagged
as incomplete. Suggest an explicit `"_status": "not_configured"` on a branch so the badge can tell
them apart. See `PRICING_RULES.md` §3.
