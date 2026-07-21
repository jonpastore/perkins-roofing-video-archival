# Tile roof-cuts pricing linkage — hips / valleys / rakes / wall-flashings / eaves

**Source of truth:** Tim's live sloped calculator, tab **"Custom Tile Calc"**
(sheet `1qxfKRRvmQS_NYu3AE2KQgek421Wzftu3xVmGECFH-ig`), decoded from the actual
cell **FORMULAS** + the 77 cell **comments** (pulled 2026-07-21 via the
perkins-deploy SA w/ domain-wide delegation, `tim@perkinsroofing.net`,
`spreadsheets.readonly`). Re-pull: `scratchpad/tim_comments.py` +
`valueRenderOption=FORMULA`.

This closes the "#3" gap: the measurement fields `hips_lf`, `valleys_lf`,
`rakes_lf`, `wall_flashings_lf` (+ ridges, eaves/perimeter) were unmapped in
`core/estimator.py` / `web/src/pages/Quoting.tsx`. They are NOT flat $/LF line
items — they feed a **per-square material cost** via the formulas below.

## Step 1 — round each measured length UP (CEILING), then it's the qty driver

| Measurement (LF) | Rounding | Cell |
|---|---|---|
| Perimeter / Eaves | `CEILING(x, 10)` | C2 |
| **Hips + Ridges** (summed) | `CEILING(hips+ridges, 10)` | C3 |
| Valleys | `CEILING(x, 50)` | C5 |
| Rakes | `CEILING(x, 10)` | C6 |
| Wall flashings | `CEILING(x, 10)` | C7 |

Let `E=C2` (eaves), `HR=C3` (hips+ridges), `V=C5` (valleys), `R=C6` (rakes),
`W=C7` (wall), `SQ` = number of squares.

## Step 2 — per-square material components (each divided by SQ)

Exact formulas (cell → decoded rule):

| Material component | Formula (cell) | Decoded per-square rule |
|---|---|---|
| **Drip Metal & SA-V strips** (B16) | `((E+R)*1.1 + (E+R+W)*0.46) / SQ` | drip metal **$1.10/LF** over (eaves+rakes); SA-V strip **$0.46/LF** over (eaves+rakes+wall) |
| **Valley Metal + Valley SA-V** (B17) | `((V/50)*90 + (V/65)*151) / SQ` | valley metal **$90 per 50 LF** (=$1.80/LF); valley SA-V **$151 per 65 LF** (≈$2.323/LF) |
| **Hip/Ridge/Rake tiles + H&R metal** (B19) | `(HR*2.3 + (R+HR)*rakeTileUnit) / SQ` | H&R metal **$2.30/LF** over (hips+ridges); rake/H&R **tile** unit × (rakes+hips+ridges). `rakeTileUnit` = post-tax/waste rake tile cost, e.g. B35 `= (3.72*1.07)*1.08 = $4.30` (varies by tile brand row) |
| **Eave Closure Metal** (B20) | `(E*3.1) / SQ` | eave closure **$3.10/LF** over eaves |

Tax/waste convention seen throughout: unit cost `× 1.07 (7% tax) × 1.08 (8% waste)`.

Total base tile material `M` (B22) = `SUM(B11:B21)` — i.e. these roof-cut
components are ADDED into the per-square material cost `M`, alongside field
tiles/underlayment/etc. `+MTS = +$135/sq` (B22 note).

## Step 3 — linkage: material item price → quote config field

Add a **tile roof-cuts material** sub-model to the estimating config (mirrors how
`seed_gutters_config.py` is the single source for gutters). Config fields (unit
prices — the "material item price" the user wants linked), with the compute rule
baked into `core/estimator.py`:

| Config field | Value from sheet | Used as |
|---|---|---|
| `drip_metal_per_lf` | 1.10 | ×(eaves+rakes) |
| `sav_strip_per_lf` | 0.46 | ×(eaves+rakes+wall) |
| `valley_metal_per_unit` / `valley_metal_unit_lf` | 90 / 50 | ×ceil(valleys,50)/50 |
| `valley_sav_per_unit` / `valley_sav_unit_lf` | 151 / 65 | ×ceil(valleys,65-basis)/... |
| `hr_metal_per_lf` | 2.30 | ×(hips+ridges) |
| `rake_tile_per_lf` | ~4.30 (brand-dependent, post tax+waste) | ×(rakes+hips+ridges) |
| `eave_closure_per_lf` | 3.10 | ×eaves |
| `roof_cut_tax` / `roof_cut_waste` | 1.07 / 1.08 | multiply unit costs |

Estimator computes: round each LF up per Step 1 → multiply by the unit rates →
sum → **divide by `num_squares`** → add to the per-square `M` (material) cost.
Measurement fields already available: `hips_lf`, `ridges_lf`, `valleys_lf`,
`rakes_lf`, `wall_flashings_lf`, `perimeter/eaves_lf`, `total_sq`.

## Non-tile / other adders (from the main branch tabs, comments)

- **Wall flashing (non-tile / stucco):** "Add **$9 per LF** for stucco metal / L
  flashing" + **$75 per penetration** (Tim-HVHZ rows 15/27). Simpler flat model
  than the tile SA-V path above — use for shingle/metal systems.
- **Roof Cuts complexity** (per-square charge, branch-specific): Roof Cuts =
  $0 (Tim/HVHZ), $40 (FBC), $100 (Marco) — the Low/Med/High picker. Tile uses the
  explicit LF math above; the flat "Roof Cuts" charge is the shingle/metal proxy.

## To confirm with Tim (only genuinely open items)

1. **Rake-tile unit** varies by tile brand (Eagle/Crown/Boral/Santa Fe rows show
   $4.30 / $4.50 / $5.78 / $19.14…). Confirm the per-brand mapping to use.
2. Whether shingle/metal systems should use the flat **$9/LF wall + roof-cuts
   tier**, while only **tile** uses the full LF material math above (current read).

## Wiring plan (post rate-limit reset — weekly limit hit 2026-07-21, resets 6am ET)

1. `scripts/seed_roofcuts_config.py` (or extend estimating config) with the unit
   prices above. 2. `core/estimator.py`: add the tile roof-cuts material computation
   consuming the measurement LF fields. 3. `web/src/pages/Quoting.tsx`: feed
   `hips_lf/ridges_lf/valleys_lf/rakes_lf/wall_flashings_lf` from the loaded
   measurement into the estimate. 4. Behavioral test asserting one real tile job
   reproduces the sheet's per-square numbers (e.g. B22 `$811` base for the sample).
   Route the build to a sonnet executor.
