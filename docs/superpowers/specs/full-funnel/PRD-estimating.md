# PRD — Estimating (Wave F2 + F2b)

**Version:** 1.0 · **Date:** 2026-07-08 · **Status:** DRAFT (R2 fixes applied — pending Jon approval)
**Wave:** F2 (engine + config) → F2b (measurement service)
**Commercial deadline:** ~3–4 weeks (F0 → F1∥F2 → F3 critical path)

---

## 1. Purpose

Replace the stub `core/estimator.py` with a contract-grade, config-driven pricing engine that
reproduces Exhibit B of the Ez-Bids legal package exactly. The engine must handle both sloped and
low-slope roofs, HVHZ and FBC code zones, all three Perkins branches, and per-property overrides —
and pass five acceptance-test golden files to the penny before Tim's contract-grade sign-off.

**What this is not:** payment processing, QuickBooks/accounting integration, CRM, or measurement
hardware. Measurement source is Google Solar API (primary) + manual entry (explicit fallback). No
LiDAR, drones, or raw Google Earth scraping.

---

## 2. Personas and user stories

### 2.1 Estimator (Marcos, Chris, branch lead)

- As an estimator, I can open the Estimating section, select a saved measurement or enter squares
  manually, choose roof type and options, and receive a fully itemized quote in under 2 seconds.
- As an estimator, I can see which measurement source fed the quote (Solar API vs. manual) so I
  know whether to annotate the proposal with a caveat.
- As an estimator, I can override the code zone on any quote (e.g., a property in a border county)
  without changing the branch default.
- As an estimator, I can re-run a quote against a different branch pricing config and see the
  delta immediately.

### 2.2 Branch admin / Tim

- As a branch admin, I can open Admin → Estimating and edit the pricing config for my branch
  through a structured form. Changes are versioned and the previous config is preserved.
- As Tim, I can see the SHA-256 hash of the active pricing config on every quote so I can audit
  that a quote was generated under a specific rate revision.
- As Tim, I can assign a commission rate per job type (sloped vs. low-slope, HVHZ vs. FBC) and
  see the commission estimate on every quote.

### 2.3 Platform admin (DeGenito)

- As platform admin, I can provision a new tenant with a copy of the Perkins seed pricing config
  as a starting point, then let their branch admins diverge from it.

---

## 3. Functional requirements

Requirements are numbered for traceability. **Must** = F2 exit gate. **Should** = F2 target but
deferrable to pre-F3 if the commercial clock is tight. **Adv** = advisory / open-item dependency.

### 3.1 Config-driven pricing (replaces hardcoded constants)

**F2-01** Rate tables (base costs, overhead, profit scale, fixed costs, line-item prices) must be
stored as versioned `pricing_configs` records (JSONB, per tenant per branch) in PostgreSQL, not as
module-level constants.

**F2-02** The engine function signature becomes `estimate(config: PricingConfig, input: QuoteInput)
→ QuoteResult` — pure, no DB access, 100%-coverable by unit tests.

**F2-03** Exhibit B tables for all five Perkins roof types (13" tile, barrel tile, 3-tab shingle,
dimensional shingle, standing-seam metal) must be the committed seed fixture for each branch
(Miami/Jupiter/Naples). The fixture is the authoritative Exhibit B data; it ships in the migration.

**F2-04** The Admin → Estimating config editor must allow a branch admin to edit any numeric field,
preview the change, and save a new version. The UI must display the active version number and hash.
The engine always reads the current version; prior versions are retained for audit.

**F2-05** Every quote record must store `pricing_config_id` (FK to the active config row) and
`pricing_config_hash` (RFC 8785 JSON-canonical SHA-256 of the config JSONB at time of quote
creation). This enables bit-exact quote reproduction for any historical quote.

### 3.2 Cost-category tags on line items

**F2-06** Every line item produced by the engine must carry a `cost_category` tag from the
enumeration: `Labor | Materials | Equipment | Sub | Misc | OH | Profit`. Tags are defined in the
pricing config and inherited by all quotes generated from that config.

**F2-07** The 13% profit floor must be computed as `profit_dollars / eligible_base ≥ 0.13`, where
`profit_dollars` is the sum of all `Profit`-tagged line item amounts and `eligible_base = project_total
− profit_dollars − floor_exempt_line_items` (insulation and tapered lines, per Exhibit B). The
existing `margin_ok` field computed from an incorrect denominator (`/ project_total`) must be replaced.
The canonical denominator definition lives in TRD-F2 §4.3.

