# Roof-cuts custom calculator — decoded spec (Tim's "Custom Tile Calc" tab)

Source: Tim's LIVE `***Sloped Roof Price Calculator` (sheet `1qxfKRRvmQS_NYu3AE2KQgek421Wzftu3xVmGECFH-ig`,
tab **Custom Tile Calc**), read read-only via the perkins-deploy-sa service account under
domain-wide delegation impersonating tim@perkinsroofing.net (2026-07-17). Formulas pulled with
`valueRenderOption=FORMULA` and verified numerically against the sheet's own example (below).

## What it does
Replaces the flat `sloped_base_cost_lm[zone]["13_tile"]` ($770 FBC / $780 HVHZ) with a
**geometry-derived base $/sq** computed from the RoofR cut linear-footages. Cut-heavy roofs cost
more per square (more metal/tile at hips/valleys/eaves); a simple roof costs slightly less. Range
observed ±20-30% of base (Zoom 30:52). "One tile calculator reused for shingle/metal via the same
% difference" (Zoom 05:33) → apply the custom/standard **ratio** to shingle/metal bases.

## Inputs (RoofR LFs — already on the `Measurement` model)
eaves_lf, hips_lf, ridges_lf, valleys_lf, rakes_lf, wall_flashings_lf, plus num_squares.

## Step 1 — round UP to material-piece lengths (Google Sheets CEILING)
| rounded | formula | piece length |
|---|---|---|
| eaves_r        | CEILING(eaves, 10)          | 10 ft |
| hipridge_r     | CEILING(hips + ridges, 10)  | 10 ft (hips & ridges share H&R material) |
| valleys_r      | CEILING(valleys, 50)        | 50 ft (valley metal comes in rolls) |
| rakes_r        | CEILING(rakes, 10)          | 10 ft |
| wall_r         | CEILING(wall_flashings, 10) | 10 ft |

## Step 2 — custom tile base $/sq = (fixed labor + 5 geometry lines) ÷ squares
Fixed per-sq labor/delivery lines (FBC values, from the Custom Tile Calc B-column):
tear_off 75 + dry_in_tuplus 85 + tile_install 160 + hauling 65 + sa_v_strips_misc 89 + tile_delivery 45
= **519 fixed $/sq**.

Five geometry-driven lines (each already divided by squares in the sheet):

```
drip_sa_v      = ((eaves_r + rakes_r) * 1.10  +  (eaves_r + rakes_r + wall_r) * 0.46) / sq
valley_metal   = ((valleys_r / 50) * 90        +  (valleys_r / 65) * 151)              / sq
field_tiles    = tile_field_cost + 5                        # NOT divided; already $/sq
hipridge_tiles = (hipridge_r * 2.30            +  (rakes_r + hipridge_r) * tile_rake_cost) / sq
eave_closure   = (eaves_r * 3.10) / sq
```

`custom_base = 519 + drip_sa_v + valley_metal + field_tiles + hipridge_tiles + eave_closure`

### Tile-brand costs (post 7% tax × 8% waste) — feed field_tiles + tile_rake_cost
Standard PROTECTOR tile = **Eagle** (the "$215 M standard tile" in the flat base):
- Eagle field = (127.72 × 1.07) × 1.08 = **$147.59** → field_tiles line = 152.59
- Eagle rake  = (4.17  × 1.07) × 1.08 = **$4.82**
Other brands on the sheet (for later tile-selection linkage): Crown field 143.19 / rake 4.30;
West Lake 145.71 / 4.50; Verea Spanish 297.04; Verea Caribbean; Tejas Borja flat +$340-465/sq.
The raw pre-tax/waste numbers (127.72, 4.17, …) are the material prices Tim maintains in cell
comments (item #9 linkage) — captured here so the linkage isn't blocked on the comments.

## Verified example (the sheet's own live inputs, Crown tile)
sq 29; eaves 299→300, hips 142 + ridges 103 = 245→250, valleys 102→150, rakes 74→80, wall 47→50;
tile_field 143.19 (Crown), tile_rake 4.30 (Crown):
drip 21.23, valley 21.33, field 148.19, hipridge 68.76, eave 32.07, +519 fixed
→ **custom_base = 810.58 → $811** (sheet cell B22 = $811). Standard FBC base = $770. Cuts +$41/sq.

## Zone note
Coefficients (1.10, 0.46, 90/50, 151/65, 2.30, 3.10) are metal/material $/LF — zone-independent.
The 519 fixed block + tile costs are FBC. HVHZ adds the "$100/sq HVHZ upgrade" and its own base
detail; seed HVHZ separately when quoting HVHZ tile (demo is Jupiter/FBC, so FBC first).

## Encode as config `cuts_calc` (zone-scoped where it varies)
```
"cuts_calc": {
  "rounding": {"eaves":10,"hips_ridges":10,"valleys":50,"rakes":10,"wall_flashings":10},
  "fixed_per_sq": {"FBC": 519, "HVHZ": null},          # sum of the 6 fixed lines
  "coeff": {"drip_a":1.10,"drip_b":0.46,"valley_a_div":50,"valley_a_rate":90,
            "valley_b_div":65,"valley_b_rate":151,"hipridge_tile_rate":2.30,
            "eave_closure_rate":3.10,"field_tiles_addon":5},
  "standard_tile": {"field":147.59,"rake":4.82}         # Eagle
}
```
Estimator: when the 6 cut LFs are present and roof_type is tile → base line uses custom_base;
for shingle/metal, multiply their flat base by (custom_base / standard_tile_base).

## R2 review notes (architect + critic, 2026-07-17) — resolved / accepted
- **Double-count with categorical roof_cuts (HIGH)** — the geometry base and the low/med/high
  `roof_cuts` line both price cut complexity. Per Tim's model BOTH exist, so we keep both
  (default low=$0) and now emit a `roof_cuts_double_count` **warning** when a non-`low` categorical
  stacks on a geometry-priced base — surfaced, not silently summed. Confirm stacking intent w/ Tim.
- **HVHZ silent flat fallback (MED)** — cut LFs on an uncalibrated zone now emit
  `cut_calc_uncalibrated_zone` instead of silently using the flat base. HVHZ still needs its own
  fixed block + (ideally) zone-scoped `standard_tile` before it's calibrated (demo is FBC/Jupiter).
- **Partial explicit LF dropped the measurement (MED)** — the API now MERGES per-field: measurement
  provides the base six, an explicit non-zero request field overrides just that one.
- **Accepted / not changed (documented):** barrel_tile uses the 13-tile ratio (no barrel-specific
  coefficients exist — treat barrel cut quotes as estimates until validated against a Tim barrel
  quote, or add a barrel `standard_tile` block); standalone package tiers (metal CARIBBEAN, flat
  PROLONG) price off catalog and don't carry the cut premium (pre-existing package design);
  `num_squares` tiny-but-positive can produce an absurd $/sq (pre-existing engine-wide, GIGO);
  county `materials_tax_7pct_tile` × a base whose tile cost is already post-tax would double-tax —
  inactive today (all counties False), same latent issue as the flat base.
