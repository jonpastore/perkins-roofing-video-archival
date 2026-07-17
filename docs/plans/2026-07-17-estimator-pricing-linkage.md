# Estimator ⇄ material pricing linkage — investigation + plan (2026-07-17)

Status: **prep — wiring gated on Tim's Zoom recording/transcript** (Jon uploading).
This captures everything learned from the live Google Sheets + golden proposals so the
video work can go straight to wiring.

## 1. The sheets (found in Drive, read 2026-07-17)

| Sheet | ID | Tabs |
|---|---|---|
| Copy of ***Sloped Roof Price Calculator | `1ptSxJYPumUKtxJk66JgbZ8tljVJMbyCAyaSyz_BCwg0` | Tim (HVHZ), FBC (Palm/Lee/St. Lucie), Custom Tile Calc, Marco, Josh, OH Metrics, Jupiter |
| Copy of **Low-Slope Roof Price Calculator | `1SGLYoOIU13nILqGxJCIxuVZ8A2I_BTEjJ03PUuuRteo` | Tim, Josh, Marco, Overhead Metrics, Jupiter |

**⚠ The comment threads Jon described are NOT on these copies** — `includeComments`
returned zero comment anchors on both. They're presumably on Tim's ORIGINALS (not shared
with jpastore79@gmail.com). Ask Tim to share the originals (or the Zoom covers it).
The local xlsx (`/tmp/perkins_mail/UPDATED Material Prices.xlsx`) has only 4 trivial
embedded comments ("1 gal does 3 squares", "50 LF of tape per SQ", "Price per LF",
"66' per roll").

## 2. The linkage IS in the sheets — base-cost breakdown sections

Each roof system's "BASE COST" cell decomposes into L (labor) + M (materials) components,
and the M components NAME price-book materials. E.g. 13" Tile HVHZ $780/sq:

| Component | $/sq | Price-book item |
|---|---|---|
| L (Tear-Off) | 75 | — labor |
| L (Dry-in and TU Plus) | 100 | — labor |
| L +MTS add (L25/OH25) | 50 | — labor |
| L (Tile Install, inc. foam) | 160 | — labor |
| Hauling | 65 | — |
| M (Dry-in, TU Plus 80mil + Metals) | 125 | **TU Plus (80 mil)** ≈ $67/sq materials |
| M (+MTS incl. accessories) | 60 | (MTS = secondary water barrier) |
| M (Standard Tiles… Eagle) | 215 | Eagle tiles (not yet in price book) |
| Tile Delivery | 40 | — |

Same shape for barrel tile (Santa Fe/Alhambra $500 M), 3-tab/dimensional shingle
(M dry-in+shingles $220/$245 → **Landmark Pro** ≈ $154/sq ABC), standing-seam metal
(M panels $550, **VersaShield** $115), and the low-slope systems (SAV/SAP 2-ply $475 =
L50+L130+H35+M260; TPO $485; coating systems INC-OH+P: PB Acrylic $375, Premium Coat
$550, Silicone 1-coat $445 / 2-coat $515, Stockmeier $595).

**Design sketch (post-video):** a `roof_system_recipes` config — per system, a list of
`{price_book_item_id | labor_key, qty_per_sq | flat}` — so the estimate's "pricing
option" per input picks a recipe, materials reprice live from the price book
(price/sq = price × 1.07 × 1.10 ÷ coverage), and labor/OH stay config rates. The
`price_book_items.roof_system_ids` column (currently all empty) is the seam.
Upgrade adds map the same way (TUP +$55, Flintlastic SA Cap +$105, Polyfresko +$80,
SAV Plus 3-ply +$175, XFR secondary barrier +$75, WinterGuard +$140).

## 3. Packages — the full menu already exists, the quote flow hides it

`core/perkins_packages.py` has ALL tiers (from the golden JOB SOLD proposals):
- **Shingle**: PROTECTOR / PREFERRED / PREMIUM / **COASTAL**
- **Tile**: PROTECTOR / PREFERRED / **PREMIUM_CARIBBEAN / PREMIUM_MEDITERRANEAN /
  PREMIUM_MODERN** / **COASTAL**
- **Flat**: PROTECTOR / PREFERRED / PREMIUM / PROLONG (standalone) / RESTORE
- **Metal**: PROTECTOR / PREFERRED / PREMIUM / **COASTAL / HVHZ_COASTAL** /
  CARIBBEAN (standalone) / COASTAL_CARIBBEAN

The gap: the estimate flow (`QuoteRequest.selected_tier`, Quoting builder, snapshot
tiers) only exposes generic good/better/best. `core/proposal.py capture_selection`
already accepts arbitrary tier keys from the snapshot, so the fix is upstream only:
build snapshot tiers from the per-system package menu (all premiums + coastal), not
3 hard-coded tiers. **Exact tier→estimate mapping: confirm in the Zoom.**

## 4. Demo / tear-off clarity (sheet facts to encode)

Today the UI has `demo: bool` + layers. The sheets price demo by WHAT is being removed,
which is independent of the NEW roof type:
- Tile demo: +$40/sq OH (HVHZ) / +$30 (FBC); tile roof dumpster $300 (>15 sq);
  "ADD $20-25 L for tile demo" on other systems' labor rows
- Metal demo: +$60/sq OH (HVHZ) / +$45 (FBC)
- Tear-off extras (low-slope): additional hauling $20 + labor $20 + OH $35 per roof or
  per insulation layer ("$75 extra per layer")
- OH Metrics tabs price crews for Tile Removal vs Tile Demo/Dry-In vs Shingle vs Metal
  separately, per branch and crew size.

→ Plan: replace `demo: bool` with `existing_roof` (tile / shingle / metal / flat /
none=new-construction) + layers; engine picks the right demo adds from existing_roof,
not the new roof_type. **Confirm exact rates/semantics in the Zoom.**

## 5. Branches (prep only — B8/B9/B10 in BACKLOG.md)

The sheets themselves are branch-structured: Tim (HVHZ=Miami), FBC, Jupiter, Marco,
Josh tabs with separate OH bases (9/12/15-man Miami vs 4/7/10-man Jupiter). Confirms:
branches are first-class (not the 3 hard-coded config rows), each with own crew/OH
metrics — and per Jon, Tim has 4 companies / 4 Knowify / 4 QuickBooks subscriptions
that map to branches.

## 6. Zoom recording TODO (when Jon uploads)

Extract from video+transcript: (a) each price cell's comment/explanation and its
material list, (b) how estimate inputs choose "pricing options", (c) package tier
mapping to estimates, (d) demo/tear-off semantics, (e) anything on branch handling.
Frames: capture screenshots where Tim points at cells/comments.