**F2-08** The 33% profit+OH floor must be computed as `(OH_dollars + profit_dollars) / eligible_base
≥ 0.33`, where `OH_dollars` is the sum of all `OH`-tagged amounts (excluding OH on floor-exempt
lines where applicable) and `eligible_base` is the same denominator as F2-07. Both floors must be
checked and reported separately in the quote output.

**F2-09** Exhibit B carve-outs apply via tags: insulation line items carry `Materials` with
`floor_excluded=[Profit]` (no Profit added per Exhibit B; OH still applies to insulation).
Tapered insulation carries `Materials` with `floor_excluded=[OH, Profit]` (no OH or Profit per
Exhibit B). The config fixture must encode these exactly. See TRD-F2 §3 `floor_excluded_categories`
for the canonical encoding.

**F2-10** Commission is computed as `commission_rate × profit_dollars` (not of project_total).
Commission rates: 10% sloped / 15% low-slope. Sloped-HVHZ rate is **open item #3** (confirm with
Tim); the config stores the rate per `(slope_category, code_zone)` pair so either value is correct
by config, not by code.

### 3.3 Sloped roof engine — delta fixes vs. current stub

**F2-11** PM incentive must use the zone×job-size matrix from Exhibit B, not a flat per-kind value.
Both zones share the same SQ band edges. The engine raises `ConfigError` (never a silent $0) on any
unmatched (zone, project_kind, SQ) cell. **Full matrix — Tim-verify required before activation:**

| Job kind | SQ range | HVHZ | FBC |
|---|---|---|---|
| Residential | < 20 SQ | $150 | $50 |
| Commercial | 20–50 SQ | $300 | $100 |
| Commercial | > 50 SQ | $300* | $250 |

*HVHZ commercial > 50 SQ: open item — current value $300 (same as 20–50); Tim must confirm.
The canonical config encoding and ConfigError behavior are specified in TRD-F2 §3 and §4.1.

**F2-12** Tile dumpster must be auto-applied by threshold count, not opt-in:
- Formula: `count = ceil(sq / threshold)` where threshold = 15 SQ (HVHZ) or 30 SQ (FBC).
- HVHZ: one dumpster ($300) per `ceil(sq / 15)` for tile roofs.
- FBC: one dumpster ($300) per `ceil(sq / 30)` for tile roofs.
- A `tile_dumpster_boundary_inclusive` config flag controls whether the threshold boundary SQ
  itself triggers the next count (default: true — lower-inclusive). **Adv-1**: exact boundary
  behavior pending Tim confirmation; the flag makes it a config change, not a code change.
- Tests at boundary SQ values (15, 16, 30, 31) are mandatory CI fixtures. See TRD-F2 §7.6.

**F2-13** The sliding-scale profit boundary is lower-inclusive / upper-exclusive (e.g., 20 SQ uses
the 15–20 band, not the 20–29 band) — **Adv-1**: pending Tim's explicit confirmation. The engine
must use whichever rule Tim confirms; a `# VERIFY` comment in code marks the boundary until resolved.

**F2-14** The 7% materials tax flag must be configurable per tile product in the pricing config
(not globally). When set, the engine adds 7% of that product's base material cost to the
`Materials`-tagged subtotal. Adv-2: Tim's confirmation of which products carry it gates this.

**F2-15** All items currently marked `# VERIFY` in `core/estimator.py` must be resolved (via Tim's
golden files and confirmations) and the verification markers removed before the contract-grade
sign-off gate. The engine may ship for F2 internal testing with open `# VERIFY` items as long as
the Exhibit-B unit fixtures pass; golden-file acceptance waits for Tim's inputs.

### 3.4 Low-slope category (Exhibit B §4 — net-new)

**F2-16** The engine must support a `slope_category` input: `sloped | low_slope`. Low-slope
activates a separate rate table section in the config.

**F2-17** Low-slope product types supported: `TPO | coatings | silicone | BUR`. Each has its own
base cost per SQ in the config, tagged `Materials`.

