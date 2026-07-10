# Perkins Roofing Corp — Proposal Template Analysis
*Reverse-engineered from 8 sold-job PDFs, 2026-07-10*

## Corpus

| File | Customer | Date | System(s) | Total |
|------|----------|------|-----------|-------|
| Palmer Metal Re-Roof | Justin Palmer, 503 Xanadu Pl, Jupiter FL 33477 | 7/10/2026 | Metal | $45,790.00 |
| Thompson Metal Re-Roof | Fred Thompson, 3699 NE 6th Dr, Boca Raton FL 33431 | 5/5/2026 | Metal + Flat + Gutters | $50,601.88 |
| Glenn Allen Shingle ReRoof | Glenn Allen, 1251 Holly Cove Dr, Jupiter FL 33458 | 6/23/2026 | Shingle + Flat + Copper | $32,943.20 |
| Person Shingle Re-Roof | Doug Person, 302 Ridge Rd, Jupiter FL 33477 | 2/4/2026 | Shingle + Gutters | $35,412.71 |
| Mazzeo Tile Roof | Joseph Mazzeo, 3549 Moon Bay Cir, Wellington FL 33414 | 3/10/2026 | Tile + Gutters | $45,501.75 |
| Malooley Tile Re-Roof | Jim Malooley, 309 Palm Trail, Delray Beach FL 33483 | 5/18/2026 | Tile + Gutters | $127,263.35 |
| Butterworth 332 Pilgrim | Melissa Butterworth, 332 Pilgrim Rd, WPB FL 33405 | 5/14/2026 | Flat + Tile + Paint | $42,529.50 |
| Mehang 3-Ply Flat Re-Roof | David Mehang / Two Koalas LLC, 404 S M St, Lake Worth FL 33460 | 10/8/2025 | 3-Ply BUR + Stucco + Straps | $26,370.00 |

---

## 1. Common Document Skeleton

Every proposal is one contiguous PDF with this exact section order:

```
[PAGE 1]
  Logo header (Perkins Roofing Corp. house icon, centered)
  Horizontal rule
  "PROPOSAL" (centered, bold)
  Horizontal rule
  Header grid:
    TO:  [client name]          Project: [project name]
         [address line 1]       Address: [blank — address is in TO block]
         [city, state zip]      Date:    [M/D/YYYY]
  Italic tagline: "We propose to furnish all materials, equipment, and labor,
    subject to any exclusions listed below, required to complete the following:"

[SCOPE SECTION — one numbered item per line item/package]
  N.  [PACKAGE NAME] - [System Description]          $X,XXX.XX
      Description of Services:
        ---[SECTION HEADER IN DASHES]---
        Specifications of Proposed Work:
        1. [step]
        2. [step]
        ...
        ---ADDITIONAL INFORMATION---
        1–7 [boilerplate bullets, same every proposal]
        ---WARRANTY---
        [warranty terms specific to package/system]
        ---PERKINS BONUS VALUES---
        [10-item value stack, dollar values vary by warranty length]
        Quantity: [N x Squares | N x Feet]

[After last roofing line item, optional add-ons may follow same structure]

[PRICING SUMMARY — bottom of last scope page]
  Subtotal:  $XX,XXX.XX
  *0% Tax:   $0.00
  TOTAL:     $XX,XXX.XX

[SIGNATURE BLOCK — immediately after pricing]
  Contractor: [signature]  [Perkins Roofing Jupiter]  [date]
  ACCEPTANCE OF PROPOSAL: The above prices, scope, specifications and
    conditions are satisfactory and hereby accepted. You are authorized
    to do the work specified.
  Client: [signature]  [printed name]  [date]

[TERMS AND CONDITIONS — separate section with bold heading]
  Intro: "Includes all service dates, skilled techs, supplies and materials,
    waste service fee, taxes and insurance."
  ***COMMERCIAL PROPERTIES (INC. CONDO ASSOCIATIONS) MUST PAY WITH CASH,
    CHECK OR MONEY ORDERS***
  RE-ROOF ROOF PAYMENT TERMS: [milestone list]
  BUILDERS RISK INSURANCE: [paragraph]
  FLORIDA HOMEOWNERS' CONSTRUCTION RECOVERY FUND: [CILB paragraph + address]
  HB 939 – GENERAL STATE OF EMERGENCY: [statutory cancellation clause]
  WINDSTORM INSURANCE: [roof age table by system type]
  CONTRACT PROVISIONS 1–N: [numbered clauses, see section 5]

[LUMBER SCHEDULE — always last exhibit before back page]
  Blue branded header: PERKINS ROOFING CORP. - MIAMI
    575 NW 152nd St, Miami, FL 33169 / 305.687.6521 / 305.642.7663
  "LUMBER SCHEDULE" (centered, bold)
  Intro line about 1-story/6-12 baseline + Killz priming add-on
  Tables: Roof Deck | Fascia Boards, Wood Nailers | Double Demo | Unit Prices
  Footnote: ***Metal type or sizing upgrades and/or upgrades to your roofing
    system (SWR) and additional layers are available upon request...***

[BACK PAGE]
  Blank page with bottom banner: www.perkinsroofing.net
  Footer: "Perkins Roofing Jupiter · 15658 Alexander Run · Jupiter, FL 33478"
```

