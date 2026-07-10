# Tim's Document Corpus → Build Requirements Brief (2026-07-10)

Synthesis of Tim's last-48h emails + 40 attachments (8 JOB SOLD packages, UPDATED
Material Prices.xlsx, New Google Estimates.xlsx) pulled via Jarvis O365 (jon@degenito.ai).
Detailed extractions (agent-verified against the PDFs/xlsx):
- `docs/superpowers/specs/tim-docs/proposals.md` — proposal template reverse-engineering (8 PDFs)
- `docs/superpowers/specs/tim-docs/invoices.md` — Knowify invoice/milestone anatomy (7 invoices + supplier quotes)
- `docs/superpowers/specs/tim-docs/details_orders_roofr.md` — permit details pages, Roofr fields, material order forms
- `/tmp/tim/dump_*.txt` — all xlsx tabs incl. threaded comments
Email verbatims: `/tmp/tim/tim_bodies.json`. Raw attachments: `/tmp/tim/tim_attachments/`.

## The full job pipeline (reverse-engineered)

Roofr measurement → estimate (calculator) → proposal (master template) → [e-sign/accept]
→ details page (permit spec sheet) → material order forms (per system, ABC Supply)
→ milestone invoices (Knowify today) → payments → QuickBooks.

We already have: measurement (Squares, area+pitch only), estimator (v2 in flight),
proposals/quotes scaffolding UI, portal accept tokens (hardening = Ez-Bids W4).

## 1. Material price book (task #12) — Tim's explicit ask ("plug this in on the back end")

Source of truth: `UPDATED Material Prices.xlsx` tab **ABC (42926)** (latest booked,
4/29/26; 9 dated ABC snapshots + Beacon tab = natural version history).
- Item schema: name, unit_price → w/Tax (7%) → w/Waste (+10%) → `squares_per_unit`
  coverage → derived price/sq. Unit-conversion notes live in threaded comments
  ("1 gal does 3 squares", "50 LF of tape per SQ", "Price per LF", "66' per roll").
