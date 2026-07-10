# Perkins Roofing — Invoice & Payment System Reverse-Engineering

## 1. Knowify Invoice Anatomy

### Header / Numbering
- Invoice numbers are sequential integers: #413 (Oct 2025), #573 (Mar 2026), #601 (May 2026), #608 (May 2026), #611 (May 2026), #639 (Jun 2026), #652 (Jul 2026). The span from #413 to #652 over ~9 months suggests roughly 26 invoices/month across the business (numbering is company-wide across all customers, not per-job).
- Format: `Invoice #NNN` — plain integer, no prefix codes, no year/month encoding.

### Bill-To / Job Reference
- `BILL TO` block: customer name + full mailing address (street, city, state, zip).
- `JOB` field: free-text job name, typically `"[LastName] [Roof Type]"` (e.g. "Malooley Tile Re-Roof", "Thompson Metal Re-Roof").
- No explicit job/contract number appears on the invoice face. The job name is the only cross-reference to the underlying contract.

### Header Date Block (3-column table)
| INVOICE DATE | PLEASE PAY | DUE DATE |
|---|---|---|
| date | **bold amount** | date |

- Invoice date = due date in every observed example (net-0 terms — payment expected same day invoice is issued).
- "PLEASE PAY" is the bolded current milestone amount, not the contract total.
- No explicit payment terms text (e.g. "Net 30") appears; no late fee language on any invoice.

### Line Items
- Column headers: `Description | Hrs/Qty | Rate/Price | Subtotal`
- Qty is always `1` — line items represent lump-sum contract packages, not unit-priced quantities.
- Each line item has two sub-rows:
  1. The service description (Perkins product name + scope)
  2. A completion percentage (e.g. "30% completed") as a sub-label under the description
