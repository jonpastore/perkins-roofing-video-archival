# TRD-F2 — Estimating Engine Complete (Exhibit-B Pricing)

**Wave:** F2  
**Date:** 2026-07-08  
**Status:** DRAFT (R2 fixes applied — pending Jon approval)  
**Grounding:** full-funnel plan §5, §9 F2 row, §10 open items 2–4; CONTINUATION-2026-07-08 §3; Exhibit B (Ez-Bids legal package); `core/estimator.py` current stub; `perkins-ezbids-proposal` + `perkins-squarequote-review` memories.

---

## 1. Scope

### In scope
- Versioned, per-tenant, per-branch `pricing_configs` table with JSONB config, immutable-row versioning, active-version pointer, and Admin editor API (CRUD + activate).
- RFC 8785 JSON Canonicalization + SHA-256 hash (`pricing_config_hash`) stamped on every quote and estimate.
- Exhibit B pricing rules fully encoded as the committed seed fixture (JSON in repo). Engine becomes pure `estimate(config, input)` with zero hard-coded constants — all rates, thresholds, and flags are config-driven.
- Cost-category tags on every line item (Labor / Materials / Equipment / Sub / Misc / OH / Profit) enabling correct 13% profit floor and 33% profit+OH floor computation.
- Commission as a percentage of profit dollars (10% sloped, 15% low-slope; sloped-HVHZ rate is an open item resolved via config — no code change needed when Tim answers).
- Low-slope category (Exhibit B §4): TPO, coatings, silicone, BUR base costs; insulation tiers; deck types; per-layer tear-off extras; flat/TPO/coatings overhead; crane/trash-chute height rules.
- Branches (Miami / Jupiter / Naples) with per-branch default `code_zone`; `code_zone` is per-property, overridable per quote; mixed-tier applies per slope type and line item.
- HVHZ zone = Miami-Dade + Broward counties. FBC zone = Palm Beach + Lee + St. Lucie counties. Per-county override layer on top of zone tables: permit fees, 7% materials-tax flag on some tile, county-specific line items.
- Delta fixes from stub: PM incentive as zone×job-size matrix; tile dumpster as threshold-count (HVHZ every >15 SQ, FBC every 30 SQ); sliding-scale boundary band confirmed as lower-inclusive / upper-exclusive (config flag so Tim's answer is a data change); commission denominators corrected.
- 5 golden-file CI fixtures (Exhibit C): 498-SQ low-slope HVHZ · 15-SQ low-slope FBC · 28-SQ sloped HVHZ · 28-SQ sloped FBC · 41.5-SQ standing-seam FBC. Tolerance ±$0.01 or ±0.01%. Manual-entry AND measurement-fed paths. Permanent in CI.
- Admin Estimating tab: versioned config editor (diff view, hash display), branch management, code-zone defaults, measurement provider selector.
- Migration `0014_pricing_configs.sql` (new table) and `0015_estimates_hash.sql` (hash column on estimates).
- Full rollout and rollback documentation.

### Non-goals (F2)
- Quoting / proposals / customer-facing accept pages (F3).
- RLS / multi-tenant isolation hardening (F4) — `tenant_id` column is added now (F0 convention) but RLS policies are F4's problem.
- Live SquareQuote/Solar API integration (F2b) — F2 wires the `Measurement` model and provider interface; the Solar adapter ships in F2b. Manual entry is the live path for F2 acceptance.
- Knowify push (F3).
- iOS app (non-goal globally, §0).

---

## 2. Data model

### 2.1 `pricing_configs`

```sql
CREATE TABLE pricing_configs (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    branch          VARCHAR NOT NULL,         -- "miami" | "jupiter" | "naples"
    version         INTEGER NOT NULL,         -- monotonically increasing per (tenant_id, branch)
    label           VARCHAR,                  -- human label, e.g. "2026-Q3 Exhibit B"
    config          JSONB NOT NULL,           -- full pricing config (see §3 schema)
    config_hash     CHAR(64) NOT NULL,        -- RFC 8785 canon + SHA-256 hex
    is_active       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by      VARCHAR NOT NULL,         -- email from auth claims
    CONSTRAINT uq_pricing_configs_tenant_branch_version
        UNIQUE (tenant_id, branch, version),
    CONSTRAINT uq_pricing_configs_active_branch
        UNIQUE (tenant_id, branch, is_active)
        DEFERRABLE INITIALLY DEFERRED       -- one active row per (tenant, branch); deferred for atomic swap
);
CREATE INDEX ix_pricing_configs_tenant_branch ON pricing_configs (tenant_id, branch);
```

**Immutability contract:** rows are never UPDATEd except to flip `is_active`. Every edit creates a new row with `version = MAX(version) + 1` for that (tenant, branch). Activating a version sets its `is_active = TRUE` and sets `is_active = FALSE` on the prior active row in one deferred transaction. Rollback = activate any prior version; no data loss, no code deploy.

### 2.2 `estimates`

New columns added to the estimates table (migration `0015`):

```sql
ALTER TABLE estimates
    ADD COLUMN IF NOT EXISTS pricing_config_id  INTEGER REFERENCES pricing_configs(id),
    ADD COLUMN IF NOT EXISTS pricing_config_hash CHAR(64),
    ADD COLUMN IF NOT EXISTS branch              VARCHAR,
    ADD COLUMN IF NOT EXISTS code_zone           VARCHAR,   -- "HVHZ" | "FBC"
    ADD COLUMN IF NOT EXISTS county              VARCHAR;   -- "miami_dade" | "broward" | "palm_beach" | "lee" | "st_lucie"
```

The `pricing_config_hash` is stamped at estimate-creation time from the active config's hash, allowing post-facto audit reproduction independent of future config changes.

### 2.3 `measurements` (interface stub — full model in TRD-F2b)

F2 adds the model shell and manual-entry provider so golden-file tests can exercise the measurement-fed path. The Solar API adapter is F2b.

```sql
CREATE TABLE measurements (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id),
    property_id     INTEGER,                  -- FK to properties (F3); nullable in F2
    provider        VARCHAR NOT NULL,         -- "manual" | "google_solar" | "nearmap"
    status          VARCHAR NOT NULL DEFAULT 'pending',  -- pending | complete | failed
    total_sq        NUMERIC(10,2),            -- total squares (100 sqft each)
    hips_lf         NUMERIC(10,2),
    ridges_lf       NUMERIC(10,2),
    valleys_lf      NUMERIC(10,2),
    rakes_lf        NUMERIC(10,2),
    eaves_lf        NUMERIC(10,2),
    wall_flashings_lf NUMERIC(10,2),
    pitch_primary   NUMERIC(5,2),             -- dominant pitch (rise/run)
    segments_json   JSONB,                    -- per-segment pitch/azimuth/area (F2b Solar detail)
    confidence      NUMERIC(4,3),             -- 0.0–1.0; NULL for manual
    raw_payload     JSONB,                    -- full provider response retained
    provenance_note VARCHAR,                  -- "Manual entry by <email> on <date>"
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by      VARCHAR NOT NULL
);
```

---

## 3. Pricing config JSONB schema

The config JSONB is the single source of truth for all rates. Zero constants in `core/estimator.py` after F2. The committed seed fixture at `infra/fixtures/pricing_config_exhibit_b.json` is the canonical Exhibit B encoding; it seeds all three branches for tenant 1 (Perkins) in migration `0014`.

```jsonc
{
  // ── Meta ──────────────────────────────────────────────────────────────────
  "schema_version": 1,
  "exhibit_version": "B-2026-07",

  // ── Boundary band rule ────────────────────────────────────────────────────
  // lower-inclusive / upper-exclusive sliding-scale tiers (PRESUMED; confirm w/ Tim — open item §10.3)
  "boundary_inclusive_lower": true,
  "boundary_exclusive_upper": true,

  // ── Code zones ────────────────────────────────────────────────────────────
  "zones": ["HVHZ", "FBC"],
  "counties": {
    "miami_dade": "HVHZ",
    "broward": "HVHZ",
    "palm_beach": "FBC",
    "lee": "FBC",
    "st_lucie": "FBC"
  },

  // ── County overrides (on top of zone tables) ──────────────────────────────
  "county_overrides": {
    "miami_dade": {
      "permit_fee_add": 0,
      "materials_tax_7pct_tile": false,
      "extra_line_items": {}
    },
    "broward": {
      "permit_fee_add": 0,
      "materials_tax_7pct_tile": false,
      "extra_line_items": {}
    },
    "palm_beach": {
      "permit_fee_add": 0,
      "materials_tax_7pct_tile": false,
      "extra_line_items": {}
    }
    // lee, st_lucie follow same pattern
  },

  // ── Sloped base cost (Labor + Materials) per square ───────────────────────
  "sloped_base_cost_lm": {
    "HVHZ": {
      "13_tile":             780,
      "barrel_tile":        1455,
      "3tab_shingle":        395,
      "dimensional_shingle": 420,
      "standing_seam_metal": 1020
    },
    "FBC": {
      "13_tile":             770,
      "barrel_tile":        1435,
      "3tab_shingle":        395,
      "dimensional_shingle": 420,
      "standing_seam_metal": 750
    }
  },

  // ── Sloped overhead per square ────────────────────────────────────────────
  "sloped_overhead": {
    "HVHZ": {
      "3tab_shingle":        125,
      "dimensional_shingle": 125,
      "13_tile":             270,
      "barrel_tile":         420,
      "standing_seam_metal": 280
    },
    "FBC": {
      "3tab_shingle":        105,
      "dimensional_shingle": 105,
      "13_tile":             185,
      "barrel_tile":         350,
      "standing_seam_metal": 205
    }
  },

  // ── Profit sliding scale — list of [max_sq_exclusive, profit_per_sq] ──────
  // Tiers apply lower-inclusive / upper-exclusive per boundary_* flags above.
  // Last tier max is null (catch-all for any size above).
  "profit_scale": [
    [1,  400],
    [4,  200],
    [7,  160],
    [14, 140],
    [20, 120],
    [29, 110],
    [null, 100]
  ],

  // ── Cost-category tags for line items ─────────────────────────────────────
  // Each line item in the engine output carries one of these tags.
  // Allowed values: "Labor" | "Materials" | "Equipment" | "Sub" | "Misc" | "OH" | "Profit"
  "cost_category_tags": {
    "base_cost_lm":           "Materials",
    "overhead":               "OH",
    "profit":                 "Profit",
    "roof_cuts":              "Labor",
    "roof_height":            "Labor",
    "tile_pointing":          "Labor",
    "specialty_tile":         "Materials",
    "pitch_7_12_add":         "Labor",
    "tile_demo":              "Labor",
    "metal_demo":             "Labor",
    "secondary_water_barrier":"Materials",
    "winterguard":            "Materials",
    "stucco_metal":           "Labor",
    "penetrations":           "Labor",
    "ridge_vents":            "Materials",
    "delivery_plywood_vents": "Materials",
    "new_bonus_values":       "Misc",
    "permit_processing":      "Misc",
    "tile_dumpster":          "Equipment",
    "pm_incentive":           "Misc",
    "insulation":             "Materials",    // no profit added per Exhibit B
    "tapered":                "Materials"     // no OH or profit per Exhibit B
  },

  // ── Margin floors ─────────────────────────────────────────────────────────
  "profit_floor_pct": 0.13,
  "profit_plus_oh_floor_pct": 0.33,
  // Floor exclusions per Exhibit B:
  //   insulation: no Profit added (Exhibit B: "no profit added" — OH still applies to insulation).
  //               floor_excluded = [Profit] only.
  //   tapered:    no OH or Profit (Exhibit B: "no OH or profit").
  //               floor_excluded = [OH, Profit].
  // NOTE: If Exhibit B's OH treatment of insulation is read as ambiguous, Tim must confirm
  // before the seed fixture is locked. The current reading (insulation carries OH, tapered does not)
  // is the conservative Exhibit B interpretation.
  "floor_excluded_categories": {
    "insulation": ["Profit"],
    "tapered":    ["OH", "Profit"]
  },

  // ── Commission ────────────────────────────────────────────────────────────
  "commission_pct": {
    "sloped": 0.10,
    "low_slope": 0.15
    // sloped_HVHZ: OPEN — defaults to sloped (0.10) until Tim confirms; change is config-only
  },

  // ── PM incentive — zone × job_size matrix ────────────────────────────────
  // Bands share edges across zones: <20 SQ residential, 20–50 SQ commercial, >50 SQ commercial.
  // Both zones use the same band edges; amounts differ by zone.
  // Engine raises ConfigError (never silent 0) on any unmatched (zone, project_kind, sq) cell.
  // FULL MATRIX — Tim-verify required before activation (all cells are open items per plan §10.5).
  "pm_incentive": {
    "HVHZ": {
      "residential_lt20":    150,   // residential, SQ < 20
      "commercial_20_50":    300,   // commercial, 20 ≤ SQ ≤ 50
      "commercial_gt50":     300    // commercial, SQ > 50  ← previously missing; Tim-verify amount
    },
    "FBC": {
      "residential_lt20":     50,   // residential, SQ < 20  (was residential_lt10 + residential_10_30 split — unified to match HVHZ band edge)
      "commercial_20_50":    100,   // commercial, 20 ≤ SQ ≤ 50
      "commercial_gt50":     250    // commercial, SQ > 50
    }
  },
  // NOTE: The FBC residential band was previously split at 10 SQ (lt10=$50, 10-30=$100).
  // PRD F2-11 shows a single <20 SQ residential band for both zones ($50 FBC / $150 HVHZ).
  // This TRD adopts the PRD-F2-11 band structure (shared band edges across zones).
  // Tim must confirm: (a) FBC residential lt20 = $50 flat (not split at 10), (b) HVHZ/FBC >50 amounts.
  // Until Tim confirms, both zones use the PRD-F2-11 values above.

  // ── Roof height per square ────────────────────────────────────────────────
  "roof_height": {
    "1_story":    0,
    "2_stories":  50,
    "3_5_stories": null,   // no per-sq charge; flat add applies
    "6_plus":     null     // crane needed — manual quote
  },
  "roof_height_3_5_flat_add": 1200,

  // ── Roof cuts per square ──────────────────────────────────────────────────
  "roof_cuts": { "low": 0, "medium": 25, "high": 50 },

  // ── Tile pointing per square ──────────────────────────────────────────────
  "tile_pointing": { "no": 0, "yes": 200 },

  // ── Specialty tile upgrades per square ───────────────────────────────────
  "specialty_tile_upgrade": {
    "HVHZ": {
      "santa_fe_clay_s":      160,
      "verea_caribbean_s":    120,
      "verea_s":              195
    },
    "FBC": {
      "santa_fe_clay_s":      160,
      "terracottagres_s_rustic": 120,
      "verea_s":              195
    }
  },

  // ── Pitch / demo adders per square ───────────────────────────────────────
  "pitch_7_12_add":             200,
  "tile_demo_add":               40,
  "metal_demo_add":              60,
  "secondary_water_barrier_add": 75,
  "winterguard_add":            140,

  // ── Linear / each adders ─────────────────────────────────────────────────
  "stucco_metal_per_lf":   9,
  "penetration_each":     75,
  "ridge_vent_per_lf":  9.79,

  // ── Project fixed costs ───────────────────────────────────────────────────
  "delivery_plywood_vents": 650,
  "new_bonus_values":       1350,
  "permit_processing":       500,
  "permit_commercial_add":   500,

  // ── Tile dumpster — threshold count ──────────────────────────────────────
  // Formula: count = ceil(sq / threshold[zone])  (applied automatically for tile roofs)
  // boundary_inclusive: controls whether the threshold boundary SQ itself triggers the next
  // dumpster (true = inclusive, i.e. exactly 15 SQ HVHZ → 1 dumpster; false = exclusive).
  // Default: true (lower-inclusive). Tim-confirm required (open item §10.6).
  "tile_dumpster_cost": 300,
  "tile_dumpster_threshold": {
    "HVHZ": 15,
    "FBC":  30
  },
  "tile_dumpster_boundary_inclusive": true,

  // ── Zone-specific line items ───────────────────────────────────────────────
  "line_items": {
    "HVHZ": {
      "blown_in_iso_r19": 135,
      "turbine_vents":    257.50,
      "solar_vents":     1339.00
    },
    "FBC": {
      "blown_in_iso_r19": 135,
      "turbine_vents":    257.50,
      "solar_vents":     1489.00
    }
  },

  // ── Low-slope category (Exhibit B §4) ─────────────────────────────────────
  "low_slope": {
    "base_cost_lm": {
      "HVHZ": {
        "tpo":      /* OPEN — Tim to supply */  null,
        "coatings": null,
        "silicone": null,
        "bur":      null
      },
      "FBC": {
        "tpo":      null,
        "coatings": null,
        "silicone": null,
        "bur":      null
      }
    },
    "overhead": {
      "HVHZ": { "flat_oh": null, "tpo_oh": null, "coatings_oh": null },
      "FBC":  { "flat_oh": null, "tpo_oh": null, "coatings_oh": null }
    },
    "insulation_tiers": [
      // [max_sq, cost_per_sq]; no profit added (Exhibit B)
    ],
    "tapered_cost_per_sq": null,       // no OH or profit (Exhibit B)
    "deck_types": {
      "existing_concrete":   0,
      "plywood_replace":     null
    },
    "tear_off_per_layer_per_sq": null,
    "crane_threshold_stories": 3,
    "trash_chute_flat_add":  1200
  }
}
```

Null values are placeholders that Tim must supply before the low-slope path is live. The engine raises a `ConfigError` (not a crash) when a required null is encountered and the path is exercised.

---

## 4. Pricing rules (exhaustive)

This section is the spec the engine is built to. Ambiguities noted as OPEN ITEMS (§10).

### 4.1 Sloped roofs

**Per-square build-up:**

```
base = sloped_base_cost_lm[zone][roof_type]       — tag: Materials
oh   = sloped_overhead[zone][roof_type]            — tag: OH
pft  = profit_scale_lookup(num_squares, config)    — tag: Profit

per_sq = base + oh + pft
       + roof_cuts[cuts_level]                     — tag: Labor
       + roof_height[height_level]                 — tag: Labor  (0 for 1-story)
       + tile_pointing[pointing]                   — tag: Labor
       + specialty_tile_upgrade[zone][tile] or 0   — tag: Materials
       + pitch_7_12_add  (if pitch ≥ 7/12 AND tile)— tag: Labor
       + tile_demo_add   (if demo AND tile)         — tag: Labor
       + metal_demo_add  (if demo AND metal)        — tag: Labor
       + secondary_water_barrier_add (if flag)      — tag: Materials
       + winterguard_add (if flag)                  — tag: Materials

squares_subtotal = per_sq × num_squares
```

**Profit sliding scale lookup:**

Tiers sorted ascending by max. Boundary rule: `lower_inclusive=True`, `upper_exclusive=True` — i.e., tier `[prev_max, max)`. Last tier (max=null) is catch-all. Config flag `boundary_inclusive_lower` / `boundary_exclusive_upper` controls this so Tim's answer becomes a one-field change.

**Project fixed costs:**

```
delivery_plywood_vents = 650                       — tag: Materials
new_bonus_values       = 1350                      — tag: Misc
permit_processing      = 500 + (500 if commercial) — tag: Misc
tile_dumpster          = 300 × floor(num_squares / threshold[zone])
                         (if tile roof AND num_squares > 0)     — tag: Equipment
stories_3_5_add        = 1200 (if height == "3_5_stories")     — tag: Labor
```

Tile dumpster formula: `count = ceil(num_squares / threshold)` where threshold = 15 (HVHZ) or 30 (FBC). Applied automatically for tile roofs — not opt-in. The `tile_dumpster_boundary_inclusive` config flag controls whether the threshold boundary itself triggers the next dumpster; default true (Tim-confirm open item §10.6).

**Project-level line items (optional, per quote):**

```
stucco_metal = stucco_metal_per_lf × lf            — tag: Labor
penetrations = penetration_each × count            — tag: Labor
ridge_vents  = ridge_vent_per_lf × lf             — tag: Materials
+ any keys in line_items[zone]                     — tag: Materials
```

**PM incentive (zone × job_size matrix):**

Bands are shared across zones (same SQ breakpoints, different amounts per zone). The engine does a strict cell lookup from config and raises `ConfigError` — never returns a silent 0 — if the (zone, project_kind, sq_range) combination has no matching cell.

| Job kind | SQ range | HVHZ | FBC |
|---|---|---|---|
| Residential | < 20 SQ | $150 | $50 |
| Commercial | 20–50 SQ | $300 | $100 |
| Commercial | > 50 SQ | $300* | $250 |

*HVHZ commercial > 50 SQ amount is Tim-verify (see open item §10.5). Current value = $300 (same as 20–50). Tag: Misc.

**County overrides (applied after zone table):**

For each county in `county_overrides[county]`:
- `permit_fee_add`: added to permit_processing line item.
- `materials_tax_7pct_tile`: if True, multiply all Materials-tagged tile line items by 1.07.
- `extra_line_items`: dict of name → amount appended to line items.

**Project total:**

```
project_total = squares_subtotal
              + sum(project_fixed_costs)
              + sum(line_items)
              + pm_incentive
              + county_override_adds
```

### 4.2 Low-slope roofs (Exhibit B §4)

Low-slope types: `tpo`, `coatings`, `silicone`, `bur`.

**Per-square build-up (low-slope):**

```
base = low_slope.base_cost_lm[zone][roof_type]     — tag: Materials
oh   = low_slope.overhead[zone][oh_key]            — tag: OH
pft  = profit_scale_lookup(num_squares, config)    — tag: Profit

per_sq_low = base + oh + pft
           + tear_off_per_layer × layers           — tag: Labor
           + deck_type_add (if deck replacement)   — tag: Materials
```

**Insulation (no profit added per Exhibit B; OH still applies):**

```
insulation_cost = insulation_tier_lookup(num_squares) × num_squares  — tag: Materials
```

Insulation carries overhead (OH) but no profit per Exhibit B. It is excluded from the profit floor denominator only. `floor_excluded_categories.insulation = ["Profit"]`. OH is still computed on insulation lines and included in the OH total.

**Tapered insulation (no OH or profit per Exhibit B):**

```
tapered_cost = tapered_cost_per_sq × num_squares   — tag: Materials
```

Excluded from both OH and profit floor denominators. Tag `floor_excluded_categories.tapered = ["OH", "Profit"]`.

**Height rules (low-slope):**

Same `roof_height` table as sloped. For 3–5 stories: crane threshold applied if `num_squares` above config `crane_threshold_stories`; `trash_chute_flat_add` = $1,200. For 6+ stories: manual quote required; engine raises `QuoteRequiresManualReview`.

### 4.3 Margin floor enforcement

After computing project_total, the engine computes floors.

**Canonical denominator — `eligible_base`:**

```
eligible_base = project_total
              − sum(line_items tagged "Profit")           # Profit itself excluded from its own denominator
              − sum(line_items in floor_excluded_categories)  # insulation + tapered line items
```

In English: `eligible_base` is the project total minus profit dollars minus any floor-exempt line items (insulation, tapered). Both floor percentages use this same `eligible_base` as their denominator. This is the single canonical denominator for all margin floor math.

**Profit floor (13%):**

```
profit_pct = profit_dollars / eligible_base
floor_ok   = profit_pct >= 0.13
```

**Profit+OH floor (33%):**

```
oh_dollars       = sum(line_items tagged "OH")
                   − sum(OH-tagged items whose key is in floor_excluded_categories with "OH" listed)
combined_pct     = (profit_dollars + oh_dollars) / eligible_base
floor_ok_combined = combined_pct >= 0.33
```

Both checks are surfaced in the estimate result with the computed percentages, numerators, and denominators — not just a boolean. The API returns `margin_warnings` when a floor is not met; it does not block the estimate (Tim may override in edge cases), but the UI must display a warning prominently.

**Exhibit-B numeric example (golden fixture requirement):**

This worked example must be encoded as a pinned golden fixture in `tests/fixtures/golden/floor_exhibit_b.json` and asserted by `test_floor_exhibit_b_example`. Any future change to the floor formula must keep this fixture passing.

```
Inputs (28 SQ sloped HVHZ, 13" tile, 1-story, no options):
  base (Materials):        $780/sq × 28 = $21,840
  overhead (OH):           $270/sq × 28 =  $7,560
  profit (Profit):         $120/sq × 28 =  $3,360   [tier: 20–29 SQ → $120/sq]
  delivery/vents (Materials):              $   650
  new_bonus (Misc):                        $ 1,350
  permit (Misc):                           $   500
  pm_incentive (Misc):                     $   150   [HVHZ residential <20... wait: 28 SQ > 20 → commercial_20_50 = $300]

Correction — 28 SQ commercial HVHZ:
  pm_incentive (Misc):                     $   300

  project_total = 21,840 + 7,560 + 3,360 + 650 + 1,350 + 500 + 300 = $35,560

Floor computation (no insulation or tapered lines in this scenario):
  eligible_base = 35,560 − 3,360 (Profit) − 0 (no floor-exempt lines) = $32,200

  profit_pct   = 3,360 / 32,200 = 10.43%   → BELOW 13% floor → margin_warning: "profit_floor"
  combined_pct = (3,360 + 7,560) / 32,200 = 10,920 / 32,200 = 33.91%  → above 33% floor ✓

Expected result: profit_floor warning fires; combined floor passes.
```

This example is deliberately constructed to trigger the profit-floor warning so the test covers both the passing and failing branch. The exact numbers above are the pinned expected values; the fixture must assert `margin_warnings == ["profit_floor"]` and `combined_floor_ok == True`.

### 4.4 Commission

```
commission = profit_dollars × commission_pct[slope_type]
```

`slope_type` = "sloped" or "low_slope". For sloped-HVHZ: defaults to `commission_pct.sloped` (10%) until Tim confirms — open item §10.3. Change is a config field update only.

### 4.5 Cost-category output

Every line item in the estimate result carries:

```json
{
  "key": "overhead",
  "label": "Overhead",
  "amount": 3220.00,
  "per_sq": 115.00,
  "category": "OH"
}
```

This enables the frontend to group by category and the floor checks to sum the correct denominators.

### 4.6 Config hash

The `pricing_config_hash` is computed as:

```python
import json, hashlib
from jcs import canonicalize   # python-jcs — RFC 8785 JSON Canonicalization

canon = canonicalize(config_dict)        # deterministic UTF-8 bytes
digest = hashlib.sha256(canon).hexdigest()
```

The hash is stored on the `pricing_configs` row at creation time and re-verified on activation. It is also stamped on every estimate at creation, not re-derived at read time.

---

## 5. APIs

All endpoints require `manage_estimates` role (admin, web_admin, sales).

### 5.1 Pricing config admin API

```
GET    /estimator/configs?branch=miami                    # list versions for branch
POST   /estimator/configs                                 # create new version (body: branch, label, config JSON)
GET    /estimator/configs/{id}                            # get version detail + hash
POST   /estimator/configs/{id}/activate                  # activate version (deactivates current)
GET    /estimator/configs/diff?from_id=1&to_id=2          # JSON diff for admin editor
GET    /estimator/configs/active?branch=miami             # get currently active config
```

Creating a version: server computes the RFC 8785 hash, stores it, returns the version with hash. The client must display the hash in the UI. Activating a version that was already active is a no-op (idempotent).

### 5.2 Estimate API

```
POST   /estimator/quote          # compute estimate (existing endpoint, signature changes)
GET    /estimator/rates          # rate tables from active config (existing endpoint, now config-driven)
```

Updated `POST /estimator/quote` request body:

```json
{
  "branch": "miami",
  "code_zone": "HVHZ",
  "county": "miami_dade",
  "slope_type": "sloped",
  "roof_type": "13_tile",
  "num_squares": 28.0,
  "roof_cuts": "low",
  "roof_height": "1_story",
  "tile_pointing": "no",
  "specialty_tile": null,
  "project_kind": "residential",
  "pitch_7_12": false,
  "demo": false,
  "secondary_water_barrier": false,
  "winterguard": false,
  "stucco_metal_lf": 0,
  "penetrations": 0,
  "extra_line_items": [],
  "ridge_vent_lf": 0,
  "layers_to_remove": 0,
  "deck_type": null,
  "include_insulation": false,
  "include_tapered": false,
  "measurement_id": null,
  "config_id": null        // null = use active config for branch; explicit = pin to a version
}
```

Response adds `pricing_config_id`, `pricing_config_hash`, `line_items_detail` (categorized), `margin_warnings`, `commission`.

### 5.3 Measurement API (stub for F2; full in F2b)

```
POST   /measurements                # create manual measurement
GET    /measurements/{id}           # get measurement
```

Manual entry creates a `Measurement` row with `provider="manual"`, `confidence=null`, and a `provenance_note`. The estimate endpoint accepts `measurement_id` to auto-populate `num_squares` and edge lengths.

---

## 6. Migrations

### Migration `0014_pricing_configs.sql`

```sql
-- Versioned per-tenant, per-branch pricing configuration.
-- Immutable rows: new row per edit; is_active pointer for activation.

CREATE TABLE IF NOT EXISTS pricing_configs (
    id           SERIAL PRIMARY KEY,
    tenant_id    INTEGER NOT NULL REFERENCES tenants(id),
    branch       VARCHAR NOT NULL,
    version      INTEGER NOT NULL,
    label        VARCHAR,
    config       JSONB NOT NULL,
    config_hash  CHAR(64) NOT NULL,
    is_active    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by   VARCHAR NOT NULL,
    CONSTRAINT uq_pricing_configs_tenant_branch_version
        UNIQUE (tenant_id, branch, version)
);

CREATE INDEX IF NOT EXISTS ix_pricing_configs_tenant_branch
    ON pricing_configs (tenant_id, branch);

-- Seed: Exhibit B fixture for Perkins (tenant 1) all three branches.
-- Full JSONB is in infra/fixtures/pricing_config_exhibit_b.json.
-- The migration runner executes the seed after table creation.
-- Hash computed by scripts/compute_config_hash.py at fixture build time.
INSERT INTO pricing_configs (tenant_id, branch, version, label, config, config_hash, is_active, created_by)
SELECT 1, b.branch, 1, 'Exhibit B 2026-Q3', :'config_json'::jsonb, :'config_hash', TRUE, 'system@perkins'
FROM (VALUES ('miami'), ('jupiter'), ('naples')) AS b(branch)
ON CONFLICT DO NOTHING;
```

### Migration `0015_estimates_hash.sql`

```sql
-- Adds pricing audit columns to estimates.
ALTER TABLE estimates
    ADD COLUMN IF NOT EXISTS pricing_config_id   INTEGER REFERENCES pricing_configs(id),
    ADD COLUMN IF NOT EXISTS pricing_config_hash CHAR(64),
    ADD COLUMN IF NOT EXISTS branch              VARCHAR,
    ADD COLUMN IF NOT EXISTS code_zone           VARCHAR,
    ADD COLUMN IF NOT EXISTS county              VARCHAR;

-- Measurement stub table (F2 shell; F2b adds provider-specific columns).
CREATE TABLE IF NOT EXISTS measurements (
    id                SERIAL PRIMARY KEY,
    tenant_id         INTEGER NOT NULL REFERENCES tenants(id),
    property_id       INTEGER,
    provider          VARCHAR NOT NULL DEFAULT 'manual',
    status            VARCHAR NOT NULL DEFAULT 'complete',
    total_sq          NUMERIC(10,2),
    hips_lf           NUMERIC(10,2),
    ridges_lf         NUMERIC(10,2),
    valleys_lf        NUMERIC(10,2),
    rakes_lf          NUMERIC(10,2),
    eaves_lf          NUMERIC(10,2),
    wall_flashings_lf NUMERIC(10,2),
    pitch_primary     NUMERIC(5,2),
    segments_json     JSONB,
    confidence        NUMERIC(4,3),
    raw_payload       JSONB,
    provenance_note   VARCHAR,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by        VARCHAR NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_measurements_tenant ON measurements (tenant_id);
```

---

## 7. Test plan (TEST-FIRST — all tests written red before any implementation)

Tests live in `tests/test_estimator.py` (unit) and `tests/test_estimator_integration.py` (API behavioral). **Fail-first sequence is mandatory: write the test, run it, confirm it fails for the right reason, implement minimally, make it green.**

### 7.1 Golden-file harness (highest-priority, written first)

Five permanent CI fixtures in `tests/fixtures/golden/`:

| File | Scenario | Roof type | County | Provider |
|---|---|---|---|---|
| `498sq_low_slope_hvhz.json` | 498 SQ TPO, HVHZ | TPO (low-slope) | Miami-Dade | manual |
| `15sq_low_slope_fbc.json` | 15 SQ TPO, FBC | TPO (low-slope) | Palm Beach | manual |
| `28sq_sloped_hvhz.json` | 28 SQ sloped, HVHZ | **13" tile** (GF-3) | Broward | manual |
| `28sq_sloped_fbc.json` | 28 SQ sloped, FBC | **Dimensional shingle** (GF-4) | Lee | manual |
| `41_5sq_standing_seam_fbc.json` | 41.5 SQ standing-seam metal, FBC | Standing-seam metal | St. Lucie | manual |

**GF-3 roof type: 13" tile, Broward county (HVHZ).** Rate: $780 base + $270 OH per §3 config.
**GF-4 roof type: dimensional shingle, Lee county (FBC).** Rate: $420 base + $105 OH per §3 config.
These assignments are canonical and mirrored in PRD-estimating §4.1.

Until Tim's real Exhibit C files land: fixtures are populated from Exhibit B derived inputs. CI passes on these; contract-grade sign-off is gated on Tim's actual files replacing them (open item §10.2).

Each fixture JSON:
```json
{
  "input": { /* QuoteInput fields */ },
  "expected_total": 12345.67,
  "expected_line_items": { /* key: amount */ },
  "tolerance_abs": 0.01,
  "tolerance_pct": 0.0001,
  "provider": "manual",
  "source": "exhibit_b_derived"
}
```

Test pattern (written first, red):
```python
@pytest.mark.parametrize("fixture_path", GOLDEN_FILES)
def test_golden_file(fixture_path, active_config):
    data = json.loads(fixture_path.read_text())
    result = estimate(active_config, QuoteInput(**data["input"]))
    assert abs(result["project_total"] - data["expected_total"]) <= max(
        data["tolerance_abs"], data["expected_total"] * data["tolerance_pct"]
    )
```

### 7.2 Config loading tests

- `test_config_load_valid`: seed fixture loads without error; hash matches recomputed hash.
- `test_config_schema_missing_field`: missing required field raises `ConfigValidationError`.
- `test_config_null_low_slope_raises`: accessing a null low-slope rate raises `ConfigError` with a clear message naming the missing field.
- `test_config_activate_deactivates_prior`: activating version 2 sets version 1 `is_active=False` atomically.
- `test_config_immutable_no_update`: updating an existing row raises `ImmutableConfigError`.

### 7.3 Hash canonicalization tests (RFC 8785 vectors)

- `test_rfc8785_key_ordering`: dict with unsorted keys produces same hash as sorted.
- `test_rfc8785_float_precision`: `1.0` and `1` and `1.00` all produce the same canonical form.
- `test_rfc8785_unicode`: unicode strings produce consistent bytes.
- `test_hash_determinism`: same config dict hashed twice produces identical output.
- `test_hash_sensitivity`: changing one rate value changes the hash.

### 7.4 Floor and commission denominator tests

- `test_profit_floor_13pct_pass`: construct input where profit is exactly 13% — `floor_ok=True`.
- `test_profit_floor_13pct_fail`: profit at 12.9% — `margin_warnings` contains `"profit_floor"`.
- `test_combined_floor_33pct`: OH + profit exactly 33% — `floor_ok_combined=True`.
- `test_insulation_excluded_from_profit_denominator`: insulation cost does not inflate the eligible base used for profit % calculation.
- `test_tapered_excluded_from_oh_and_profit_denominators`: tapered excluded from both.
- `test_commission_sloped_10pct`: sloped job → commission = profit × 0.10.
- `test_commission_low_slope_15pct`: low-slope job → commission = profit × 0.15.
- `test_commission_default_sloped_hvhz`: sloped HVHZ → uses sloped rate (10%) until config changes.

### 7.5 Boundary-band edge tests

- `test_sliding_scale_at_boundary_7sq`: num_squares=7 lands in the [7,14) tier → $140/sq (if lower-inclusive/upper-exclusive).
- `test_sliding_scale_just_below_boundary`: num_squares=6.999 → $160/sq (prior tier).
- `test_sliding_scale_boundary_flag_flip`: toggle `boundary_inclusive_lower=False` → boundary-sq moves to next tier.
- `test_sliding_scale_all_tiers`: parametrized over all boundary values.

### 7.6 Tile dumpster threshold tests

Formula under test: `count = ceil(sq / threshold)`. The `tile_dumpster_boundary_inclusive` flag is `true` in the seed fixture (Tim-confirm open item §10.6). Tests at boundary SQ values are mandatory:

- `test_dumpster_hvhz_15sq`: 15 SQ tile HVHZ, boundary_inclusive=true → ceil(15/15) = 1 dumpster ($300).
- `test_dumpster_hvhz_16sq`: 16 SQ tile HVHZ → ceil(16/15) = 2 dumpsters ($600).
- `test_dumpster_fbc_30sq`: 30 SQ tile FBC, boundary_inclusive=true → ceil(30/30) = 1 dumpster ($300).
- `test_dumpster_fbc_31sq`: 31 SQ tile FBC → ceil(31/30) = 2 dumpsters ($600).
- `test_dumpster_hvhz_30sq`: 30 SQ tile HVHZ → ceil(30/15) = 2 dumpsters ($600).
- `test_dumpster_not_applied_shingle`: shingle roof → no dumpster regardless of SQ.
- `test_dumpster_zero_sq_no_dumpster`: edge case SQ=0 → no dumpster.
- `test_dumpster_boundary_flag_flip`: toggle `tile_dumpster_boundary_inclusive=False` for a boundary-SQ case and assert count changes (verifies the flag is wired, not just documented).

### 7.7 County override tests

- `test_county_permit_fee_add`: county with `permit_fee_add=150` → permit line = 500 + 150.
- `test_county_materials_tax_tile`: `materials_tax_7pct_tile=True` → tile Materials lines × 1.07.
- `test_county_materials_tax_not_applied_shingle`: shingle roof → no 7% tax even if flag set.
- `test_county_extra_line_items`: county extra line item appears in estimate output.
- `test_county_override_stacks_on_zone`: county overrides add to zone base, not replace.

### 7.8 PM incentive matrix tests

- `test_pm_hvhz_residential_lt20`: HVHZ residential 15 SQ → $150.
- `test_pm_hvhz_commercial_20_50`: HVHZ commercial 30 SQ → $300.
- `test_pm_fbc_residential_lt10`: FBC residential 8 SQ → $50.
- `test_pm_fbc_residential_10_30`: FBC residential 20 SQ → $100.
- `test_pm_fbc_commercial_ge30`: FBC commercial 35 SQ → $250.

### 7.9 Migration tests

**Dual-path note:** these tests run against dev Postgres only, not the SQLite unit suite. The `.sql` migrations use `ADD COLUMN IF NOT EXISTS` and Postgres-specific DDL (JSONB, TIMESTAMPTZ, DEFERRABLE INITIALLY DEFERRED) that is not valid SQLite syntax. Schema for unit tests comes from `Base.metadata.create_all` on the SQLite test engine (see TRD-F0 §5 Group 1 note). Migration idempotency and column-type assertions are Postgres-side validations.

- `test_migration_0014_idempotent`: apply migration 0014 twice against dev Postgres; assert second run produces no errors.
- `test_migration_seed_hash_matches`: after seeding, `config_hash` in DB matches `compute_config_hash(seed_json)` (Postgres-side; verifies the seed INSERT and the hash script agree).
- `test_migration_0015_columns_present`: estimates table has the five new columns (`pricing_config_id`, `pricing_config_hash`, `branch`, `code_zone`, `county`) — verified via `information_schema.columns` on Postgres.
- SQLite unit tests for the ORM models (column presence, FK declarations, model instantiation) are in `tests/test_estimator.py` and run in the standard CI suite against the SQLite test engine.

### 7.10 Low-slope tests (with Tim's data; placeholder tests written now, skip-marked until data lands)

- `test_low_slope_tpo_hvhz`: 498 SQ TPO HVHZ matches golden file.
- `test_low_slope_insulation_no_profit`: insulation line has `category="Materials"`, not in profit denominator.
- `test_low_slope_tapered_no_oh_no_profit`: tapered line excluded from both floors.
- `test_low_slope_commission_15pct`: low-slope job → 15% commission.

### 7.11 Behavioral / integration validation

`scripts/validate_estimator.py` — hermetic, no I/O side effects:

1. Load seed fixture from file.
2. Instantiate engine with config (no DB needed).
3. Run all 5 golden inputs.
4. Assert totals within tolerance.
5. Print `PASS` or `FAIL <diff>`.

Run in CI after unit tests. This is the R1 behavioral validation for the adapter (`api/routes/estimator.py`) path.

### 7.12 API behavioral tests

`tests/test_estimator_api.py` (outside `core/` coverage gate but required by R1):

- `test_api_quote_returns_hash`: POST /estimator/quote → response contains `pricing_config_hash`.
- `test_api_unknown_specialty_tile_400`: unknown specialty_tile → 400, not 500.
- `test_api_config_activate_idempotent`: POST activate twice → 200 both times.
- `test_api_config_diff_returns_changes`: diff endpoint returns field-level changes between versions.
- `test_api_measurement_manual_provenance`: POST measurement with manual provider → `provenance_note` set.

---

## 8. Implementation steps

Steps are ordered to support fail-first TDD. Each step begins with writing the tests (red), then implementing (green).

1. **Write golden-file harness (red)**: Create `tests/fixtures/golden/` with 5 derived fixtures; write parametrized `test_golden_file`; confirm red (engine not yet config-driven).

2. **Write config schema and validator**: `core/pricing_config.py` — `PricingConfig` dataclass, `load_config(jsonb: dict) -> PricingConfig`, `compute_hash(config: dict) -> str`. Write all config loading tests (red). Implement. Green.

3. **Rewrite `core/estimator.py` as `estimate(config: PricingConfig, input: QuoteInput) -> EstimateResult`**: no module-level constants; all rates from `config`. Write boundary-band, dumpster, county, PM matrix, floor/commission tests (red). Implement. Green. Run `_selfcheck` equivalent (28 SQ @ $635/sq = $20,280 pre-incentive) as a unit test pinned to the seed config.

4. **Create seed fixture**: `infra/fixtures/pricing_config_exhibit_b.json` with all sloped values (low-slope nulls marked). `scripts/compute_config_hash.py` prints the hash; embed in fixture JSON under `"_hash"` for documentation (DB stores it authoritatively).

5. **Write and apply migration 0014**: `infra/migrations/0014_pricing_configs.sql`. Write migration idempotency test (red). Apply locally. Green.

6. **Write and apply migration 0015**: `infra/migrations/0015_estimates_hash.sql`. Write column-presence test (red). Apply. Green.

7. **Update `api/routes/estimator.py`**: load active config from DB, inject into `estimate()`, stamp hash on response. Write API behavioral tests (red). Implement. Green.

8. **Config admin API**: `api/routes/pricing_configs.py` — CRUD + activate + diff. Write tests. Implement. Green.

9. **Measurement stub**: `core/measurement.py` — `MeasurementProvider` Protocol, `ManualEntryProvider`. `api/routes/measurements.py` — POST/GET endpoints. Write tests. Implement. Green.

10. **Admin Estimating tab UI**: update `web/src/` Estimating section — versioned config editor (Monaco JSON editor), hash display, diff view, branch tabs. Non-covered by `core/` gate; behavioral: load a config, edit one rate, save, see new hash.

11. **Golden file green**: run all 5 golden tests. If any fail, fix the engine (not the fixture). Document any Exhibit-B ambiguity as an OPEN ITEM.

12. **R2 review**: architect + critic agents review for gaps, unwired code, floor denominator correctness, hash canon correctness, migration safety.

13. **Drift check**: `scripts/drift_check.sh` shows clean.

---

## 9. Exit gate

The wave is done when ALL of the following are true:

- [ ] `pytest --cov=core --cov-fail-under=100 tests/test_estimator.py tests/test_pricing_config.py` green. (`core/` coverage gate is 97% minimum per R1, but estimator and config modules target 100%.)
- [ ] All 5 golden-file tests pass at ±$0.01 / ±0.01% with Exhibit-B-derived inputs.
- [ ] `scripts/validate_estimator.py` exits 0.
- [ ] API behavioral tests pass (test_estimator_api.py, test_measurements_api.py).
- [ ] `ruff check core adapters api jobs` clean.
- [ ] Config hash test: same config produces same hash across 100 runs (determinism).
- [ ] Admin Estimating tab renders in the browser: create a new config version, activate it, see the hash update on the /estimator/quote response.
- [ ] Architect + critic R2 review: no unaddressed HIGH findings.
- [ ] `scripts/drift_check.sh` → no drift (R4).
- [ ] CONTRACT-GRADE exit (gated on Tim's real Exhibit C files): 5 golden files replaced with Tim's actuals; all 5 pass at ±$0.01.

---

## 10. Rollout / rollback

**Rollout:**

1. Apply migrations 0014 + 0015 via `scripts/apply_migrations_connector.py` (with Jon's explicit permission; requires fresh ADC).
2. Deploy API with config-injected engine. The engine reads the active config from DB on first request (no startup cache invalidation needed; each request fetches active config — adds one DB read, acceptable for this query volume).
3. Activate the seed Exhibit B config for all three branches via `POST /estimator/configs/{id}/activate`.
4. Smoke: `scripts/validate_estimator.py` against prod (read-only; no writes).

**Rollback (config):**

Activate the prior version via `POST /estimator/configs/{prior_id}/activate`. No code deploy required. The prior version's hash is preserved and will be stamped on new estimates immediately.

**Rollback (code):**

If the code deploy must be reverted: re-deploy the prior image (previous git SHA). The old engine code reads the old constants (prior to F2, no `pricing_configs` table is read). Migration columns are additive (ADD COLUMN IF NOT EXISTS) — the old code ignores them safely. Do not drop tables on rollback.

**Rollback (migration):**

Migrations 0014 and 0015 are additive. No rollback DDL is provided. If needed, drop tables/columns manually with Jon's explicit permission and a support ticket.

---

## 11. Risks and open items

### Open items (human-owned)

1. **Low-slope base costs, OH, insulation tiers, tapered cost** — Tim must supply Exhibit B §4 values. Engine raises `ConfigError` with a clear message for any null accessed. Tests marked `@pytest.mark.skip(reason="pending Tim data")` until filled. **Mid-F2 gate.**

2. **5 golden-file quotes** (Exhibit C actual values from Tim/Josh) — engine ships on Exhibit-B-derived fixtures. Contract-grade sign-off requires Tim's real numbers. **Mid-F2 gate; tracked as open item §10.2 in the plan.**

3. **Sloped-HVHZ commission rate: 10% or 15%?** — currently 10% (sloped default). Config-driven; answer from Tim = one field change, no code deploy. **F2 seed gate.**

4. **Sliding-scale boundary rule** — presumed lower-inclusive/upper-exclusive per Exhibit B wording. Config flag `boundary_inclusive_lower` / `boundary_exclusive_upper` — if Tim corrects the assumption, it is a config activation, not a code change.

5. **PM incentive matrix exact breakpoints** — matrix above is derived from the plan; verify each cell and breakpoint with Tim before activating.

### Risks

- **Hash library dependency**: The chosen implementation is `jcs` (`python-jcs` on PyPI, package name `jcs`). It must be pinned in `app/requirements.txt` as `jcs==<version>` before F2 ships. Add `pip-audit` to the CI gate. The alternative (hand-rolling RFC 8785 for the JSON subset we use) is available as a fallback if `pip-audit` flags a CVE or the package is abandoned — `core/canon.py` would implement the subset with test vectors. Decision: use `jcs` unless a blocker arises; do not defer the pin.
- **Low-slope nulls in seed fixture**: if a null is accidentally exercised in a non-low-slope path, the engine must guard cleanly. Defensive access via `config.get_or_raise(path, context)`.
- **Active-config DB read per request**: at high volume this is one extra read per quote. Mitigate in F5 with a short-lived (5-min) per-tenant branch cache if needed. Do not prematurely optimize in F2.
- **Admin config editor**: JSON editing is error-prone. Add schema validation server-side (config validator) and client-side (JSON schema in the Monaco editor) before user-facing release.

---

*TRD-F2 — prepared 2026-07-08. Implementation subagents: sonnet (per token policy). R2 review: architect + critic (opus).*
