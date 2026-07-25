# CONTINUATION 2026-07-25 — estimator now runs Tim's own method (93% within a day)

Deployed image **`platform:0b291ef`** (2026-07-25 05:2x UTC). Prod pricing configs at **v13** on
all three branches.

> **Correction (2026-07-25).** An earlier version of this line said the commits after `b390ba6`
> were "docs/config-only". They were not — `b1a4277` changed `core/estimator.py` and
> `api/routes/estimator.py`. Config v13 already carried `pitch_day_adder`, so for ~5h prod ran the
> pre-pitch model while the config that feeds it sat live and ignored: mistake §7.1 again, with
> config ahead of code instead of behind it. **Verified fixed in prod** — see §1.

### Prod smoke, 2026-07-25 (918 Mil Creek geometry through the live `/estimator/quote`)

| `pitch_primary` | tile days | project total |
|---|--:|--:|
| 5/12 | 5.0 | $41,875.00 |
| **6/12** | **5.5** | **$42,247.50** |
| omitted | 5.0 | $41,875.00 |

+$372.50 = 0.5 × $745/day, and omitting pitch adds nothing (no silent default). The $41,875 in
Tim's email is now confirmed against the deployed endpoint, not just `tim_quote_breakdown.py`.

---

## 1. THE HEADLINE — pricing now reproduces Tim's method

Tim prices overhead by **time**, and time tracks **complexity and steepness**, not area. His words
(2026-07-17 Zoom transcript, `~/Documents/Zoom/2026-07-17 14.24.24 .../transcript.txt`):

- [09:46] *"the way to **properly** generate the overhead is based on how long the job is going to
  take … **this is just a guide** than it is a rule"* — the per-square OH table is the guide.
- [10:12] *"two houses that are both **30 squares** but one got towers … this one is going to take
  **two days** and the one with all the crazy shit going on could take **five or six days**"*.

So days now come from RoofR geometry, per series, coefficients in
`config["daily_overhead_day_model"]["geometry_model"]`:

```
tile install = 0.55 + 0.032·squares + 0.0135·hips + 0.0130·ridges
                    + 0.0107·rakes  + 0.0007·valleys + 0.0014·wall_flash
demo         = 1.11 + 0.0060·eaves  + 0.0010·rakes
shingle      = 0.87 + 0.0066·squares + 0.0062·ridges + 0.0016·hips + 0.0039·wall_flash
metal        = 0.85 + 0.0131·hips + 0.0085·ridges + 0.0130·rakes + 0.0052·valleys + 0.0042·squares
+ 0.5 install days when pitch >= 6/12   (config: pitch_day_adder)
```

### Measured against Tim's own day figures (29 of 30 homes)

| Model stage | within 0.5d | within 1.0d | mean miss | mean OH vs Tim |
|---|--:|--:|--:|--:|
| squares only (start of day) | 48% | 69% | 0.98 d | +$21 |
| geometry (cut LFs) | 55% | 83% | 0.71 d | −$2 |
| + eaves on demo | 66% | 86% | 0.59 d | −$87 |
| **+ steep-roof rule (now)** | **66%** | **93%** | **0.53 d** | **+$3** |

Reproduce: `DB_URL=… PYTHONPATH=. .venv/bin/python scripts/tim_quote_breakdown.py [--csv out.csv]`
Refit: `scripts/fit_days_from_roofr.py` (leave-one-out, non-negative).

### Three findings that shaped it

1. **Non-negative coefficients matter.** Plain OLS returned negatives (demo valleys −0.005, "more
   valleys ⇒ fewer days") — noise that under-prices complex roofs. `fit_nonneg` (backward
   elimination, no scipy) forces monotonicity AND improved prediction (shingle 0.36 → 0.55).
2. **Eaves drive tear-off.** Adding eaves lifts demo 0.363 → 0.662 LOO. Pitch as a *linear* term
   was REJECTED — it drops tile 0.825 → 0.736.