**Branding elements present on every page:**
- Logo mark (blue house icon + PERKINS / ROOFING CORP. wordmark) — cover page only
- Footer on every page: "Perkins Roofing Jupiter · 15658 Alexander Run · Jupiter, FL 33478"
- Back-page banner: teal/navy gradient bar with "WWW.PERKINSROOFING.NET"
- Lumber Schedule header uses distinct PERKINS ROOFING CORP. - MIAMI banner (blue header image) — this is a static exhibit, same in all 8 proposals

**Contractor license:** Not printed as a separate field. The contractor's name and "Perkins Roofing Jupiter" appear as the Contractor signature block. No CRC/license number appears on the face of these 8 proposals.

---

## 2. Scope-of-Work Patterns Per Roof System

Each numbered line item starts with `---[SYSTEM HEADER IN DASHES]---` then `Specifications of Proposed Work:` followed by numbered steps. Steps are boilerplate per system with only a few job-specific substitutions (tile brand, panel gauge, sq count, special site notes in bold).

### 2a. Metal Re-Roof (Palmer, Thompson)

Header: `---[GAUGE] MIL FINISH GALVALUME STEEL (1.5" STANDING SEAM) METAL RE-ROOF---`

Steps (standard order):
1. Obtain roofing permit; processing included, permit fee(s) extra
2. Tear off existing [prior system] and dispose of debris; demo NOTE about standard layers
3. Replace damaged decking wood; 100 LF / 2 sheets allowance; Lumber Schedule reference; painting add-on $4.25/LF
4. Re-nail decking per revised Florida Building Code
5. Install Roofnado AnchorDeck PSU HT 50 mil Ice and Water Barrier (base layer)
6. Fabricate/prime/install 3"×3" perimeter bull nose drip edge metal; stainless or copper upgrade billed at material cost; fastened every 4" with 1-1/4" ring shank nails; wall flashings at $110/man-hr + material
7. Install new Mil Finish Steel (1.5" standing seam); all clips, screws, ridge caps, valley metal, gables, flashing, eaves metal in standard color of choice
   NOTE: 24 GA thicker than 26 GA; Mil finish not recommended near salt air (see COASTAL upgrade)
8. Clean up and haul away debris daily

Additional NOTE (metal only, after step 8): "Mil finish panels included here but not recommended as salt in the air may prematurely rust the panels if not properly protected. See Preferred Option for Kynar Coated Panels."

FBC reference: "Re-nail the existing decking to meet revised Florida Building Code"
HVHZ: Not mentioned in metal scope (non-HVHZ jobs in this corpus). Additional Information item 1 says "All roof work done in accordance with the Florida Building Code."

### 2b. Tile Re-Roof (Mazzeo, Malooley, Butterworth rear, Thompson — none in Thompson; Butterworth has tile)

Header: `---PERKINS PROTECTOR: TILE RE-ROOF---`

Steps:
1. Obtain permit
2. Tear off existing [N-story] tile roof; demo NOTE about standard layers
3. Replace damaged decking; 100 LF / 2 sheets allowance; Lumber Schedule; painting add-on
4. Re-nail decking per revised FBC
5. Install Polyglass 6" SA Flashing strips at terminations and 1/2 sheet SA V FR at valleys prior to metal install
6. Fabricate/prime/install 3"×3" drip edge; Standard Colors: White, Black, Brown, Beige, Terracotta, Mil Finish; wall flashings at T&M
7. Check wall flashing metals; replace at $110/man-hr + material; remaining "L" flashings 3-course sealed with Polyflash 1C and 6" fabric
8. Install new 16" 26 gage galvanized metal in all roof valleys
9. Replace all plumbing vent flashings
10. Replace "all purpose" gooseneck ventilators with new
11. Install Polyglass TU Plus 80 mil roof tile underlayment
    NOTE: Polyglass MTS Secondary Water Barrier available for upgrade
12. Install 26 gage galvanized hip and ridge anchor metal
13. Install Eagle concrete roof tiles [or Crown, depending on job]: 13" concrete flat/roll tile in standard color; 3M Polyfoam tile adhesive (or Dupont Tile Bond)
    NOTE: Boral costs additional $15/SQ; clay tile upgrade priced in PREMIUM option
14. Install hip and ridge tiles; point with mortar, choice of color; Colored Mortar INCLUDED; Mitered tile option available at no charge
15. Clean up and haul away debris daily
    NOTE: Price includes 80 mil TU Plus and 3×3 drip metal upgrades with ACH-160 dual-component foam (160 mph wind rating)
    NOTE: Mechanically fastened / single-component tiles rated only to 110-120 mph

FBC: "Re-nail existing decking and/or sheathing using 8d ring shank nails per revised Florida Building Code"

### 2c. Shingle Re-Roof (Glenn Allen, Person)

Header: `---PERKINS PROTECTOR: SHINGLE RE-ROOF---`

Steps:
1. Obtain permit
2. Tear off existing roof; expose wood decking; haul debris
3. Replace damaged decking; 100 LF / 2 sheets allowance; Lumber Schedule; painting add-on
4. Re-nail decking per revised FBC (Person: "approved ring shank nails"; Allen: "8d ring shank nails")
5. Install Roofnado Spyder PSU 40 mil high temperature ice and water barrier self-adhered to structural wood deck
   ADDITIONAL NOTE: Additional secondary water barrier for warranty upgrade priced below
6. Fabricate/prime/install 3"×3" drip edge; Standard Colors: White, Black, Brown, Beige, Terracotta, Mil Finish; wall flashings at T&M; remaining L-flashings 3-course Polyflash 1C
7. Check wall flashings
8. Install new 16" 26 gage galvanized metal in all roof valleys
9. Install new architectural CertainTeed Landmark shingles in color of owner's choice; upgrade to PREMIUM Landmark Pros available
10. Replace all plumbing vent flashings
11. Clean up and haul away debris daily

HVHZ note (Person only): "All roof work done in accordance with HVHZ Florida Building Code." — Person is Jupiter FL 33477 (Palm Beach County, non-HVHZ), so this appears to be a template variant that got the HVHZ language applied. Glenn Allen's same address range uses non-HVHZ "Florida Building Code."

### 2d. Flat / BUR Re-Roof (Thompson, Glenn Allen partial, Butterworth, Mehang)

Two flat sub-systems appear:

**Standard Polyglass Flat (Thompson, Glenn Allen, Butterworth):**
Header: `---PERKINS PROTECTOR - Polyglass Flat Roof---`
Note: "Perkins Roofing price on flat roofs is dependent upon ability to core test the roof deck prior to bid and to have direct access to see deck from underneath."
Steps:
1. Obtain permit
2. Tear off; NOTE: standard low-sloped demo = max 1 anchor sheet + 1 underlayment + cap; recommends core test; extra layers per Lumber Chart
3. Replace damaged decking/wood nailers; 100 LF / 2 sheets
4a. WOOD DECK: Re-nail with ring shank nails per revised FBC
4b. OPTIONAL INSULATION SYSTEM
   NOTE: Metal/Gypsum decks require RigidBoard/Tapered; concrete uses low-rise foam
   NOTE: LWIC decks — Polyglass Modifleece base layer with low-rise foam
5. Install cant at walls and A/C equipment curbs
6. Install Elastobase SA V modified bitumen interply (Wood/Metal deck) OR re-prime with PG 100 asphalt primer (Concrete)
7. Install Polyglass SA V modified bitumen interply over field
8. Install Polyglass SAP modified bitumen cap (Wood deck, white granulated with leister) OR hybrid torch Polyglass G cap (all other decks, white granulated)
9. Replace ventilators; flash mechanical racks
10. Fabricate/prime/install 3"×3" drip edge; COASTAL note for within 1,500 ft of salt/brackish water
11. Check wall flashings; T&M if replacement needed; "important to discuss drainage plan" and "desired roof termination at the edge"
12. Liquid flash all details with Polyflash 1C, 3-coursed polyurethane
13. Clean up daily
14. Liquid flash all details

**3-Ply Polyglass BUR (Mehang only):**
Header: `---BUILT-UP 3-PLY POLYGLASS ROOFING SYSTEM---`
Steps:
1. Obtain permit
2. Tear off; low-sloped demo note; recommends core test
3. Replace decking; 100 LF / 2 sheets
4. Re-nail with ring shank nails per FBC
5. Install one heavy duty Elastobase nailable base using 1-1/4" ring shank nails and Miami-Dade approved tin tags; optional tapered insulation if selected
6. Install Elastobase SA V modified bitumen interply
7. Fabricate/prime/install 3"×3" drip edge
8. Check wall flashings; T&M
9. Install Polyglass SAP modified bitumen cap system, white granulated
10. Clean up daily

HVHZ: Mehang (Lake Worth FL, Palm Beach County) Additional Information item 1: "All roof work done in accordance with the high velocity hurricane zone section of the Florida Building Code." — This is the HVHZ-specific variant of the Additional Information block.

---

## 3. Line-Item and Pricing Presentation

**Format:** All proposals use a numbered line-item list, each with a title, italic "Description of Services:" label, body text, and a right-aligned dollar amount on the title line. This is lump-sum per line item, never itemized within a line item.

**Package structure per line item:**
- Every primary roofing work item is named with a Perkins package tier prefix
- Add-ons and options are separate numbered items either with a dollar price or $0.00 with "ADDITIONAL UPGRADE PRICE: $X" bolded below their description

**Package tiers observed:**

| Package | System | Warranty upgrade | What changes |
|---------|--------|-----------------|-------------|
| PERKINS PROTECTOR | Any | Base: 7-yr Perkins | Base materials, standard metals |
| PERKINS COASTAL | Metal or Shingle | 12-yr Perkins | Upgrade to .032 Aluminum Kynar Fluropon panels (metal) or double-layer Polyglass MTS Plus underlayment + CT Landmark Pro shingles + aluminum metals (shingle) |
| PERKINS PREMIUM (regional name) | Tile only | Longer warranty | Upgrade to clay tile (vs concrete); double underlayment |

Regional PREMIUM names seen: Caribbean (Butterworth), Mediterranean (Malooley). These are regional brand names, not different products.

**Optional/alternate items:**
- Named "(OPTIONAL)" in the item title; dollar amount shown on title line; "ADDITIONAL UPGRADE PRICE: $X" also appears in body
- Sometimes items are $0.00 on title line with "ADDITIONAL UPGRADE PRICE: $X" in body (e.g., Malooley gutters)
- Discounts appear as separate negative line items (e.g., "Discount ($1,000.00)", "Valentine's Day Discount ($1,700.16)")

**Pricing summary block (identical wording in all proposals):**
```
Subtotal:    $XX,XXX.XX
*0% Tax:     $0.00
TOTAL:       $XX,XXX.XX
```

**Payment schedule — standard (6 of 8 proposals):**
```
RE-ROOF ROOF PAYMENT TERMS:
1. 30% due upon acceptance, prior to permitting
2. 30% due upon material delivery / mobilization
3. 30% due upon completion of roof dry-in, prior to cap installation
4. NOTE: Any additional lumber used above the listed allowance will be billed and payment
   due immediately following the completion of dry-in.
5. Remaining Net Balance due upon substantial completion (late fees apply after 30 days overdue)
```

**Payment schedule variants:**
- **Palmer (financing variant):** 15% / 15% / 30% / 30% / balance — 5 milestones instead of the standard 4 (deposit split into two smaller draws, presumably to match a financing product). This is a field-level override, not a separate template.
- **Thompson:** Same standard 30/30/30/balance, but Thompson had a separate gutter item added to proposal — no change to payment structure.
- The lumber surcharge note (item 4) is present in all standard proposals.

---

## 4. Variable Fields Inventory

These are the fields that change per job. This is the complete template variable list.

### Header / Cover
- `client_name` — full name (e.g., "Justin Palmer")
- `client_address_line1` — street (e.g., "503 Xanadu Place")
- `client_address_line2` — city, state, zip (e.g., "Jupiter, FL 33477")
- `project_name` — short description (e.g., "Thompson Metal Re-Roof")
- `proposal_date` — M/D/YYYY

### Per Line Item
- `item_number` — sequential integer (1, 2, 3…)
- `item_title` — package tier + system descriptor (e.g., "PERKINS PROTECTOR - Metal Re-Roof")
- `item_price` — dollar amount right-aligned (positive or negative for discounts)
- `item_is_optional` — boolean; prefixes title with "(OPTIONAL)" when true
- `item_header` — dashed section header (e.g., "---24 GA MIL FINISH GALVALUME STEEL (1.5" STANDING SEAM) METAL RE-ROOF---")
- `system_type` — enum: METAL | TILE | SHINGLE | FLAT_POLYGLASS | FLAT_3PLY | COASTAL_METAL | COASTAL_SHINGLE | PREMIUM_TILE | GUTTER | STUCCO | HURRICANE_STRAPS | COPPER | DISCOUNT | OTHER
- `existing_system_description` — what's being torn off (e.g., "existing mortar-set concrete tile roof system")
- `stories` — integer; triggers surcharge note in lumber schedule if > 1
- `slope` — fraction string (e.g., "6/12"); triggers T&M note if > 7/12 or 3-story
- `special_site_notes` — free-text bold notes (e.g., harness requirement, hand demolition, unique construction type warning)

### Scope Body Variables (system-specific)
**Metal:**
- `panel_gauge` — "24 GA" or "26 GA"
- `panel_finish` — "MIL FINISH" or "KYNAR COATED"
- `panel_material` — "GALVALUME STEEL" | "ALUMINUM" | "COASTALUME"
- `underlayment_product` — "Roofnado AnchorDeck PSU HT 50 mil" (standard) or variant
- `metal_color` — "standard color of your choice"

**Tile:**
- `tile_brand` — "Eagle" (Mazzeo) | "Crown" (Malooley) | not specified (Butterworth)
- `tile_type` — "13 inch concrete flat tile" | "concrete roll tile" | clay
- `tile_adhesive` — "3M Polyfoam" | "Dupont Tile Bond"
- `tile_color` — "any standard color"
- `underlayment_product` — "Polyglass TU Plus 80 mil" (standard)
- `mortar_color` — "choice of color"
- `clay_upgrade_note` — boolean

**Shingle:**
- `shingle_brand` — "CertainTeed Landmark" (standard) | "CT Landmark Pro" (COASTAL)
- `underlayment_product` — "Roofnado Spyder PSU 40 mil" (standard)
- `swr_upgrade_note` — boolean

**Flat:**
- `deck_type` — WOOD | METAL | GYPSUM | CONCRETE | LWIC
- `flat_system_variant` — STANDARD_POLYGLASS | 3PLY_BUR
- `insulation_optional` — boolean + price

### Warranty (per line item)
- `perkins_warranty_years` — integer (5 for gutters, 7 for base, 10 for flat+insulation, 12 for COASTAL)
- `polyglass_warranty_years` — integer (15 for 3-ply, 20 for flat/tile, 20 for shingle underlayment)
- `manufacturer_warranty` — free text (CertainTeed, Metal Alliance, Dupont, etc.)
- `swr_insurance_note` — boolean (appears in COASTAL items)

### Bonus Values (per line item)
- `bonus_perkins_years` — same as `perkins_warranty_years`; drives "X years" in items 1 and 2
- `bonus_total_value` — computed sum (e.g., "$10,665.00" standard base, "$30,665.00" metal with SWR)
- `bonus_swr_item` — boolean; adds item 11 (SWR insurance savings) when true

### Quantity
- `quantity_value` — number (e.g., 33, 3.5, 105)
- `quantity_unit` — "Squares" | "Feet" | "Straps"

### Additional Information (all items)
- `hvhz_flag` — boolean; changes item 1 text from "Florida Building Code" to "high velocity hurricane zone section of the Florida Building Code"

### Pricing Summary
- `subtotal` — computed sum of all line item prices
- `tax` — always $0.00 in all 8 proposals
- `total` — equals subtotal

### Payment Schedule
- `payment_schedule_variant` — "STANDARD_30_30_30" | "CUSTOM" (custom requires explicit milestone list)
- `payment_milestones` — list of (pct, trigger_description) if CUSTOM

### Signature Block
- `contractor_name` — printed + signature (e.g., "Tim Kanak", "Marie Ramos")
- `contractor_branch` — "Perkins Roofing Jupiter" (all 8 proposals)
- `contractor_date` — M/D/YYYY
- `client_signature_name` — printed name (may differ from client_name if entity — e.g., "David Meharg - Two Koalas. LLC")
- `client_date` — M/D/YYYY

### Terms and Conditions (static with one conditional)
- T&C clauses 1–49 are fully static boilerplate in all proposals that show them
- One conditional: T&C clause count differs between older proposals (Mazzeo: clauses end at 49) and no observed difference in numbering otherwise

### Lumber Schedule
- Fully static exhibit — identical in all 8 proposals; no per-job variables

---

## 5. Terms and Conditions Structure

The T&C section is **embedded in the proposal document** (not a separate exhibit), appearing immediately after the pricing summary/signature block and before the Lumber Schedule. It is fully boilerplate — word-for-word identical across all proposals that expose it. The Mazzeo proposal shows the most complete T&C set and reveals the full clause list.

**T&C section order:**
1. Intro + commercial cash-only notice
2. RE-ROOF ROOF PAYMENT TERMS (milestone list — this IS variable, see section 3)
3. BUILDERS RISK INSURANCE
4. FLORIDA HOMEOWNERS' CONSTRUCTION RECOVERY FUND (statutory — CILB address)
5. HB 939 – GENERAL STATE OF EMERGENCY (10-day cancellation for governor's emergency declaration)
6. WINDSTORM INSURANCE (roof age table: 3-tab 15yr, arch shingle 20yr, flat 20yr, concrete tile 20yr, clay tile 25yr, metal 30yr)
7. CONTRACT PROVISIONS (numbered 1–N):
   1. SCHEDULE
   2. HOA / GATES / NEIGHBOR ACCESS
   3. MATERIAL ESCALATION + MATERIAL UNAVAILABILITY
   4. LIABILITY (general) + sub-clauses: INTERIOR PROTECTION, UNDERGROUND ELEMENTS, ACCESS, UTILITIES, NAILS AFTER COMPLETION, PRE-CONSTRUCTION
   5. WARRANTY
   6. WARRANTY TRANSFER ($500 admin fee, 90-day notification window)
   7. REPAIR WARRANTIES
   8. ROOF REPAIR MATERIAL AESTHETICS
   9. TIME AND MATERIAL (T&M) — $110/man-hr + materials + 15% markup
   10. DAMAGE LIMITATION (capped at contract price; mold sub-clause)
   11. ROOF COMPONENTS
   12. NON-ROOFING DETAILS
   13. ANNUAL MAINTENANCE INSPECTION
   14. EXISTING STRUCTURE
   15. SCOPE OF WORK
   16. WOOD CLAUSE + WOOD BILLS
   17. INSPECTOR / WARRANTY REQUIRED CHANGE ORDER
   18. PERMITTING AND ENGINEERING FEES (15% pass-through) + GAS VENTS + HURRICANE STRAPPING
   19. OPEN / EXPOSED BEAM CEILING
   20. ICYNENE INSULATION
   21. OPEN VALLEYS AT TILE ROOF
   22. INTERIOR ACCESS
   23. INSULATION / VENTILATION
   24. DEMOLITION + TILE ROOF DEMO
   25. OIL CANNING
   26. INTERNAL PLUMBING SYSTEMS
   27. ADDITIONS BY OTHERS
   28. OTHER TRADES
   29. CONTRACT ADDENDUMS
   30. CONTRACT NEGOTIATION
   31. WORKMANSHIP
   32. CONSULTATION
   33. DEMOBILIZATION (includes force majeure; bold text for demobilization rights)
   34. CANCELATION / UNKNOWN CONDITIONS + HB 715 HURRICANE CANCELATION CLAUSE
   35. MATERIALS (leftover materials remain Perkins property)
   36. HOME OWNER'S INSURANCE (per HB 715)
   37. ADDITIONAL TERMS AGREEMENT + FINAL PAYMENT NOTE
   38. LATE FEES (5% per 30 days overdue, compounding) + COLLECTIONS
   39. LIEN RIGHTS (45 days; Sections 713.001-713.37 Florida Statutes; Florida Construction Lien Law)
   40. WRITTEN NOTICE (Chapter 558 Florida Statutes; 60-day cure period before legal action)
   41. ATTORNEY FEES (loser pays)
   42. CREDIT CARDS (residential only, up to $50k; 4% merchant fee)
   43. FINANCING (RenewPace / third-party; down payment still required)
   44. REFERRAL PROGRAM ($50 Amazon gift card)
   45. DIGITAL MATERIAL RIGHTS (drone photography; drone consent pre-contract)
   46. NAMED STORM PRICING
   47. PROFILE AND COLOR SELECTIONS (14-day selection deadline or price may increase)
   48. PRICE QUOTE (30-day expiry; metal: 15-day expiry)
   49. EXECUTION OF CONTRACT (dual signature = executed contract)

**Key statutory references embedded in T&C:**
- HB 939 (General State of Emergency, 10-day cancellation)
- HB 715 (Hurricane cancellation clause, 10-day / 180-day post-emergency)
- Sections 713.001-713.37 Florida Statutes (Construction Lien Law)
- Chapter 558 Florida Statutes (written defect notice)
- Florida Homeowners' Construction Recovery Fund / CILB

---

## 6. Cross-Proposal Differences: Variants vs Conditionals

**Conclusion: One master template with conditionals, not separate templates per system.**

The system-type drives which scope-of-work body block is emitted. All surrounding structure (header, additional info, warranty block format, bonus values block, T&C, signature, lumber schedule, back page) is identical boilerplate.

### Confirmed conditionals (template logic needed):

| Conditional | Trigger | Effect |
|------------|---------|--------|
| HVHZ language | Job address in HVHZ zone (Miami-Dade, Broward) | Changes Additional Info item 1 from "Florida Building Code" to "high velocity hurricane zone section of the Florida Building Code" |
| Payment schedule | Custom financing | Replaces standard 30/30/30/balance with custom milestone list |
| Bonus item 11 (SWR) | COASTAL package | Adds SWR insurance savings item; changes bonus total |
| Bonus years | Package warranty length | Items 1 and 2 dollar values scale with warranty years |
| Demo NOTE wording | Slope system type | "sloped roof" vs "low-sloped roof" in step 2 demo note |
| Discount item | Sales promotion active | Adds a negative line item with promotion name and dollar off |
| Wood allowance | Job size / stories | Glenn Allen got 300 LF / 6 sheets vs standard 100 LF / 2 sheets (larger job) |
| COASTAL upgrade note | Metal base item | Adds NOTE at end of metal scope about mil finish + salt air risk |
| Stucco/waterproofing item | Site condition | Separate line item added (Mehang, Butterworth) |
| Hurricane straps | Miami-Dade / HVHZ | Separate line item (Mehang) |
| Multi-structure | Multiple buildings on property | Each structure listed in parenthetical "(Both Structures)", "(BACK ONLY)" |
| Optional items | Sales decision | Prefix "(OPTIONAL)" on title; body includes "ADDITIONAL UPGRADE PRICE:" callout |
| PREMIUM regional name | Tile job + premium package | "Caribbean" or "Mediterranean" suffix — marketing name only, not a product difference |
| Gutters | Any job | Separate line item with its own warranty (5-yr Perkins) and linear-foot quantity |
| Copper/special metals | Specific detail work | Separate line item (Glenn Allen copper ridge) |

### Observed product-level variants within system types:

**Tile adhesive:** Eagle + 3M Polyfoam (Mazzeo) vs Crown + Dupont Tile Bond (Malooley). Both are valid; salesperson/availability driven. Template should accept `tile_brand` + `tile_adhesive` variables.

**Metal gauge:** 24 GA used in both metal proposals (Palmer, Thompson). 26 GA appears in valleys (all proposals). The base price line always specifies the panel gauge.

**Flat deck type:** Standard Polyglass (Thompson, Allen, Butterworth) uses a different step sequence than 3-ply BUR (Mehang). These are two distinct scope blocks, not just variable substitutions.

**Underlayment naming:** Shingle jobs use "Roofnado Spyder PSU 40 mil"; metal jobs use "Roofnado AnchorDeck PSU HT 50 mil." These are different products; the template must select the correct one by system.

**T&C count:** Mazzeo and other proposals that include the full T&C show 49 clauses. Thompson's proposal is notably shorter (8 pages vs 14-17 pages) and appears to have an abbreviated T&C — the T&C section is not fully visible in Thompson. This may be a deliberate shorter-form proposal or a PDF rendering issue. All other proposals with visible T&C sections are 49 clauses.

---

## Template Requirements Checklist

### Data model
- [ ] `client` object: name, address_line1, address_line2, entity_name (if different)
- [ ] `proposal` object: date, project_name, contractor_name, contractor_branch, contractor_date
- [ ] `line_items[]` array: ordered list of items, each with all variables from section 4
- [ ] `payment_schedule` object: variant enum + custom milestones if non-standard
- [ ] `hvhz_flag` boolean at proposal level (drives Additional Info block variant)

### Scope blocks (one composable block per system type)
- [ ] METAL scope block (variables: panel_gauge, panel_finish, panel_material, underlayment_product)
- [ ] COASTAL_METAL scope block (variables: adds aluminum spec, Kynar coating, Metal Alliance warranty)
- [ ] TILE scope block (variables: tile_brand, tile_type, tile_adhesive, underlayment_product)
- [ ] COASTAL_TILE scope block (upgrades metals to aluminum)
- [ ] PREMIUM_TILE scope block (variables: regional_name, clay upgrade description)
- [ ] SHINGLE scope block (variables: shingle_brand, underlayment_product)
- [ ] COASTAL_SHINGLE scope block (variables: double-layer underlayment, Pro shingles, aluminum metals, SWR note)
- [ ] FLAT_POLYGLASS scope block (variables: deck_type conditional substeps, insulation_optional)
- [ ] FLAT_3PLY scope block (Miami-Dade/HVHZ variant; tin tags; nailable base)
- [ ] GUTTER scope block (variables: gutter_size, gutter_lf, downspout_count, downspout_lf)
- [ ] STUCCO scope block (variables: stucco repair description, PB70 waterproofing areas)
- [ ] HURRICANE_STRAPS scope block (variables: strap_count)
- [ ] COPPER scope block (variables: copper_lf, application description)
- [ ] DISCOUNT line item (variables: discount_label, discount_amount)
- [ ] OTHER/CUSTOM line item (free-text body)

### Additional Information block
- [ ] 7 static bullets with HVHZ conditional on bullet 1
- [ ] Financing phone number: RenewPace 1-888-906-3560 (static)

### WARRANTY block (per line item)
- [ ] Perkins Limited Warranty: "{perkins_warranty_years} year(s) upon final payment and signed Perkins Roofing Limited Warranty Certificate"
- [ ] Material warranty line: system-specific manufacturer and product name + years
- [ ] Metal Alliance warranty lines: added for COASTAL metal items (substrate corrosion + kynar warranty)
- [ ] Maintenance inspection requirement line (always appended)
- [ ] Commercial warranty add-on note (flat roofs only)

### PERKINS BONUS VALUES block (per line item)
- [ ] Items 1-10 are standard; item 11 (SWR) conditional on COASTAL package
- [ ] Dollar values in items 1-2 scale with warranty years ($300/yr × years for item 1, $350/yr × years for item 2)
- [ ] INCLUDED BONUS VALUE computed total
- [ ] ADDITIONAL BONUS VALUE line for COASTAL upgrade items (different heading)

### Pricing summary
- [ ] Subtotal = sum of all positive and negative item prices
- [ ] Tax = $0.00 (always)
- [ ] Total = Subtotal

### Payment terms
- [ ] Standard 30/30/30/balance block (4 items + lumber surcharge note)
- [ ] Custom payment block (ordered list of pct + milestone description)
- [ ] "Late fees apply after 30 days overdue" on final balance item

### Statutory / boilerplate blocks
- [ ] BUILDERS RISK INSURANCE (static)
- [ ] FLORIDA HOMEOWNERS' CONSTRUCTION RECOVERY FUND (static; CILB address hardcoded)
- [ ] HB 939 clause (static)
- [ ] WINDSTORM INSURANCE roof-age table (static)
- [ ] CONTRACT PROVISIONS clauses 1-49 (fully static; rendered once per proposal)
- [ ] Note: "Perkins Roofing will not enter contract or engagement in state of emergency work within 10 days of execution of the contract unless entering into a verbal, cash deal due to this new Florida law as of May 2nd, 2024."

### Lumber Schedule exhibit
- [ ] Static exhibit (identical in all 8 proposals; no per-job variables)
- [ ] Uses Miami branch header (575 NW 152nd St, Miami, FL 33169)
- [ ] Always appended as second-to-last page

### Document layout / branding
- [ ] Cover logo: Perkins Roofing Corp. house icon + wordmark
- [ ] Page footer every page: "Perkins Roofing Jupiter · 15658 Alexander Run · Jupiter, FL 33478"
- [ ] Back page: blank + teal/navy "WWW.PERKINSROOFING.NET" banner
- [ ] Lumber Schedule header: blue "PERKINS ROOFING CORP. - MIAMI" banner image

### Quote validity
- [ ] Standard: "This estimate will be automatically withdrawn if not accepted within THIRTY (30) days."
- [ ] Metal override: "Metal Roofs must be accepted within fifteen (15) days" — add system-level flag

### Signature block (dual)
- [ ] Contractor block: name / branch / date
- [ ] "ACCEPTANCE OF PROPOSAL" acceptance text (static)
- [ ] Client block: signature line / printed name / date
