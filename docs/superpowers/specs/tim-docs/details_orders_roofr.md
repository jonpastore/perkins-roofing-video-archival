# Details Pages, Roofr Reports, and Material Orders — Reverse Engineering Analysis

_Source documents: 5 Details Pages, 7 Roofr PDFs, 6 material order .txt dumps_

---

## 1. Details Page

### What It Is

The Details Page is a **permit submission spec sheet** — a single-page pre-job document that captures everything the Florida building department needs to issue a roofing permit, plus the key parameters that drive crew deployment and material ordering. It is NOT an invoice or proposal. It is completed by the estimator (Veneice, per the header "ANY QUESTIONS CALL VENEICE 305.305.2213") and travels with the job from permit filing through crew briefing.

### Every Field

| Field | Values / Notes |
|---|---|
| Header | "ANY QUESTIONS CALL VENEICE 305.305.2213" — static crew-contact line |
| Section label | "PERMIT DETAILS:" |
| OWNERS NAME | Homeowner full name |
| PHONE # | Homeowner phone |
| EMAIL ADDRESS | Homeowner email |
| JOB ADDRESS (highlighted yellow) | Street address + City/State/Zip (2 lines) |
| TYPE OF ROOF(S) — circle one or more | SHINGLE / FLAT / METAL / TILE |
| DECK TYPE — circle one | WOOD / STEEL / CONCRETE; note field "4, 5 & 7" appears in multiple docs — likely refers to the permit code sections that apply |
| ROOF PITCH/SLOPE | "SLOPED IS: __:12" and "FLAT IS: __:12" (separate fields because a property can have both) |
| SQUARE FOOTAGE | "SLOPED IS: __ SQFT" and "FLAT IS: __ SQFT" (raw area before waste; matches Roofr "pitched area" and "flat area") |
| SLOPED ROOF MEAN HEIGHT | feet — required for permit |
| FLAT ROOF MEAN HEIGHT | feet — required for permit |
| HOW MANY FLOORS — circle one | ONE / TWO / OTHER |
| SYSTEM YOU WILL BE USING | Free-text: lists base sheet, ply sheet, membrane in order — e.g., "1 Ply Elastobase, 1 Ply SA V, 1 Ply SA P" for flat; "1 Ply RoofNado AnchorDeck PSU HT (50 mil), Metal Alliance .032 ALUM 1.5" panels mech seam" for metal |
| SLOPED (system) | System spec for sloped portion |
| FLAT (system) | System spec for flat portion |
| ARE YOU USING INSULATION | YES / NO circle; TYPE field |
| ARE THERE PARAPET WALLS | YES / NO circle; HEIGHT OF PARAPET WALL: __ FEET/INCHES |
| FLASH WALLS WITH — circle | "L FLASHING AND STUCCO STOP" vs "GO UP WALL WITH CANT AND T-BAR" |
| JOB VALUE$$$$ | Contract dollar amount (e.g., $42,529.50; $49,173.88 w/o gutters; $127,263.35) |
| ROOF DIAGRAM BELOW WITH DIMENSIONS | Hand-drawn or "See RoofR" (all sampled jobs reference Roofr here) |
| PARAPET FLASHING DETAILS | Diagram area — blank or noted |

### Who Consumes It and How It Relates to Other Documents