3. **Pitch is a step, not a slope.** Residual vs pitch: −0.29 d at ≤4/12, +0.03 at 5/12, **+0.64 at
   ≥6/12**. As a fitted 7th regressor it made every install series worse (only 7 steep homes); as a
   threshold rule it took the library 86% → 93%. Tim's own 7/12 sheet comment breaks out
   `OH = $90/sq`, independently confirming steep roofs carry real extra overhead.
   ⚠️ **Zero homes in the sample are ≥7/12** — no calibration in the band his sheet says jumps.

### Jon's padding hypothesis — tested and rejected
Overall bias is only **−0.10 days** (11 under-calls vs 9 over). Blanket round-up made it worse
(66% → 59% within half a day). Do not add a global pad; the asymmetry is pitch, not padding.

---

## 2. THE MONEY BUG — the published catalog under-quotes Tim on 30/30 homes

`core/perkins_packages.py`'s flat per-system `$/sq` came out **below Tim's own cost-up build on
every single home**: mean **−$72/sq**, worst **−$150/sq** (16.5 SQ shingle), ~$2,900 of margin on a
35 SQ tile roof. Barrel tile is the extreme: one `tile` entry at $1,100/sq covers 13" tile (base
$770) and barrel ($1,435) — below material+labour before any OH or profit.

**Shipped:** `core/proposal_gen.py` refuses a **tile** full price from the catalog
(`requires_engine_price()` → route maps ValueError to a **422** explaining why). Upgrade ADDERS
still price off the catalog, correctly — an upgrade IS a flat per-square material swap.
Shingle/metal remain catalog-priceable to avoid breaking the live endpoint, **but the data says
they need the same treatment** (−$57 and −$73/sq).

⛔ **Jon/Tim decision:** retire the flat catalog as a price and quote from the engine, or re-issue
it as a size-banded table. A flat $/sq cannot equal a cost-up build across sizes (engine tile runs
$1,420/sq at 10 SQ down to $1,129 at 100).

---

## 3. UNBLOCKED TODAY — Tim's cell comments are readable (7/17 item #9)

That item was blocked on *"comments live in Tim's ORIGINAL sheets — ask Tim to share originals"*.
**No ask needed:** the Drive API + existing DWD grant reads them.

```python
creds = service_account.Credentials.from_service_account_file(
    "/home/jon/.config/gcloud/perkins-deploy-sa.json",
    scopes=["https://www.googleapis.com/auth/drive.readonly"]).with_subject("tim@perkinsroofing.net")
AuthorizedSession(creds).get(f"https://www.googleapis.com/drive/v3/files/{SID}/comments",
    params={"fields":"comments(content,quotedFileContent,anchor,replies(content))","pageSize":100})
```

**77 comments** saved to `~/perkins-corpus/tim_sheet_comments.json` (sloped calculator; the
low-slope one has none). They contain the material↔price linkage the item wanted, e.g.

- `[$215]` → Eagle $135 / Crown $155 / Boral $160 / rake tiles $35 / eave closure $20 / mortar $5 /
  ridge metal $20
- `[$140 per Sq. to add MTS]` → **L $20 / M $67 / OH $32 / P $18** — the L/M/OH/P decomposition
- `[Add $200 for 7/12+]` → Demo L $70 / Tile L $70 / M $40 / **OH $90** / P $35
- `[$285]` → "$285 (busy, 16+ guys) / $210 huge job" — crew-size price variants

**Not** in the comments: PM incentive, commission, Verea field costs, crane/storeys, dumpster
boundary. Those genuinely need Tim.

**Next:** feed these into the price-book → aggregate-input-box linkage (7/17 item #9's actual
design) so Tim only maintains material prices.

---

## 4. CONFIG: what's pending Tim — 9 nulls + 5 notes

Fixed today (were wrongly open): **OI-1** low-slope base costs (fully priced 11/11) and **OI-11**
low-slope zone split (Zoom 7/20 confirmed one table) — both retired from
`_meta.tim_verify_open_items`, 10 → 9.

Still pending, and his own sheet does NOT answer them:

| # | Field | Why it needs him |
|---|---|---|
| 1 | `pm_incentive` | **Values match, keying does not.** His bands are size-only; ours add residential/commercial with no residential >20 SQ entry → 35 SQ residential takes $50 where his sheet says $100 |
| 2 | `commission_pct.sloped_hvhz` | 10% (sloped) or 15% (low-slope)? |
| 3 | `roof_height.3_5_stories`, `roof_height.6_plus` | **blank in his sheet too** ("-") |
| 4 | `cuts_calc.tile_brands.{verea_s,verea_caribbean,other}.field` | 3 nulls; those brands can't be priced |
| 5 | `cuts_calc.fixed_per_sq.HVHZ` | we have FBC ($519), not HVHZ |
| 6 | `low_slope.deck_types.plywood_replace` | generic plywood adder |
| 7 | `_pending_boundary` | does exactly-20-squares take the 20-29 or 15-20 rate? |
| 8 | `_pending_tile_dumpster_boundary` | does the threshold square itself trigger the next dumpster? |
| 9 | crew-size column per branch | OH Metrics has 9/12/15 men; ours sits between |

Audit command:
```bash
PYTHONPATH=. .venv/bin/python -c "…walk active config for None values and _pending* keys…"
```
(see §"PENDING-TIM TALLY" recipe in git history of this doc's session, or just grep the config JSON)

---

## 5. ZOOM SWEEP — both calls, final status

**2026-07-17** (`docs/plans/2026-07-17-zoom-analysis.md`) — 12 build items:
- ✅ 1 branch management (4th branch "Perkins Construction" exists), 2 time-based OH (**this
  session**), 3 tier adders (PREFERRED already $165), 5 demo selector (`existing_roof`),
  11 low-slope inputs, 12 B9 scaffold
- ✅ **6 RoofR ingestion** — "parse report PDFs into measurements+cut LFs" is now real
  (`scripts/fit_days_from_roofr.py` parses pitch/eaves/hips/ridges/valleys/rakes/wall-flashing/
  facets/2nd-storey from 29 reports)
- ✅ **8 duration-training dataset** — Tim delivered; model fitted and shipped
- ✅ **9 material↔price linkage** — UNBLOCKED (§3); the linkage build itself is the remaining work
- ⛔ 4 profit slider/floor rules — floors enforced, no slider UI
- ⛔ 7 CompanyCam — scaffold built, gated on Tim's PAT
- ⛔ 10 copper commodity pricing — needs Tim's dated copper quotes
- ⛔ social accounts click-to-authenticate surface in Admin → Marketing [58:03]

**2026-07-20** (`docs/meetings/2026-07-20-*.md`) — 25+ items, all verified shipped except:
- ✅ **repair T&M config** — was NULL on all 3 branches (built but never switched on); seeded this
  session, verified: tile / 1.5 d / 2-man / $450 material = **$2,602.50**
- ⛔ Contractor-license *hint text* exists; the license itself now prints (CCC1331944)
- ⛔ GCP spend panel — needs the BigQuery export (`docs/BILLING_EXPORT_SETUP.md`)
- ⛔ Social credentials / X + LinkedIn accounts — needs Tim/Josh logins
- ⛔ CompanyCam token — needs Tim

Nothing else from either call is unaccounted for.

---

## 6. OTHER WORK THIS SESSION

- **Scope-of-work templates**: `GET/PUT/DELETE /quoting/scope-templates` on tenant settings (NOT
  the immutably-versioned pricing config). Seeded with Josh's real PERKINS PROTECTOR block from his
  Knowify proposal (`assets/scope_templates/`). Quoting page has a picker + "Save as template";
  admin repair panel shows the list.
- **Proposal PDF redesign** (`docs/design/2026-07-24-proposal-pdf-redesign.md`): page 1 = decision
  page (tier cards, hero total, CTA), T&C `pre-line` at 10px/1.6, FAQ as stacked cards, accent
  changed to Perkins light blue `#41b1e5` (the old `#ef3c1a` red is in neither Tim's signature nor
  his Knowify proposals). `_PDF_TEMPLATE_VERSION = perkins-scope-v3`.
- **Licence CCC1331944** — was hard-coded `None` in BOTH render contexts, so no proposal ever
  printed it (a Florida requirement). Fixed + set in prod tenant settings.
- **Contract FAQ**: 32 drafts reviewed → 7 duplicate pairs deleted, **25 approved** and printing.
- **Articles**: `_ensure_faq_headings` converts legacy `<dl>` and `<ul><li><strong>Q?</strong>`
  FAQ markup to `<h3>`; `question_heading` promoted to a GATED criterion. 90 articles reprocessed
  and pushed live; 0 failing, 0 legacy FAQ lists left.
- **CI was red since 2026-07-24 16:28 UTC** on one `I001` from `9ba04a9` — because the lint gate
  runs first, bandit/pip-audit/coverage were SKIPPED that whole time. Fixed; all gates green,
  coverage 97.80%.
- **Tim's licence + brand** and the golden Knowify proposal:
  `docs/TIM_SHEET_VERIFICATION_2026-07-24.md`, `~/perkins-corpus/golden-proposals/`.

## 7. MISTAKES WORTH NOT REPEATING

1. **Shipped the geometry model, seeded prod, and reported "the pricing fix is in" — while it was
   inert.** The route deliberately withheld cut LFs from the headline quote. Unit tests + green
   deploy are not evidence a feature works; only the prod smoke caught it.
2. **Then repeated the same class of bug**: the eaves-heavy demo fit collapsed to ~1.1 days for any
   caller that omitted `eaves_lf`, dropping the library to 10% within half a day. Fixed with
   `geometry_model[series]["requires"]`.
3. **Address matching hid 5 of Tim's reports** — `"north"→"n"` ran before `"northeast"→"ne"`,
   numeric street names were skipped, and `split("__")[-1]` returned "Lucie" for `Port_St__Lucie`.
   Nearly asked Tim for files he had already sent. Check the filesystem before blaming the client.
4. **Claimed "all 20 config values match Tim's sheet"** — PM incentive matches in *value* but not
   *keying*. Corrected in the doc.
5. **Left a known lint error as "pre-existing, not my scope"** without checking that CI gates on it.

## 8. NEXT ACTIONS

1. **Send Tim the email** — now an **Outlook draft in jon@degenito.ai**, subject
   `Re: TIME LEARNING (Overhead) for AI Systems — your 30 homes are in, 93% within a day`,
   To tim@, Cc marco@/josh@/eugene@. Jon reviews and sends from Outlook.
   ⚠️ Two bridge limits found: `gmail_create_draft` **silently drops `cc`**, and its `threadId` is
   ignored (Graph needs `createReplyAll`), so the draft is a **new thread**, not threaded under
   Tim's "PART 2". Also `gmail_update_draft` **blanks the body** unless `body` is resent — always
   pass every field. Verify the Cc line in Outlook before sending.
   Source of truth for the prose stays `docs/email-drafts/2026-07-24-tim-estimator-quotes.md`.
2. **Decide the catalog question** (§2) — retire as a price, or re-issue size-banded.
3. **Build the price-book ↔ aggregate-input linkage** from the 77 comments (§3).
4. **BigQuery billing export** — `docs/BILLING_EXPORT_SETUP.md`, then `BILLING_BQ_TABLE` in
   `deploy.sh` and redeploy.
5. Not started, from Jon's earlier list: metal-adjacent article enumeration among the 262
   scheduled, and the article image-vs-YouTube-title-screen audit.
6. Marketing brief for 7/27: **recommended dropped** — that meeting is drip messaging / competitor
   analysis / appointment forms per Tim's 7/24 thread, not a content-SEO review.

## GOTCHAS

`EMBED_BACKEND=vertex` + `export GOOGLE_APPLICATION_CREDENTIALS="$(scripts/fetch_vertex_sa.sh)"`
for anything retrieval-shaped (the `.env` default path does not exist). Cloud SQL proxy on
127.0.0.1:5432; `PW=$(gcloud secrets versions access latest --secret=db-password)`.
`bash scripts/deploy.sh` (not executable) and it refuses a dirty tree (R3-ENFORCE).
`articles` is keyed by **slug**, no `id`. Outbound mail is `EMAIL_SEND_MODE=test`.

**Standing archive directive:** when writing the next continuation doc, move the OLDEST top-level
`CONTINUATION-*.md` into `docs/continuations/`, keep only the latest 3 at top level, fix every
inbound link to the moved file, refresh the README "most recent" pointer, and update related docs.
Done here: `CONTINUATION-2026-07-24.md` archived.