**F2-18** Insulation tiers: uninsulated / R-19 blown-in / tapered polyiso. Each tier has a
per-SQ cost. Blown-in insulation is tagged `Materials` with `floor_excluded=[Profit]` (no profit
per Exhibit B; OH still applies). Tapered is tagged `Materials` with `floor_excluded=[OH, Profit]`
(no OH or profit per Exhibit B carve-out, F2-09). Both match TRD-F2 §3 `floor_excluded_categories`.

**F2-19** Deck types: wood / concrete / steel. Each has a per-SQ adder in the config.

**F2-20** Per-layer tear-off: configurable cost per SQ per layer being removed.

**F2-21** Height rules for low-slope (crane/trash-chute): 3–5 stories adds a flat project-level
cost (same pattern as sloped); 6+ stories requires manual pricing (quote blocked with an explicit
"manual quote required" flag in the output, not a silent zero).

**F2-22** Low-slope OH is configurable per product type in the pricing config (distinct from sloped
OH values, which already differ by roof type).

**F2-23** The `estimate()` function must produce the same output structure for both sloped and
low-slope inputs, with `slope_category` recorded on the result. The API and UI must pass it through
without special-casing by slope type.

### 3.5 Code zones, branches, counties

**F2-24** Code zone (`HVHZ | FBC`) is stored per-property and defaults to the branch default. It
is overridable per-quote at quote-creation time without changing the property record.

**F2-25** HVHZ = Miami-Dade + Broward counties. FBC = Palm Beach + Lee + St. Lucie counties.
The county → zone mapping is encoded in the pricing config (or a seed reference table), not hardcoded
in the engine.

**F2-26** The pricing config supports per-county overrides on top of the zone tables: permit fees,
the materials-tax flag, and county-specific line items. A property in Palm Beach County can carry
a Palm Beach permit fee that differs from the FBC default without changing its zone assignment.

**F2-27** Branches (Miami / Jupiter / Naples) each have their own `pricing_config` row. The branch
determines which config is loaded as the default; the per-quote override (F2-24) can substitute a
different zone's rate table without switching branches.

**F2-28** Mixed-tier per slope/line: a single property quote may have a sloped section (HVHZ) and
a low-slope section (FBC addendum) if the property straddles a code zone. The engine must accept
a list of `QuoteInput` segments and sum them into one `QuoteResult` with per-segment breakdowns.

### 3.6 Measurement service (Wave F2b)

**F2b-01** Primary measurement source: **Google Maps Platform Solar API** (`buildingInsights`
endpoint). The adapter must return per-segment pitch, azimuth, and area; aggregate to total SQ,
hips, ridges, valleys, rakes, eaves, and wall flashings matching the `Measurement` model.

**F2b-02** Manual entry is a **first-class, explicitly labeled fallback**, not a silent substitute.
The UI must display the measurement source on every quote. If the Solar API returns no data for an
address, the UI must prompt the user to enter measurements manually and label the quote
"manual measurement" before submission — never silently fall back.

**F2b-03** The `MeasurementProvider` interface must be defined so adapters are swappable
(Solar API, future Nearmap/Vexcel) without changing the engine or API contract.

**F2b-04** The Solar API adapter must be mocked in CI (no live API calls in tests). Integration
tests against a real address run in a separate test suite gated by `SOLAR_API_KEY` presence.

**F2b-05** The Solar API enablement and billing on GCP is a human-owned prerequisite (jarvis #331,
Jon). The adapter ships with mock; live activation follows Solar API key availability.

**F2b-06** No LiDAR, drone imagery, or raw Google Earth scraping. The SquareQuote/eaglepoint
ml-service (DeGenitoAI/eaglepoint) must not be merged into this repo. If that service's
measurement outputs are consumed in the future, they must arrive via the `MeasurementProvider`
interface, not by importing its code.

---

## 4. Acceptance criteria (contract-grade gate)

### 4.1 Five golden files — the definitive acceptance test

The engine must reproduce all five of Tim's reference quotes **to ±$0.01 (or ±0.01%)**, both via
manual entry and via measurement-fed input. These are permanent fixtures in CI — they must never
regress.