- **Permit office**: The completed form is submitted with the building permit application. Pitch, deck type, system spec, mean height, and job address are the permit-critical fields.
- **Crew foreman**: Tells the crew what system goes on sloped vs. flat sections, whether there are parapets, and how to flash walls — decisions that must be made before the first roll is opened.
- **Material orderer (Veneice)**: Job value and system spec confirm which of the two material order forms to fill (sloped metal/tile/shingle vs. flat BUR/TPO). The square footages feed directly into the order quantity cells.
- **Invoice**: Job value on the Details Page should match the invoice total. Cross-referencing the sampled invoices (#601 Fred Thompson, #608 Melissa Butterworth, #611 Jim Malooley, #639 Glenn Allen) against the Details Page values confirms this is the same dollar amount — the Details Page is essentially the permit-filing copy of the signed contract value.
- **Roofr report**: The Details Page references "See RoofR" for the roof diagram in every sampled job. Roofr provides the dimensioned plan; the Details Page is the human-readable permit summary of what Roofr measured.

### Blank / Template Version

"PERKINS ROOFING DETAILS PAGE.pdf _ DocHub.pdf" is the blank master. The DocHub watermark confirms it is managed as an online fillable PDF that Veneice or an admin completes per job.

---

## 2. Roofr Measurement Report

### Report Structure (7 pages)

| Page | Content |
|---|---|
| 1 | Cover: contractor logo, address, total sqft, facet count, predominant pitch, aerial photo with imagery source/date |
| 2 | Roof diagram (plan-view outline of facets, color-coded by edge type) |
| 3 | Length measurement report: labeled edge lengths on the diagram |
| 4 | Area measurement report: per-facet areas labeled on the diagram |
| 5 | Pitch & direction report: pitch value and water-flow arrow per facet |
| 6–N | Structure summary (one per detached structure) + combined Report Summary |
| Last | Material calculations (shingle-based; generic brands) |

### All Measurement Fields

**Area fields**
- Total roof area (sqft) — all facets combined
- Total pitched area (sqft)
- Total flat area (sqft)
- Predominant pitch — e.g., 6/12, 3/12, 1/12
- Predominant pitch area (sqft)
- Unspecified pitch area (sqft)
- Two story area (sqft)
- Two layer area (sqft)
- Per-pitch breakdown table: Pitch | Area (sqft) | Squares — up to 4 pitches on one property (e.g., 309 Palm Trail shows 1/12, 2/12, 4/12, 5/12)
- Squares at 0% waste (raw; 1 square = 100 sqft)
- Waste table: 0% / 5% / 10% / 12% / 15% / 17% / 20% / 22% — area (sqft) and squares at each level

**Linear (LF) fields — all in feet + inches**
- Total eaves
- Total valleys
- Total hips
- Total ridges
- Total rakes
- Total wall flashing
- Total step flashing
- Total transitions
- Total parapet wall
- Total unspecified
- Derived combos: Hips + ridges, Eaves + rakes

**Facet-level fields**
- Facet count (total roof facets)
- Per-facet area (sqft) labeled on diagram
- Per-facet pitch (X/12) labeled on diagram
- Per-facet water-flow direction arrow

**Property-level**
- Address
- Aerial imagery source (Bing) and date
- Number of detached structures (multi-structure reports split into Structure #1, #2, etc.)

### Branding

Reports are co-branded: Perkins Roofing Corp. logo top-left, "Powered by roofr" top-right on every interior page. Cover says "Prepared by Perkins Roofing Corp." The Roofr copyright line reads "Copyright © 2026 Roofr.com". Perkins controls the presentation layer; Roofr generates the measurements.

### Roofr Material Calculations Page

Roofr auto-generates a shingle-centric material estimate using brand-name products (IKO, CertainTeed, GAF, Owens Corning, Atlas). Categories:
- Shingles: bundles at 0/10/15/20% waste
- Starter (eaves + rakes LF): bundles
- Ice & Water (eaves + valleys + flashings LF): rolls
- Synthetic underlayment (total pitched sqft): rolls
- Capping (hips + ridges LF): bundles
- 8' Valley metal: sheets
- 10' Drip edge (eaves + rakes LF): sheets

**Perkins does NOT use this page for their actual orders.** They use their own Excel order forms with Polyglass/Elastobase/SAP/SAV/RoofNado products from ABC Supply. The Roofr material page is shingle-only and vendor-agnostic — it does not cover tile, metal panel, TPO, or BUR systems. Its primary value to Perkins is the measurement data feeding into their own order form, not the material quantities.

### Fields the Material Order Actually Consumes from Roofr

| Order form field | Roofr source field |
|---|---|
| Squares | Total pitched area ÷ 100 (the primary driver for nearly every roll/bundle quantity) |
| Perimeter / Eaves (ft.) | Total eaves (LF) |
| Hips / Ridges (ft.) | Hips + ridges (combined LF) |
| Valleys (ft.) | Total valleys (LF) |
| Wall Transitions (ft.) | Total transitions (or wall flashing, depending on system) |
| Rakes (ft.) | Total rakes (LF) |

The Squares field drives almost all material quantities. The linear fields drive: drip metal pieces, termination bar, valley metal rolls, ridge/hip tiles or cap shingles, eave closure LF, and parapet termination.

---

## 3. Material Order Forms

### Header Fields (Common to All Forms)

- P/O Name (customer name)
- Street, City, State, Zip
- Squares (total, from Roofr)
- Perimeter / Eaves (ft.)
- Hips / Ridges (ft.)
- Valleys (ft.)
- Wall Transitions (ft.)
- Rakes (ft.)

Note: Fred Thompson's first version of the order (Justin Palmer form) shows Squares=26.0 with most linear fields blank; the corrected version shows Squares=32.5. This confirms the form is completed incrementally and the Roofr report is not always attached at first pass.

### Full Item Inventory by Roof System

#### A. Metal Re-Roof (Fred Thompson — 32.5 sq, 3250 sloped sqft)

**Order #1: Dry-In**
- Rolls of RoofNado AnchorDeck PSU HT (50 mil) — qty: 20 [primary underlayment; ~1.6 sq/roll → 32.5 sq ÷ 1.6 ≈ 20]
- Rolls of Versashield (3.5 sq roll) — qty: blank [secondary/thermal break layer]
- Cans of 5 gal PG 500 — qty: 5 [adhesive/primer; ~6.5 sq/can → 32.5 ÷ 6.5 ≈ 5]
- Box(es) of Sheathing Nails — qty: 2
- Box(es) of 1-1/4" Roofing Coil Nails — qty: 3
- Box(es) of Tin Caps — qty: 2
- Sheets of 5/8" CDX Plywood — qty: 6 [repair allowance; not derived from sq]
- LF of 1x6 T&G — blank
- LF of 1x8 T&G — blank
- LF of Butyl Tape — qty: 0
- Box(es) of APS 500 Caulking — blank
- Color of Caulking — blank

**Order #2: Metal (per Metal Quote)**
- Add 2 Rolls of Visqueen [vapor barrier for flat/penetrations]
- Add 2 Rolls of Polyglass SA V
- Add 3 Rolls of Polyglass SA P

**Additional Details**
- 4" / 6" / 10" Gooseneck Vents (Sloped) — qty: per metal order / noted needed
- 2" / 3" / 4" Flex Boots — blank

**Additional Wood**
- LF 1x6/1x8/1x10/1x12 Square Edge Pressure Treated — blank
- Bundle(s) of 1x2 (96 LF each) — blank
- LF 2x4 Pressure Treated — blank

#### B. Tile Re-Roof (Jim Malooley — 76 sq, tile system)

**Order #1: Dry-In**
- Rolls of 6" SA V Flashing Strips — blank
- Rolls of MTS [Mineral Surface] — qty: 44 [~1.73 sq/roll → 76 ÷ 1.73 ≈ 44]
- Rolls of TU Plus — qty: 42 [~1.8 sq/roll → 76 ÷ 1.8 ≈ 42]
- Cans of 5 gal PG 500 — qty: 12
- Box(es) of Sheathing Nails — qty: 4
- Box(es) of 1-1/4" Roofing Coil Nails — qty: 4
- Box(es) of Tin Caps — qty: 4
- Sheets of 5/8" CDX Plywood — qty: 10 [repair allowance]
- LF of 1x6 T&G — blank
- LF of 1x8 T&G — blank
- Piece(s) of 3x3 .032 ALUM Drip Metal — qty: 85 [eaves + rakes LF ÷ ~10 ft/piece; 766+5=771 ÷ 9 ≈ 85]
- Color of Drip metal — White
- Cans of 1 gal PG 100 (Metal Primer) — qty: 2
- Roll(s) of SAV — qty: 2
- Roll(s) of .032 ALUM Valley Metal — qty: 5 [valleys 192 LF ÷ ~40 LF/roll ≈ 5]
- Piece(s) 4"x5" Galv "L" Metal — blank
- Piece(s) Termination Bar — blank
- Piece(s) of Galv. Stucco Stop — blank

**Order #2: Tiles**
- Squares of Field Tiles — qty: 82 [76 sq + ~8% waste → 82]
- LF Hip/Ridge/Rake Tiles — qty: 760 [matches hips+ridges+rakes LF from Roofr → 685+5+... ≈ 760]
- Brand of Tiles — Verea
- Type/Style — Spanish S
- Color — Graphite
- LF .032 ALUM Eave Closure Metal — qty: 850 [eaves LF ≈ 766 + waste ≈ 850]
- LF 5" Ridge Metal ("S"/Roll) — qty: 753.5 [hips+ridges LF from Roofr = 685+... ≈ 753]
- LF 4" Ridge Metal (flat) — blank
- LF 6" Ridge Metal (barrel) — blank
- Rolls of SAP FR (Open Valley) — blank
- Bags of QuickCrete (every 50 LF) — qty: 17 [760 LF hip/ridge ÷ 50 × 1.1 ≈ 17]
- Bags of Oxide / Color of Oxide — blank
- Box(es) of Long/Rake Tile Nails — blank

**Additional Details**
- 4" / 6" Gooseneck Vents — blank
- 10" Gooseneck Vents (Sloped) — qty: 7
- 2" / 3" / 4" Lead Stacks — 0 / 3 / 0
- Add 4 Roll of Visqueen, 2 rolls SAP, 2 buckets Polyflash 1C, 2 rolls 6" fabric, 4 chip brushes [flat/detail work supplements]
- NOTE: TILE is SPECIAL PRICE via Yovani [supplier contact note]

**Additional Wood**
- LF 1x6–1x12 Square Edge PT — blank
- Bundle(s) 1x2 (96 LF each) — blank
- LF 2x4 PT — blank

#### C. Shingle Re-Roof (Glenn Allen — 30 sq, CertainTeed Landmark)

**Order #1: Dry-In**
- Rolls of IR-XE (1.9 sq roll) — qty: 18 [30 sq ÷ 1.9 ≈ 16; 18 = ~15% waste factored]
- Rolls of MTS Plus (2 sq roll) — qty: 0
- Cans of 5 gal Poly Plus 50 — qty: 5
- Box(es) of Sheathing Nails — qty: 2
- Box(es) of 1-1/4" Roofing Coil Nails — qty: 3
- Box(es) of Tin Caps — qty: 2
- Sheets of 5/8" CDX Plywood — qty: 8
- LF of 1x6/1x8 T&G — blank
- Piece(s) of 2x2 Drip Metal — qty: 21 [rakes LF 10 ÷ 10 ft × 21... drip covers both eaves+rakes → 261+10=271 ÷ 10 ft/pc ≈ 27; 21 pcs of 2x2 + 11 pcs of 3x3 = 32 total ≈ 27 ft + waste]
- Piece(s) of 3x3 Drip Metal — qty: 11
- Color of Drip metal — Copper
- Cans of 1 gal PG 100 — qty: 2
- Roll(s) of 16 oz Copper Valley Metal — qty: 2
- Piece(s) 4"x5" Galv "L" Metal — blank
- Piece(s) Termination Bar — blank
- Piece(s) of Galv. Stucco Stop — blank

**Order #1: Shingles**
- Bundles of Field Shingles — qty: 99 [30 sq × 3 bundles/sq = 90 + 10% waste = 99]
- LF Hip/Ridge Shingles — qty: 102 [hips 82 + ridges 0... Roofr: hips=82 LF]
- Brand — CertainTeed (CT)
- Type/Style — Landmark
- Color — Pending
- Bundle(s) of Matching Starter Shingles — qty: 1
- 4' Section(s) of 12" CertainTeed Ridge Vent — qty: 15

**Additional**
- Add 2 Rolls of Visqueen
- Add 3 Rolls Polyglass SA V
- Add 6 Rolls Polyglass SA P
- 4" / 6" / 10" Gooseneck Vents — blank
- 2" Lead Stacks — qty: 3
- 3" Lead Stacks — qty: 1
- 4" Lead Stacks — blank

#### D. Flat / BUR Re-Roof (David Meharg — 18 sq, TPO/BUR system)

**Order #1: TPO/Dry-In**
- Rolls of Elastobase (if wood deck) — qty: 10 [18 sq; Elastobase ≈ 1.8 sq/roll → 18 ÷ 1.8 = 10]
- Rolls of SAV (Interply / Base) — qty: 10
- Rolls of SAV (Secondary Ply) — blank
- Rolls of SAP — qty: 20 [SAP ≈ 0.9 sq/roll → 18 ÷ 0.9 = 20]
- Box(es) of Sheathing Nails — qty: 1
- Box(es) of 1-1/4" Roofing Coil Nails — qty: 1
- Box(es) of Tin Caps — qty: 1
- Sheets of 5/8" CDX Plywood — qty: 2
- LF of 1x6/1x8 T&G — blank
- Upgrade Rolls of Polyfresko G FR — blank
- Cans of 1 gal PG 500 — qty: 2.83 [computed; ~6.35 sq/can]
- Piece(s) of 3x3 Drip Metal — qty: 4 [perimeter 30 LF / 10 = 3 + 1]
- Color — White
- Cans of 5 gal PG 100 (Metal Primer) — qty: 0.99
- PG 100 Asphalt Primer — qty: 0
- 4' PC Cant Strip — qty: 35 [wall transitions 125 LF ÷ 4 ≈ 31; +4 for corners → 35]
- Piece(s) Termination Bar — qty: 14 [wall transitions 125 LF ÷ 10 ft/pc ≈ 13 → 14]
- Piece(s) of Galv. Stucco Stop — blank
- 5 gal buckets WB-3000 (15 sq/bucket) — blank

**Order #1: Insulation**
- Box(es) of GAF #15 Screws / Size — blank
- 3" Drill Tec Barbed Plates (1 bucket) — qty: 0
- Olybond 500 A&B Canisters (set) — qty: 0
- PLUS TAPERED/ISO ORDER PER DRAWING — note

**Additional Details**
- 2" / 3" / 4" Lead Stacks — qty: 1 / 1 / 1
- Chem Curb Kits (4 per Box) — blank
- Hercules Retro Field Drains / Size — blank
- Aluminum Scupper Drains & Overflow Drains / Size — blank

**Supplements (Butterworth only, flat section)**
- Add 2 Rolls of Visqueen
- Add 2 Buckets of Polyflash 1C and 2 Rolls Fabric, 4 Chip Brushes

#### E. Mixed Systems — Key Differences in Butterworth (flat TPO + sloped tile)

Butterworth's order splits into two halves on the same sheet:
- Left columns: flat TPO system (same structure as Meharg above)
- Right columns (C/D): tile order for the back mansard roof
  - Squares of Field Tiles: 6
  - LF Hip/Ridge/Rake Tiles: 0
  - Brand: Verea / Type: Caribbean / Color: Red
  - LF Eave Closure Metal: 0
  - LF 5" Ridge Metal: 30 LF
  - Rolls SAP FR (Open Valley): blank
  - Bags QuickCrete: 3

### Quantity Formulas Inferable from the Data

| Material | Formula |
|---|---|
| Underlayment rolls (MTS/TU Plus) | `ceil(squares / roll_coverage)` where roll_coverage ≈ 1.7–1.9 sq/roll |
| Underlayment rolls (Elastobase/SAV) | `ceil(flat_squares / 1.8)` |
| SAP rolls | `ceil(flat_squares / 0.9)` |
| RoofNado rolls (50 mil) | `ceil(sloped_squares / 1.6)` |
| PG 500 (5 gal) | `ceil(squares / 6.5)` |
| Sheathing Nails | `ceil(squares / 15)` |
| 1-1/4" Coil Nails | `ceil(squares / 10)` |
| Tin Caps | `ceil(squares / 15)` |
| CDX Plywood sheets | Fixed repair allowance (6–10 per job regardless of size) |
| Drip Metal pieces (10 ft each) | `ceil((eaves_lf + rakes_lf) / 10)` |
| Termination Bar pieces (10 ft each) | `ceil(wall_transitions_lf / 10)` |
| Cant Strip pieces (4 ft each) | `ceil(wall_transitions_lf / 4)` |
| Field Tile squares | `ceil(sloped_squares * 1.08)` [~8% waste for tile] |
| Hip/Ridge/Rake Tile LF | `hips_lf + ridges_lf + rakes_lf` (direct from Roofr) |
| Ridge Metal LF (5" S-roll) | `hips_lf + ridges_lf` (direct from Roofr) |
| Eave Closure LF | `eaves_lf * 1.1` |
| QuickCrete bags | `ceil(hip_ridge_rake_tile_lf / 50)` |
| Valley Metal rolls (ALUM) | `ceil(valleys_lf / 40)` |
| Ridge Vent sections (4 ft) | `ceil(ridges_lf / 4)` [shingle only] |
| Field Shingle bundles | `ceil(sloped_squares * 3 * (1 + waste_pct))` |
| Hip/Ridge Shingle LF | `hips_lf + ridges_lf` |

### Differences by System

| Attribute | Metal | Tile | Shingle | Flat (BUR/TPO) |
|---|---|---|---|---|
| Primary underlayment | RoofNado AnchorDeck PSU (40 or 50 mil) | MTS + TU Plus (2-ply) | IR-Xe or Polyglass IR | Elastobase + SAV + SAP (3-ply) |
| Field material | Metal panels per separate quote | Field tiles (sq) | Shingles (bundles) | None — membrane is the underlayment |
| Ridge/hip material | Ridge metal LF (per metal quote) | Hip/ridge/rake tiles LF + QuickCrete | Hip/ridge shingle bundles + ridge vent | N/A |
| Valley material | ALUM valley metal rolls | SAP FR open valley rolls | Copper valley metal rolls | N/A |
| Eave treatment | Gooseneck vents (sloped), per metal order | ALUM eave closure LF | Drip metal + starter | Drip metal + cant strip |
| Wall termination | Caulk/APS 500 | Stucco stop or T-bar | Stucco stop | Termination bar + cant strip |
| Insulation | Rare (Versashield only) | No | No | Optional (ISO board, GAF screws/plates) |
| Drain hardware | None | None | None | Retro field drains, scupper drains |
| Special notes | Vents per metal order; separate metal quote | Tile via special supplier (Yovani); color critical | Ridge vent sections; starter bundle | PB 70 / Polyflash 1C for penetrations |
| Supplier extras | Visqueen (2 rolls) | Visqueen (4 rolls), Polyflash, fabric | Visqueen (2 rolls), SAV/SAP add rolls | Visqueen, PB 70, fabric, brushes |

---

## 4. Data Model Requirements

### Core Entities

```
RoofMeasurement
  id, job_address, roofr_report_id, imagery_date, imagery_source
  total_area_sqft, pitched_area_sqft, flat_area_sqft
  facet_count, predominant_pitch
  eaves_lf, valleys_lf, hips_lf, ridges_lf, rakes_lf
  wall_flashing_lf, step_flashing_lf, transitions_lf, parapet_wall_lf
  hips_plus_ridges_lf  [derived]
  eaves_plus_rakes_lf  [derived]
  total_squares        [derived: pitched_area / 100]
  pitch_breakdown[]    [{pitch: "3/12", area_sqft, squares}]
  waste_table[]        [{waste_pct, area_sqft, squares}]

DetailsPage (= PermitSpec)
  id, job_id, measurement_id
  owner_name, phone, email, job_address
  roof_types[]         [SHINGLE | FLAT | METAL | TILE]
  deck_type            [WOOD | STEEL | CONCRETE]
  permit_code_sections [e.g., "4, 5 & 7"]
  sloped_pitch, flat_pitch
  sloped_sqft, flat_sqft
  sloped_mean_height_ft, flat_mean_height_ft
  floor_count
  sloped_system_spec   [free text]
  flat_system_spec     [free text]
  insulation_used, insulation_type
  parapet_walls, parapet_height_ft
  wall_flash_method    [L_FLASHING_STUCCO_STOP | CANT_TBAR]
  job_value_dollars
  diagram_reference    ["See RoofR" | blob]

RoofSystem  (catalog / lookup)
  id, name             [METAL | TILE | SHINGLE | FLAT_BUR | FLAT_TPO]
  layers[]             [{product_sku, description, layer_order}]
  order_form_template_id

Estimate / Proposal
  id, job_id, details_page_id
  line_items[], total_value
  (feeds job_value on DetailsPage)

MaterialOrderForm
  id, job_id, measurement_id, roof_system_id
  created_date, ordered_by
  header_fields        [squares, eaves_lf, hips_ridges_lf, valleys_lf, transitions_lf, rakes_lf]
  line_items[]         → MaterialOrderLine

MaterialOrderLine
  id, order_id, section   [DRY_IN | TILES | SHINGLES | INSULATION | ADDITIONAL | WOOD]
  item_ref               → PriceBookItem
  qty_ordered, unit
  qty_formula            [e.g., "ceil(squares / roll_coverage)"]
  notes

PriceBookItem  (ABC Supply catalog)
  id, supplier           [ABC_SUPPLY | VEREA | ...]
  sku, description
  unit                   [roll | bundle | box | can | sheet | piece | LF | bag | bucket]
  unit_coverage          [e.g., 1.9 sq/roll for MTS Plus; 100 sqft/bundle for shingles]
  current_unit_price
  effective_date
  roof_system_ids[]      [which systems use this item]

SupplierQuote  (for metal panels — separate flow)
  id, job_id, supplier, quote_date, panel_spec, total_price
  referenced_from MaterialOrderLine.notes ["per Metal Quote"]
```

### Key Relationships

```
RoofMeasurement  ←1:1→  DetailsPage  ←1:1→  Estimate
                                               ↓
RoofMeasurement  ←1:many→  MaterialOrderForm  ←1:many→  MaterialOrderLine
                                                            ↓
                                                        PriceBookItem
```

### Quantity Engine Logic

The engine takes `RoofMeasurement` + `RoofSystem` as inputs and outputs `MaterialOrderLine[]`:

1. For each `PriceBookItem` linked to the system, apply the `qty_formula` using the measurement fields.
2. Round up (ceiling), apply minimum-order-quantity constraints from the price book.
3. Flag items where `qty_formula` is `null` (manual entry required — e.g., plywood repair sheets, gooseneck vent counts, lead stack counts).
4. Tile system: fire a secondary `TileOrderBlock` that depends on tile brand/style/color selected at estimate time (not derivable from measurements alone).
5. Metal system: emit a `SupplierQuote` stub flagged "per Metal Quote" — panel quantities are handled by the metal subcontractor, not this engine.

### What We Have vs. Google Solar

Our existing Squares feature (Google Solar-based) produces total pitched area and basic pitch. To fully replicate Roofr and feed the order engine, we additionally need:

- Eaves LF (separate from perimeter — eaves only, not rakes)
- Rakes LF
- Hips LF
- Ridges LF
- Valleys LF
- Wall flashing / transitions LF
- Parapet wall LF
- Per-facet pitch breakdown
- Flat vs. pitched area split

Google Solar does not produce these linear measurements; Roofr derives them from aerial photogrammetry with manual QC. Until we have a Roofr API integration or equivalent aerial measurement, these fields must be entered manually from the Roofr report — which is exactly what Perkins does today (the Details Page says "See RoofR" and the order form header fields are filled from the Roofr summary page).

---

_End of analysis_