- The `Rate/Price` column holds the **dollar amount due for this milestone draw** on that particular scope — it is NOT the total contract price for that scope. (See section 2 for the math.)
- Discounts appear as separate negative-amount line items (e.g. "Discount / 30% completed / ($300.00)").
- Optional add-ons are labeled `(OPTIONAL)` in the description (seen in #573, #639).

### Footer Totals
- `Subtotal` = sum of all lines
- `Taxes` = $0.00 on all observed invoices (roofing services are tax-exempt in Florida)
- `Credit` = $0.00 on all observed invoices (no credits applied in these samples)
- `TOTAL` = equals subtotal

### Payment Instructions / Methods
- No payment instructions, ACH routing, card link, check payable-to, or QR code appear on any invoice page 1.
- Page 2 of each invoice is a "Friends of Perkins Roofing" vendor referral sheet — this is the only other content Knowify appends. No payment portal link, no remittance stub.
- Payment methods are handled outside the invoice (presumably verbally or via a separate portal not reflected here).

### Comments / Special Instructions
- Field is present on every invoice but blank in all samples.

---

## 2. Cross-Invoice Comparison — Milestone Patterns

### The Milestone Model
Perkins does **percentage-of-completion billing per scope line**, not named milestone stages (not "deposit / dry-in / completion" labels). Each invoice represents one draw at a stated completion percentage. All line items on a given invoice carry the **same percentage** — this is a single-milestone-draw invoice, not a multi-stage document.

| Invoice | Customer | Total Drawn This Invoice | % Stated | Implied Contract Value |
|---|---|---|---|---|
| #413 | David Meharg | $7,911.00 | 30% | ~$26,370 |
| #573 | Joseph Mazzeo | $13,650.53 | 30% | ~$45,502 |
| #601 | Fred Thompson | $15,180.56 | 30% | ~$50,602 |
| #608 | Melissa Butterworth | $12,758.85 | 30% | ~$42,530 |
| #611 | Jim Malooley | $38,179.01 | 30% | ~$127,263 |
| #639 | Glenn Allen | $9,882.96 | 30% | ~$32,943 |
| #652 | Justin Palmer | $6,868.50 | 15% | ~$45,790 |

**Key finding:** Six of seven invoices are exactly at the 30% milestone. Invoice #652 (Palmer) is at 15% — a deposit or first draw. This strongly implies a standard draw schedule where the first invoice is 15% and subsequent draws are 30% each, though we only have one data point for the 15% tranche.

**Inferred standard draw schedule (hypothesis based on evidence):**
- Draw 1: 15% (deposit / contract signing or permit issuance)
- Draw 2: 30% (work commencement / material delivery / tear-off)
- Draw 3: 30% (mid-point / dry-in or substantial completion)
- Draw 4: 25% (completion / final inspection)

This totals 100%. The labels on the invoices only say "X% completed" — they don't name the phase (no "dry-in", "tear-off", etc. in any observed invoice). The phase label exists in the underlying Knowify contract/proposal but is stripped to just the percentage on the invoice output.

### Multi-Scope Jobs
Multi-scope jobs (multiple roof sections or add-on packages) have one line item per scope, each independently priced, but all drawn at the same percentage simultaneously. The invoice aggregates all scopes into a single payment request. Examples:
- #608 (Butterworth): 4 scopes (flat re-roof x2, tile re-roof, painting) all at 30%
- #611 (Malooley): 3 scopes (tile re-roof, premium tile upgrade, coastal upgrade) all at 30%
- #601 (Thompson): 5 lines including a discount, all at 30%

### Perkins Product Lines Observed
- **PERKINS PROTECTOR** — base warranty package (appears on nearly every job, always the largest line)
- **PERKINS COASTAL / PERKINS COASTAL UPGRADE** — coastal/wind resistance add-on
- **PERKINS PREMIUM** — premium tile styles (Mediterranean, Caribbean)
- Non-branded scopes also appear (e.g. "Copper Metal Install", "Re-Paint Guest House & Stucco Repairs", "New Seamless Aluminum Gutter and Downspout System", "Install Perimeter Hurricane Straps")

### Taxes
$0.00 taxes on all seven invoices. Florida does not tax roofing labor; materials purchased by the contractor are taxed at the supply house level (see ABC Supply quotes which include sales tax). No tax is passed through on the customer invoice.

---

## 3. Knowify Features in Use (Evidence Only)

From these documents, Knowify is being used for:
- Invoice generation with logo/branding
- Job-linked billing (job name on invoice)
- Progress billing by percentage (line-item sub-label "X% completed")
- Multi-line invoices per job scope
- Discount line items (negative amounts)
- Sequential invoice numbering (company-wide)
- PDF generation with 2-page layout (invoice + referral sheet appended)

Knowify features **not evidenced** in these documents (may or may not be in use):
- Payment processing / online pay links
- Named milestone stages (Knowify supports these but they don't appear in output)
- Purchase orders or subcontractor management
- Scheduling or time tracking
- Customer portal
- QuickBooks sync (may be active but not visible in invoice PDFs)
- Retainage tracking
- Lien waivers

---

## 4. Supplier Quotes

### Quote 2006095674 — ABC Supply Co. Inc. (Stuart, FL)
- **Supplier:** ABC Supply Co. Inc., 3680 SE Dixie Hwy, Stuart, FL 34997
- **Account:** Perkins Roofing Corp account #2086211 0002, Branch 499
- **Bill to / Ship to:** Perkins Roofing Corp Miami (575 NW 152nd St) — shop delivery (CPU = customer pickup noted)
- **Date:** 01/28/2026, close date 02/27/2026 (30-day validity)
- **Items:** Solatube skylights for HVHZ (High Velocity Hurricane Zone) — 160ISN and 290ISN models with night light kits, plus extension tubes
  - Solatube 160ISN HVHZ w/Ntlt 124510: $596.48
  - Solatube 10" Spectralight Infinity Extension Tube: $77.10
  - Solatube 290ISN HVHZ w/Ntlt 124740: $831.02
  - Solatube 14" Extension Tube: $96.16
  - Subtotal: $1,600.76 + $104.05 sales tax = **$1,704.81**
- **Relevance to invoices:** Skylights are a materials cost Perkins buys at the supply house (with tax) and passes through to customer invoices (without tax) as a scope line. This is the material procurement side of a scope like "Solatube Install." The ABC Supply relationship is Perkins' primary roofing materials supplier.
- **Structure:** Standard supply house quote format — item number, SKU, UOM (EA/PC), price/UOM, extended amount. Includes sales tax (supplier taxes the contractor; contractor does not charge customer tax).

### Quote RA2037661X1 — ABC Supply Co. Inc. Tapered Solutions (for 404 South M St, Lake Worth Beach)
- **Supplier:** ABC Supply Co. Inc. (same supplier, different quote type — Tapered Solutions division)
- **Project Manager:** Raymond Collazo, raymond.collazo@abcsupply.com
- **Property:** 404 South M St, Lake Worth Beach, FL (same address as Invoice #413, David Meharg)
- **Date:** 09/23/2025 — this is a pre-job material quote for the Meharg flat roof
- **Items:** Tapered insulation system design for a flat/low-slope roof
  - Non-taper area: 12.84 squares
  - Cricket system: 20 PSI ISO 1/2Q panels (4x4), 0.24 sq, slope 1/2"/ft
  - Taper fill: ISO 20 Base 3 panels
  - Total applied: 13.08 sq; total material: 13.60 sq
  - Min R-value: 17.10
  - **Price: $2,222.34** (excludes tax, freight, fuel surcharge)
  - Valid through 11/18/2025
- **Relevance:** This is an engineered insulation/tapered system quote for the same Meharg job that became Invoice #413. The quote was from Sept 2025; the invoice was dated Oct 2025. This is how material costs feed into job estimates — ABC designs the tapered system and quotes the material; Perkins uses this to build the proposal price. The quote includes a roof layout diagram.
- **Note on disclaimer:** ABC Supply explicitly states they are a "supplier of materials only" and do not assume responsibility for design/engineering errors. Architect/contractor must verify all specs.

---

## 5. Competitor Proposal — Pinewood Construction, Inc.

- **Company:** Pinewood Construction, Inc., 1065 Sterling Pine Place, Loxahatchee, FL 33470. LIC# CGC023773 / LIC# CCC1335386. Owner: Michael Cirillo.
- **Customer:** Joseph Mazzeo, 3549 Moon Bay Cir, Wellington FL 33414 — the same customer as Perkins Invoice #573.
- **Estimate #6594, dated 02/20/2026** — this is a competing bid Perkins apparently obtained for comparison.
- **Scope:** New tile roof — Westlake Barcelona 900 tile (handwritten on the form). Remove existing tile, renail decking, install self-adhesive TU Max underlayment (1-ply), 26-gauge drip edge, lead plumbing stack flashing, goose neck vent caps, poly foam tile installation, hip/ridge metal channel.
- **Price: $37,800.00 flat** (includes labor, material, permit fees; excludes HOA/POA, wood beyond 2 sheets allowance at $100/sheet, fascia at $25/linear foot)
- **Draw Schedule (Pinewood's):**
  - $3,000 upon signing proposal
  - $19,000 upon work commencing
  - $4,000 when underlayment is complete
  - $1,800 upon completion
  - *Note: the "$10,000 when tile has been delivered" line also appears — these add to $37,800 total across 5 draws*
  - Actual draw schedule: Sign $3K / Commence $19K / Underlayment $4K / Tile delivered $10K / Completion $1.8K
- **Warranty:** Labor warranty against leaks for 10 years (handwritten correction — original said 7, corrected to 10 with note "this was an error, was supposed to be 10 years per owner"). Manufacturer warranty also applies.
- **Exclusions:** HOA/POA costs not included; engineering for roof mitigation if house >$300K value and permitted before 1/1/1988 not included; gutter removal/resealing not included.
- **Validity:** 30 days.
- **Format:** Single-page estimate with scope-of-work narrative, signature lines for owner and customer, license numbers at bottom.

**Comparison to Perkins:**
- Pinewood uses named milestone draws (sign / commence / underlayment / tile delivered / completion) — Perkins uses percentage draws.
- Pinewood's format is a scanned paper estimate; Perkins uses Knowify-generated PDF.
- Pinewood's price for the same Mazzeo job was $37,800; Perkins billed $13,181.40 as a 30% draw — implying Perkins total contract was ~$43,938, roughly 16% higher than Pinewood. (The contracts may differ in scope — Perkins included optional gutters and applied a $600 discount.)
- Pinewood front-loads draws: the first two draws ($3K + $19K = $22K = 58% of contract) are due before the roof is even half done. Perkins' first draw at 30% is more balanced.
- Pinewood includes permit fees in the lump sum price; it is unclear whether Perkins' invoices include permits.

---

## 6. ACC Approval — 302 Ridge Road, Jupiter

- **Document type:** HOA Architectural Control Committee (ACC) approval letter.
- **HOA:** The Ridge at The Bluffs Homeowners Association, Inc., managed by Campbell Property Management, 215 Cape Point Circle, Jupiter FL 33477; phone (561) 744-3009.
- **Homeowner:** Dolores Person, 15 Penacook, Sundown NH 03873 (mailing address — likely a seasonal/second home).
- **Property:** 302 Ridge Road, Jupiter FL 33477. Account #: RID42339.
- **Reference number:** XN35540770 — this is the HOA's internal tracking number for the approval.
- **Date:** February 04, 2026.
- **Approval status:** "APPROVED PENDING INSPECTION" — work may proceed but a final HOA inspection is required upon completion.
- **Approved scope:** "Gutters, Asphalt Roof and Skylights as outlined in application."
- **Homeowner obligations per approval:** Obtain all permits, comply with building codes, restrict construction access to the homeowner's property only (no common-area access), follow all application stipulations.
- **Fields that matter for our system:**
  - HOA/ACC approval reference number (XN35540770)
  - Issuing HOA name and management company
  - Approval date
  - Approved scope description
  - Approval status (Approved / Approved Pending Inspection / Denied)
  - Permit responsibility clause (homeowner, not contractor)
  - Final inspection requirement flag

---

## 7. Invoicing System Requirements Checklist

### Entities

**Invoice**
- invoice_id (internal), invoice_number (sequential integer, company-wide), tenant_id
- invoice_date, due_date (default = invoice_date for net-0)
- status: draft | sent | viewed | partially_paid | paid | voided
- job_id (FK), customer_id (FK)
- subtotal, tax_amount (always 0 for roofing services in FL), credit_amount, total
- comments/special_instructions (text, nullable)
- pdf_url (generated PDF storage)
- quickbooks_invoice_id (for QB sync), quickbooks_synced_at

**InvoiceLine**
- invoice_line_id, invoice_id (FK)
- line_type: scope | discount | addon | tax | credit
- description (e.g. "PERKINS PROTECTOR - Tile Re-Roof")
- scope_id (FK to job scope/package, nullable for discounts)
- milestone_pct (decimal, e.g. 0.30 — the % draw being billed)
- quantity (always 1 in current practice)
- unit_price (dollar amount = contract_value_for_scope * milestone_pct)
- subtotal (= quantity * unit_price)
- sort_order

**MilestoneSchedule**
- schedule_id, job_id (FK), template_id (FK, nullable)
- milestones: ordered list of {sequence, name, pct, trigger_event}
  - Standard Perkins template: Draw 1 (15%, signing/deposit), Draw 2 (30%, work start), Draw 3 (30%, mid/dry-in), Draw 4 (25%, completion)

**MilestoneDraw** (one record per draw per job)
- draw_id, job_id (FK), schedule_id (FK), sequence_number
- milestone_name (e.g. "Work Commencement"), pct_due (decimal)
- status: pending | invoiced | paid
- invoice_id (FK, set when invoice is created for this draw)
- planned_date, actual_date

**Payment**
- payment_id, invoice_id (FK), tenant_id
- payment_date, amount
- method: check | ach | card | cash | other
- reference (check number, ACH trace, card last-4, etc.)
- notes
- quickbooks_payment_id, quickbooks_synced_at

**Credit**
- credit_id, customer_id (FK), job_id (FK, nullable)
- amount, reason, applied_to_invoice_id (FK, nullable)
- created_at

### Numbering
- Invoice numbers are sequential integers, company-wide (not per-tenant in current single-company operation, but must be per-tenant in multi-tenant platform).
- Starting sequence should be configurable (Tim is at ~652 in Knowify; migration must initialize counter above current max to avoid collision).
- Format: integer only, no prefix. Expose as `#NNN` in UI.

### States
Invoice: `draft → sent → (partially_paid | paid) | voided`
MilestoneDraw: `pending → invoiced → paid`
Job (billing angle): `not_started → deposit_invoiced → in_progress → final_invoiced → closed`

### QuickBooks-Sync-Relevant Fields
- Customer (maps to QB Customer): name, billing address, email
- Invoice: invoice_number (QB Invoice Number), invoice_date, due_date, line items, subtotal, tax, total
- InvoiceLine: description, quantity, unit_price, amount (QB Item or Service mapping)
- Payment: date, amount, payment_method, deposit_to_account
- Job: maps to QB Customer:Job (sub-customer) or Class
- Discount: maps to QB discount line item
- Sync fields: `qb_entity_id`, `qb_synced_at`, `qb_sync_status` (synced | pending | error), `qb_error_message`
- QB does not have a native "milestone draw" concept — each draw is a separate QB Invoice under the Customer:Job. Sync must create one QB Invoice per Perkins Invoice, not one per job.

### Additional Requirements Derived from Documents
- **Multi-scope per invoice:** A single invoice can have N scope lines, each with its own dollar amount but all at the same milestone pct.
- **Optional line items:** Must support flagging a line as "(OPTIONAL)" — used for add-ons the customer accepted.
- **Discount line items:** Negative-amount lines must be supported as first-class line type (not a coupon field).
- **"Friends of Perkins Roofing" appendix page:** Knowify appends a referral sheet to every PDF. Our system needs a configurable PDF footer/append feature to replicate this marketing insert per tenant.
- **HOA/ACC tracking:** Jobs in HOA communities need an approval-reference field (reference number, HOA name, management company, approval date, scope approved, status, final-inspection-required flag). This is a job attribute, not an invoice attribute.
- **No payment instructions on invoice:** Current practice has no payment link on the PDF. Future system should add a configurable payment link or ACH instructions block (this is a gap vs. best practice).
- **Tax:** Always $0.00 for roofing services in Florida. System must support $0 tax but keep the field for future use or out-of-state tenants.
- **Permit cost tracking:** Pinewood includes permit fees in lump-sum price; unclear if Perkins does. System should support a permit-fee line item or job-level permit cost field.

---

## Summary — 15-Line Key Findings

1. Perkins invoices via Knowify with sequential integer invoice numbers (#413–#652 over ~9 months, ~26/month pace).
2. Each invoice represents a single milestone draw; all scope lines on one invoice carry the same completion percentage.
3. Six of seven sample invoices are at the 30% milestone; one (Palmer #652) is at 15%, consistent with a first/deposit draw.
4. Inferred standard draw schedule: 15% deposit, 30% work start, 30% mid-job, 25% completion (totals 100%); labels are only percentages on the invoice, not named stages.
5. Line items use Qty=1 / lump-sum pricing per scope package; the Rate/Price is the draw amount (not the total contract price for that scope).
6. No taxes on any invoice (Florida roofing services are tax-exempt at the customer level; tax is paid by Perkins to suppliers like ABC Supply).
7. No payment instructions, ACH info, or online pay link appear on any Knowify invoice PDF — this is a current gap to close.
8. Invoice due date equals invoice date on all samples (net-0 terms); no late fee language observed.
9. Discounts appear as separate negative line items at the same milestone percentage as other lines.
10. ABC Supply (Stuart/Miami) is Perkins' primary materials supplier; quotes flow from ABC Supply into job cost estimates and then into customer invoice pricing.
11. The Pinewood competitor proposal uses named draw stages (sign/commence/underlayment/tile-delivered/completion) with heavy front-loading (~58% due before mid-job) vs. Perkins' percentage-based balanced draws.
12. HOA/ACC approvals are a distinct pre-work document with their own reference number, approval status, and final-inspection requirement — must be tracked as a job attribute.
13. The Knowify PDF appends a "Friends of Perkins Roofing" referral page to every invoice — our system needs a configurable marketing-page appendix feature.
14. Payment methods are not evidenced in these PDFs; the system must support check, ACH, card, and cash with reference capture for QuickBooks reconciliation.
15. QuickBooks sync requires one QB Invoice per Perkins Invoice (per draw), mapped to QB Customer:Job sub-customers, with separate payment records — not a single per-job aggregate.