| # | Description | Roof type | Zone | County | Size |
|---|---|---|---|---|---|
| GF-1 | Low-slope (TPO) | TPO | HVHZ | Miami-Dade | ~498 SQ |
| GF-2 | Low-slope (TPO) | TPO | FBC | Palm Beach | ~15 SQ |
| GF-3 | Sloped — **13" tile** | 13" tile | HVHZ | **Broward** | ~28 SQ |
| GF-4 | Sloped — **dimensional shingle** | Dimensional shingle | FBC | **Lee** | ~28 SQ |
| GF-5 | Standing-seam metal, sloped | Standing-seam metal | FBC | St. Lucie | ~41.5 SQ |

**GF-3 canonical assignment:** 13" tile, Broward county (HVHZ). Base $780/sq, OH $270/sq per seed config.
**GF-4 canonical assignment:** dimensional shingle, Lee county (FBC). Base $420/sq, OH $105/sq per seed config.
These assignments are sourced from TRD-F2 §7.1 and are canonical — do not alter without updating TRD-F2 §7.1 simultaneously.

**Golden file sign-off is gated on receiving Tim's actual filled-in sheets** (section A of the Tim
requirements doc). The engine can ship for F2 internal demo using Exhibit-B unit fixtures
(`_selfcheck` pattern); contract-grade sign-off waits for Tim's inputs + the three pricing
confirmations.

### 4.2 Three pricing confirmations (unblocks golden files)

| # | Question | Current assumption | Needed from Tim |
|---|---|---|---|
| PC-1 | Commission on sloped HVHZ jobs | Unknown (10% or 15%) | Explicit answer |
| PC-2 | Sliding-scale band at exactly 20 SQ | Lower-inclusive assumed | Explicit answer |
| PC-3 | Which tile products carry 7% materials tax | Unknown | Product list |

### 4.3 Exhibit-B unit fixtures (F2 internal gate — no Tim dependency)

The existing `_selfcheck` (28 SQ, HVHZ, KEY-block override → $20,280 pre-incentive) passes. The
full Exhibit B table must be encoded as pytest fixtures covering at least:
- Profit sliding scale: one case per tier (1, 3, 5, 10, 17, 25, 30+ SQ).
- 13% profit floor and 33% profit+OH floor: one passing case, one that would fail pre-floor.
- PM incentive matrix: all six cells.
- Tile dumpster threshold: boundary cases for both HVHZ (15 SQ) and FBC (30 SQ).
- All five sloped roof types × both regions.
- Low-slope: TPO + silicone × both regions, each insulation tier.

### 4.4 Other acceptance criteria

**AC-01** Config edit in Admin → Estimating → save → new quote uses new config; prior quote still
reproduces under its stored `pricing_config_hash`. Verified by an integration test.

**AC-02** Cross-region: a quote for an HVHZ property using HVHZ rates vs. the same property forced
to FBC rates produces different totals (guards against zone override being ignored).

**AC-03** `margin_ok` flag (F2-07/F2-08) correctly reports False when profit or profit+OH drops
below floor, and True otherwise, on at least three fixture cases.

**AC-04** Manual-entry quote and Solar-API-fed quote for the same inputs produce identical
`project_total` (measurement source affects SQ count input, not the engine math).

**AC-05** Josh's Roofr reference quotes (additional validation, not golden files) validate on top
of GF-1 through GF-5 when provided. Failures are advisory until Tim signs off on the comparison.

---

## 5. Non-goals (do not build in this wave)

- Payment processing or deposit collection (no Stripe, no ACH, no invoicing).
- QuickBooks / accounting integration (Tim's backend handles this; this platform does not touch it).
- LiDAR, drone measurement, or raw Google Earth image scraping.
- SquareQuote/eaglepoint source import into this repo.
- Native iOS app (deferred from Ez-Bids proposal; GCP web-first).
- Engagement-sim bots or automatic social publishing from the estimating section.
- Nearmap/Vexcel oblique imagery (future paid upgrade path; not v1).
- A full CRM (leads is a status field, not a CRM module; that is Quoting scope).

---

## 6. Differentiators

### vs. current stub (`core/estimator.py`)

The stub hardcodes rate tables as module constants, uses a flat PM incentive, has an opt-in
dumpster, computes margin against the wrong denominator, and has no low-slope category. All five
gaps are eliminated in F2.

### vs. SquareQuote-as-is (DeGenitoAI/eaglepoint in its current state)

SquareQuote's production pipeline today outputs footprint area only (LiDAR silently disabled,
U-Net running random weights, edge math wrong). It cannot feed the golden files. The Solar API
adapter produces pitch, azimuth, and area per segment from Google's own imagery and DSM — the
same data source without ToS risk. This gives Perkins measurement quality that SquareQuote does
not currently deliver.