- Needs: `PriceBookItem` (sku, unit, unit_coverage, current price, tax/waste rates,
  roof_system mapping so the quantity engine knows which items belong on which order
  form), versioned snapshots via the existing pricing-config flow, seed import of the
  42926 tab, **admin/estimates edit UI** ("edit material cost and update the full
  material price per square"), estimator material-side consumption reconciled with the
  existing lump `base_cost_lm` values (Tim's sheets derive base costs FROM items — see
  sloped workbook `Custom Tile Calc` tab).
- Blanks/#DIV0 rows in the sheet = not-stocked/no-booked-price → model as nullable, not 0.

## 2. Admin/estimates ↔ sheet formula alignment

Estimator v2 (day-based OH + flat profit; landing today) covers Tim's items 1–2.
Remaining alignment: material side driven by price book (above); per-branch OH day
rates (Jupiter tabs in both workbooks; Naples has NO data — ask Tim); sheet-comment
breakdowns. Google-sheet comments on the two calculator workbooks: none exist (verified
via xlsx export); the only comments are the 4 unit-conversion notes in the price book.

## 3. Proposal/contract generation (task #14)

One MASTER template + conditionals (verified across 8 PDFs — not per-system templates):
- Structure: header grid → numbered line items → pricing summary (Subtotal / 0% tax /
  TOTAL) → dual signature block → embedded 49-clause static T&C → static Lumber
  Schedule exhibit → back page.
- Package tiers: PERKINS PROTECTOR (7-yr) / COASTAL (corrosion, 12-yr) / PREMIUM
  Caribbean-Mediterranean (clay tile, double underlayment).
- 5 scope blocks (METAL, TILE, SHINGLE, FLAT_POLYGLASS, FLAT_3PLY_BUR) + ancillary
  (GUTTER, STUCCO, HURRICANE_STRAPS, COPPER, DISCOUNT-as-negative-line-item).
- Shared blocks: 7-bullet ADDITIONAL INFO (HVHZ conditional wording on bullet 1),
  WARRANTY, 10/11-item BONUS VALUES.
- Payment schedule: standard 30/30/30/balance verbatim block + `custom_milestones[]`
  override (Palmer financing = 15/15/30/30/balance).
- Rules engine bits: metal line item present → 15-day expiry, else 30 (T&C clause 48);
  lumber surcharge billed at dry-in; tax always $0 (FL roofing services exempt).
- Jon's addition (Requested-documents email): T&C **AI-FAQ cover page** — summary
  bullets + recommended AI prompts + attorney disclaimer; reuse Contract-FAQ engine.

## 4. Details page + measurements

- Details Page = **permit submission spec sheet** (~18 fields; job_value == invoice
  total; references Roofr diagram). Generate from estimate + measurement data.
- Roofr fields needed beyond our Solar-based Squares: eaves/valleys/hips/ridges/rakes/
  wall-flashing/step-flashing/transitions/parapet LF, per-facet areas, per-pitch table,
  waste table. NOT derivable from Google Solar → need Roofr PDF ingestion and/or a
  linear-measurements entry UI on the estimate.
- Material order quantity engine (per-system templates: metal/tile/shingle/flat) from
  measurements + price book coverage: e.g. rolls=ceil(sq/coverage), drip=ceil((eaves+
  rakes)/10), field tiles=ceil(sq×1.08), QuickCrete=ceil(HRR_LF/50). Manual inputs
  remain: plywood sheets, penetrations, tile color/brand pick, metal panels (separate
  subcontractor quote flow — SupplierQuote stub).

## 5. Invoicing + milestones + e-sign + QuickBooks (task #15) — Knowify replacement

Observed Knowify usage (invoices #413–#652, ~26/mo): sequential company-wide numbering;
ONE invoice per milestone draw (all lines same completion %); lump-sum lines (qty=1);
discounts as negative lines at same %; net-0 terms (due=invoice date); NO tax; NO
payment instructions/links (gap to close); "Friends of Perkins" referral page appended
to every PDF (→ per-tenant configurable marketing appendix).
- Entities: Invoice, MilestoneSchedule (from proposal payment block), Payment
  (check/ACH/card/cash + reference), Credit/Discount, JobDocuments (ACC/HOA approval as
  job attribute with ref#, status, final-inspection flag).
- Numbering: continue from Knowify sequence (#653+) for Perkins.
- QuickBooks: one QB Invoice per draw, QB Customer:Job sub-customers, payments linked
  to bank deposits. Jon has a takeover Knowify account — API suck-down feasible for
  history import.
- E-sign: proposal acceptance + change orders. MUST align with Ez-Bids W4 (bearer-token
  hardening: single-use, TTL, host+proposal binding, email-scanner-safe, session-vs-
  acceptance separation) — the e-sign flow IS the W4 surface, extended to signature
  capture + executed-document storage. Legal review flagged in W4 already covers this.
- DISTINCT from Ez-Bids W5: W5 = platform→tenant SaaS billing (Stripe). This lane =
  tenant→homeowner job billing. Shared patterns (immutable ledger, idempotent webhooks,
  snapshotting) should be reused, not shared tables.

## 6. Marketing geo pricing (context, not build-now)

`New Google Estimates.xlsx` = per-city Google Ads reach/CPC/spend + $200K+ household
share + 3,000ft²-home counts + premium re-roof TAM (22-yr insurer-driven cycle);
methodology notes included. Supports the $300/appointment paid-leads service Tim wants
("100%", preferred-clientele filters by area/roof type/home value). Jon runs ads —
platform work here is later-scope (lead routing/attribution), not part of this plan's
build waves unless Jon says so.

## Business context (do not encode as scope)

- Estimating-tool payment may wait "a couple months for profits to catch up" unless
  Chris goes 50/50 (Tim believes he will; closing on house). Jon floated: defer mobile /
  defer proposals / stagger 3rd payment / do it all. → Plan must be WAVE-STAGED so any
  payment decision maps to a clean cut line.
- Tim: "a back end form will need to be filled out to algorithmically create the
  calculator the way we want" — admin-first design confirmed.
- Part 1.mp4 walkthrough on Tim's Drive (id 1dy53TN8pbl-CKZLXtwAwmQjKxskBNj9E) — worth
  transcribing (cerberus Whisper, dev-only STT) before finalizing admin UI details.

## Alignment constraints (existing approved plans — do NOT relitigate)

- Ez-Bids 8-wave plan APPROVED: W4 token/e-sign hardening owns acceptance security;
  W5 owns SaaS billing patterns; W0–W2 in flight. New lanes slot AFTER/BESIDE, using
  W4's token model for e-sign and W5's ledger patterns for job billing.
- Estimator v2 (task #10) lands today — day-based OH + flat profit + goldens.
- Exhibit B pricing config = zone-scoped values verified against Tim's sheets
  (docs/superpowers/specs/2026-07-10-pricing-workbooks-analysis.md); OI-7 (HVHZ
  commission 15%) + OI-8 (pm_incentive) have sheet evidence, await Tim sign-off.
- 8 golden packages → end-to-end validation fixtures for estimator/proposal/invoice.