### vs. manual spreadsheets (Tim's current process)

Every quote is reproducible: the `pricing_config_hash` on the quote record links it to an exact,
immutable copy of the rate tables active at time of creation. Tim can audit any historical quote
without hunting for the right spreadsheet version.

### vs. Knowify

Knowify has no configurable pricing engine and no per-property code-zone routing. Estimators
cannot branch by HVHZ vs. FBC in Knowify; they switch sheets manually.

---

## 7. Multi-tenant considerations

**MT-01** `pricing_configs` is a tenant-scoped table (`tenant_id` FK, RLS policy). Perkins (tenant
1) cannot see or modify another tenant's configs; another tenant cannot see Perkins' configs.

**MT-02** The engine receives a `PricingConfig` object fetched under the active tenant context.
The engine itself has no tenant awareness — it is a pure function of config + input.

**MT-03** Platform admin (DeGenito) can copy Perkins' seed config to a new tenant's branch as a
starting point during tenant provisioning (Admin → Tenants tab, platform_admin role only).

**MT-04** Per-tenant usage metering: estimate computation time and Solar API call counts are
emitted as structured log fields on the existing metering path (feeds future billing story at
near-zero marginal cost).

---

## 8. Data model sketch (non-binding — TRD owns the canonical schema)

```
pricing_configs
  id, tenant_id, branch (miami|jupiter|naples), version_num, created_at, created_by
  config_json JSONB          -- RFC 8785 canonical; SHA-256 = pricing_config_hash
  is_active BOOL             -- per (tenant, branch), only one active at a time

quotes  (owned by Quoting wave — Estimating writes the snapshot)
  pricing_config_id FK       -- which config row
  pricing_config_hash TEXT   -- SHA-256 at creation; denormalized for immutable audit

measurements
  id, tenant_id, property_id
  provider (solar_api|manual), requested_at, completed_at
  total_sq, hips_lf, ridges_lf, valleys_lf, rakes_lf, eaves_lf, wall_flashings_lf
  raw_response JSONB         -- Solar API full response for audit/reprocessing

line_item_cost_categories (enum, seeded, not tenant-scoped)
  Labor | Materials | Equipment | Sub | Misc | OH | Profit
```

---

## 9. Dependencies and open items

| # | Item | Owner | Blocks |
|---|---|---|---|
| #318 | Base-cost composition (KEY block vs. per-type lookup) canonical rule | Tim / golden files | GF-3, GF-4 |
| #324 | Golden files: filled-in sheets for all 5 scenarios | Tim | AC gate |
| PC-1 | Sloped-HVHZ commission rate (10% vs 15%) | Tim | F2-10, commission output |
| PC-2 | Sliding-scale boundary at 20 SQ (lower-inclusive?) | Tim | F2-13, GF-3/4 |
| PC-3 | 7% materials-tax product list | Tim | F2-14 |
| #331 | Google Solar API enablement + billing on GCP | Jon | F2b-01 live |
| Adv-1 | Tile dumpster boundary rule (HVHZ >15 / FBC 30 — inclusive/exclusive) | Tim | F2-12 |
| —  | SquareQuote API key (not needed for F2; mock sufficient) | DeGenito internal | F2b adapter go-live only |

**None of these block F2 internal engine work.** The engine can be built and Exhibit-B unit
fixtures can pass before any Tim input arrives. Golden-file CI fixtures and contract-grade sign-off
are the only gates that require Tim's responses.

---

## 10. Out-of-scope clarifications (do not open debates on these)

These are locked decisions from the full-funnel plan (§0 and §3 of docs/continuations/CONTINUATION-2026-07-08.md):

- Stack: GCP everywhere. Ez-Bids is rebuilt on this stack, not Cloudflare/D1/Next.
- Tenancy: single-DB RLS with `tenant_id`, not schema-per-tenant.
- Auth: Firebase/GCIP; Perkins stays on the project-level pool as tenant 1.
- Measurement: Solar API + manual. No LiDAR/drones. No SquareQuote source merge.
- Proposals: Quoting wave (F3). Estimating produces a `QuoteResult`; Quoting wraps it in a proposal.
- Knowify: one-way handoff from Quoting, not from Estimating.
