# Proposal PDF Redesign Spec — 2026-07-24

Scope: presentation only. Renderer is `core/proposal_render.py` (`DEFAULT_TEMPLATE_HTML`),
Jinja2 → Gotenberg/Chromium → PDF, no network egress, no JS. Context variables and legal
text are unchanged; this spec only changes markup/CSS inside the template string.

## 1. Diagnosis

Line refs are into the current `DEFAULT_TEMPLATE_HTML` (`core/proposal_render.py:186-359`).

1. **The T&C `<pre>` wall is the client's literal complaint.** `proposal_render.py:225,323` —
   `tc.text` (a single plain-text string) is dumped into `<pre style="white-space:pre-wrap">`
   at 9px with body line-height (1.35). No paragraph rhythm, no clause emphasis, smallest font
   on the page for the densest content. This is the "blob of text."
2. **FAQ is a bare 2-column `<table>`.** `:338-344` — each row crams a bold question into a
   narrow left cell and the answer into the right cell with only a 1px hairline between rows.
   Long answers wrap awkwardly against a short question cell; there's no breathing room between
   Q/A pairs. Tables are the wrong primitive for prose Q&A.
3. **Flat, single-weight heading hierarchy.** `:204` — every section (Scope of Work, Alternate
   Package Options, Terms & Conditions, Contract FAQ, Lumber Schedule) uses the identical `h2`.
   A homeowner can't tell "this is the decision" from "this is the appendix" by looking at it.
4. **No page-1 guarantee.** `.scope` and `.payment` have `break-inside:avoid` (`:205,217`), but
   nothing pins the Totals/Payment/Accept block to page 1. A proposal with 4+ scope line items
   pushes the Accept CTA onto page 2 unpredictably — the one element that must never get buried.
5. **Good/Better/Best is an afterthought, not a comparison.** `:276-287` — when tiers exist it's
   a single bordered box with a 2-column label/price grid, not three cards a homeowner can scan
   side by side. Worse: `quote.good_price` (`api/routes/proposals.py:1457`) is actually the
   **contract total**, not a distinct "Good" tier price — so the ladder can read as
   good=total, better=X, best=Y, which is internally inconsistent if better/best are real
   upgrade tiers. Flagging as a data-shape issue; the redesign below treats "good" as the base
   price row and doesn't imply three fully-differentiated packages unless the caller populates
   real tier data.
6. **Totals block always shows a fake tax line.** `:289-293` — Subtotal and Total are always
   identical (`quote.good_price` used twice) with `Tax: 0%` hardcoded between them. Three rows
   of visual weight for one real number.
7. **Scope-of-work items risk literal duplication.** `api/routes/proposals.py:281-282` —
   `label` is `description.split("—", 1)[0]` and `description` is the full raw string. When the
   source description has no em-dash (the common case), `item.label` (shown in the card header)
   and `item.description` (shown as the body paragraph, `proposal_render.py:262`) are the
   **exact same string**, rendered twice. This is a template-guard fix, not a data change —
   included in the component spec below, flagged separately since it's not pure CSS.
8. **Off-brand color leak.** `.tc-ai-cover` (`:226,229`) uses `#2471a3` (a blue never seen
   elsewhere) instead of the navy `#1b2a52` used everywhere else. Reads as an unbranded inserted
   box.
9. **Density everywhere, no visual rest.** 11px body, 1.35 line-height, ~10px paddings on every
   box, and every container (`info-box`, `.scope`, `.payment`, `.accept`) uses the same
   `border:1px solid #d0d5dd` treatment — no visual priority between "here's your price" and
   "here's a reference table."
10. **Inline lumber exhibit is unconditional.** `:347-357` has no `{% if %}` guard, while a
    separate `include_lumber_chart` checkbox (`proposals.py:1492`) only gates a second, attached
    PDF. That's likely intentional (short in-body summary vs. detailed attached chart) but is
    worth Jon/Tim confirming — not changed here since it's logic, not presentation.

## 2. Page plan (Letter portrait, 0.5in margins)

**Page 1 — the decision page.** Everything needed to say yes, nothing else:
header/brand block → customer+property card → tier comparison (or single price card if no
tiers) → "what's included" highlights (short bullets, not paragraphs) → total investment +
due-today amount → Accept CTA. Force `page-break-after: always` on this block's wrapper so it
never bleeds onto page 2 and never gets crowded by later content.

**Page 2+ — Detailed Scope of Work.** One scannable card per line item (qty chip + bullet
spec, not a paragraph), Perkins Bonus Values line, then the full Payment Draw Schedule table.

**Next — Terms & Conditions + AI cover letter/summary/review-prompts.** Reflowed prose
(see §4), the existing `tc-ai-cover` box re-themed to navy.

**Next (own page, `page-break-before:always`, unchanged) — Contract FAQ.** Redesigned as
stacked Q/A blocks instead of a table.

**Appendix (own page, `page-break-before:always`, unchanged) — Lumber Schedule / Additional
Work Exhibit.** Same reference table, restyled for consistency (zebra rows).

## 3. Type scale, spacing scale, color roles

### Type scale (px, print @ 11px body base)

| Token | Size | Weight | Use |
|---|---|---|---|
| `--fs-brand` | 26px | 900 | Company wordmark |
| `--fs-hero-price` | 20px | 900 | Page-1 total investment number |
| `--fs-h1` | 16px | 800 | "Roofing Proposal" page title (new, page 1 only) |
| `--fs-h2` | 13px | 800 | Section headers (Scope, T&C, FAQ, Lumber) — uppercase |
| `--fs-h3` | 12px | 800 | Card titles (scope item, tier name) |
| `--fs-body` | 11px | 400 | Default body copy |
| `--fs-legal` | 10px | 400 | T&C body (was 9px) |
| `--fs-small` | 9px | 700 | Labels/meta, uppercase, tracked |

### Spacing scale (4px grid)

`--sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px; --sp-5: 20px; --sp-6: 24px; --sp-8: 32px;`
Card padding = `--sp-3`/`--sp-4`. Section top margin = `--sp-6`. Inter-card gap = `--sp-2`/`--sp-3`.

### Color roles (consolidated — one token per role, no ad hoc hex)

| Role | Hex | Was |
|---|---|---|
| `--ink` | `#1f2937` | unchanged |
| `--ink-muted` | `#475467` | unchanged (secondary body/legal text) |
| `--ink-label` | `#667085` | unchanged (uppercase labels/meta) |
| `--brand-navy` | `#1b2a52` | unchanged |
| `--brand-red` | `#ef3c1a` | unchanged (primary CTA / accent only) |
| `--border` | `#d0d5dd` | unchanged |
| `--border-hairline` | `#eaecf0` | unchanged |
| `--surface-alt` | `#f8fafc` | unchanged (card header bg, table head bg) |
| `--surface-tint-navy` | `#eef1f8` | replaces the stray `#f4f8ff`/`#2471a3` blue in `tc-ai-cover` |
| `--surface-tint-info` | `#f0f9ff` | unchanged (Perkins Bonus Values callout) |
| `--warn-border` | `#f59e0b` | unchanged (Payment Schedule box) |
| `--warn-bg` | `#fffbeb` | unchanged |

Rule going forward: no new hex literals in the template. Every color is one of the above.

## 4. Component specs (markup sketch + intent)

### Cover/header block
Keep the existing `.top` grid (brand left, meta right, red 3px rule under). Add a page-1-only
`<h1 class="page-title">Roofing Proposal</h1>` under the brand so page 1 reads as a title page,
not a continuation of a form.

### Tier comparison (page 1)
Replace the flat 2-column grid (`:276-287`) with a 3-column card row, only when
`quote.better_price or quote.best_price`:

```html
<div class="tiers">
  {% for name, price, featured in [("Good", quote.good_price, false), ("Better", quote.better_price, true), ("Best", quote.best_price, false)] %}
    {% if price %}
    <div class="tier-card{% if featured %} tier-card--featured{% endif %}">
      {% if featured %}<div class="tier-flag">Recommended</div>{% endif %}
      <div class="tier-name">{{ name }}</div>
      <div class="tier-price">{{ price }}</div>
    </div>
    {% endif %}
  {% endfor %}
</div>
```
`.tiers { display:grid; grid-template-columns: repeat(3, 1fr); gap: var(--sp-3); break-inside: avoid; }`
— grid is already proven safe in this template (used for `.top`/`.info-grid`/`.scope-head`
today), so no new print-break risk. If only one price exists, this block is skipped entirely
and the single scope/price card from the fallback branch (`:268-271`) is page 1's price line
instead — no forced three-card layout on single-tier proposals.

### Scope-of-work list (page 2)
Guard the duplicate-description case and switch the body from a paragraph to a bullet:
```html
<div class="scope-body">
  {% if item.qty_display %}<div class="qty">Qty: {{ item.qty_display }} {{ item.unit }}</div>{% endif %}
  {% if item.description and item.description != item.label %}
    <p class="spec">{{ item.description }}</p>
  {% endif %}
  <div class="bonus">Perkins Bonus: standard cleanup, project supervision, and warranty support included.</div>
</div>
```
This is the one non-CSS change in this spec (a Jinja `{% if %}` guard) — flagged separately
per constraints; it suppresses an exact literal duplicate, it does not change what data is
shown.

### Price/deposit summary (page 1)
Replace the 3-row fake-invoice `.totals` (`:289-293`) with one hero stat, no invented tax line:
```html
<div class="hero-total">
  <div class="hero-total-label">Total Investment</div>
  <div class="hero-total-price">{{ quote.good_price }}</div>
  {% if deposit.amount %}<div class="hero-total-due">Due at signing: {{ deposit.amount }}</div>{% endif %}
</div>
```

### Payment-draw schedule (page 2)
Keep the existing table (`:298-305`), add zebra striping and bold the first row (the amount
due now):
```css
.payment tbody tr:first-child td { font-weight: 800; }
.payment tbody tr:nth-child(even) td { background: var(--surface-alt); }
```

### Signature/accept block (page 1)
Same `href`/token, same copy intent, restyled to be the clear visual climax of page 1 — filled
tint background instead of a plain white bordered box identical to every other box:
```css
.accept { background: var(--surface-tint-info); border: none; }
.accept a { font-size: 13px; padding: 12px 28px; }
```

### T&C body
Do not touch `tc.text` content. Only:
```css
.terms pre { white-space: pre-line; font-size: var(--fs-legal); line-height: 1.6; }
```
`pre-line` (vs. `pre-wrap`) collapses stray runs of spaces while still honoring the author's
blank-line paragraph breaks — the single highest-leverage, zero-content-risk change here.
Re-theme `.tc-ai-cover` off the stray blue onto navy:
```css
.tc-ai-cover { background: var(--surface-tint-navy); border-left: 4px solid var(--brand-navy); }
.tc-ai-faq h2 { color: var(--brand-navy); }
```

### FAQ (own page)
Replace the `<table>` (`:339-343`) with stacked cards — this is a markup change, not CSS-only,
since a table can't be restyled into this layout:
```html
<div class="faq-list">
  {% for item in tc.faq_items %}
  <div class="faq-item">
    <div class="faq-q">{{ item.q }}</div>
    <div class="faq-a">{{ item.a }}</div>
  </div>
  {% endfor %}
</div>
```
```css
.faq-item { break-inside: avoid; padding: var(--sp-3) 0; border-bottom: 1px solid var(--border-hairline); }
.faq-q { font-weight: 800; color: var(--brand-navy); margin-bottom: var(--sp-1); }
.faq-a { color: var(--ink); }
```

### Lumber exhibit (appendix)
Keep the reference table (it's genuinely tabular data, unlike the FAQ) — just zebra it and
apply the shared type/color tokens.

## 5. Ready-to-paste CSS

```css
@page { size: Letter; margin: 0.5in; }
:root {
  --fs-brand: 26px; --fs-hero-price: 20px; --fs-h1: 16px; --fs-h2: 13px; --fs-h3: 12px;
  --fs-body: 11px; --fs-legal: 10px; --fs-small: 9px;
  --sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px; --sp-5: 20px; --sp-6: 24px; --sp-8: 32px;
  --ink: #1f2937; --ink-muted: #475467; --ink-label: #667085;
  --brand-navy: #1b2a52; --brand-red: #ef3c1a;
  --border: #d0d5dd; --border-hairline: #eaecf0;
  --surface-alt: #f8fafc; --surface-tint-navy: #eef1f8; --surface-tint-info: #f0f9ff;
  --warn-border: #f59e0b; --warn-bg: #fffbeb;
}
body { font-family: Arial, Helvetica, sans-serif; color: var(--ink); font-size: var(--fs-body); line-height: 1.45; margin: 0; }
.page { max-width: 8in; margin: 0 auto; }

.top { display:grid; grid-template-columns: 1.2fr 1fr; gap: var(--sp-5); border-bottom: 3px solid var(--brand-red); padding-bottom: var(--sp-3); margin-bottom: var(--sp-3); }
.brand { color: var(--brand-navy); font-size: var(--fs-brand); font-weight: 900; letter-spacing: .02em; }
.brand small { display:block; color: var(--ink-label); font-size: var(--fs-small); letter-spacing:0; margin-top:2px; font-weight:700; }
.page-title { font-size: var(--fs-h1); font-weight: 800; color: var(--brand-navy); margin: 0 0 var(--sp-2); }
.meta { text-align: right; font-size: var(--fs-body); color: var(--ink-muted); }
.meta div { margin-bottom: 3px; }
.label { color: var(--ink-label); font-weight:700; text-transform:uppercase; letter-spacing:.04em; font-size: var(--fs-small); }

.info-grid { display:grid; grid-template-columns: 1fr 1fr; gap: var(--sp-3); margin: var(--sp-3) 0 var(--sp-5); }
.info-box { border:1px solid var(--border); border-radius:6px; padding: var(--sp-3); min-height:54px; }

h2 { color: var(--brand-navy); font-size: var(--fs-h2); font-weight: 800; text-transform:uppercase; letter-spacing:.06em; border-bottom:1px solid var(--border); padding-bottom: var(--sp-2); margin: var(--sp-6) 0 var(--sp-3); }

/* Page 1 — decision page. Everything before .page-break-1 is forced onto page 1. */
.page-break-1 { break-before: page; page-break-before: always; }

.tiers { display:grid; grid-template-columns: repeat(3, 1fr); gap: var(--sp-3); margin: var(--sp-3) 0; break-inside: avoid; }
.tier-card { position: relative; border:1px solid var(--border); border-radius:8px; padding: var(--sp-4) var(--sp-3); text-align:center; }
.tier-card--featured { border-color: var(--brand-navy); border-width: 2px; }
.tier-flag { position:absolute; top:-10px; left:50%; transform:translateX(-50%); background: var(--brand-navy); color:#fff; font-size: var(--fs-small); font-weight:800; text-transform:uppercase; letter-spacing:.04em; padding:2px 10px; border-radius:10px; }
.tier-name { color: var(--ink-label); font-size: var(--fs-small); font-weight:800; text-transform:uppercase; letter-spacing:.04em; margin-bottom: var(--sp-1); }
.tier-price { color: var(--brand-navy); font-size: var(--fs-h3); font-weight:900; }

.hero-total { margin: var(--sp-5) 0; padding: var(--sp-4); border:1px solid var(--border); border-radius:8px; text-align:center; break-inside: avoid; }
.hero-total-label { font-size: var(--fs-small); text-transform:uppercase; letter-spacing:.04em; color: var(--ink-label); font-weight:800; }
.hero-total-price { font-size: var(--fs-hero-price); font-weight:900; color: var(--brand-navy); margin: var(--sp-1) 0; }
.hero-total-due { font-size: var(--fs-body); color: var(--ink-muted); }

.accept { text-align:center; margin: var(--sp-4) 0 var(--sp-5); padding: var(--sp-4); border-radius:8px; background: var(--surface-tint-info); break-inside: avoid; }
.accept a { display:inline-block; background: var(--brand-red); color:#fff; text-decoration:none; padding:12px 28px; border-radius:6px; font-weight:800; font-size:13px; }

/* Page 2+ — Detailed Scope of Work */
.scope { border:1px solid var(--border); border-radius:7px; margin: var(--sp-2) 0 var(--sp-3); break-inside: avoid; overflow:hidden; }
.scope-head { display:grid; grid-template-columns: 34px 1fr 130px; gap: var(--sp-2); align-items:center; background: var(--surface-alt); border-bottom:1px solid var(--border); padding: var(--sp-2) var(--sp-3); }
.scope-no { width:24px; height:24px; border-radius:50%; background: var(--brand-navy); color:#fff; display:flex; align-items:center; justify-content:center; font-weight:800; }
.scope-title { color: var(--brand-navy); font-weight:800; font-size: var(--fs-h3); text-transform:uppercase; }
.scope-price { text-align:right; color: var(--brand-navy); font-size: var(--fs-h3); font-weight:900; }
.scope-body { padding: var(--sp-3); }
.qty { color: var(--ink-label); margin-bottom: var(--sp-1); font-size: var(--fs-small); text-transform:none; letter-spacing:0; }
.spec { margin:0; color: var(--ink-muted); }
.bonus { margin-top: var(--sp-2); background: var(--surface-tint-info); border-left:3px solid var(--brand-navy); padding: var(--sp-2); font-size: var(--fs-small); font-weight:400; text-transform:none; letter-spacing:0; color: var(--ink-muted); }

.payment { border:1px solid var(--warn-border); background: var(--warn-bg); border-radius:7px; padding: var(--sp-3); margin: var(--sp-4) 0; break-inside: avoid; }
.payment table, .tc-ai-faq table, .lumber table { width:100%; border-collapse:collapse; margin-top: var(--sp-2); }
.payment th, .payment td, .tc-ai-faq th, .tc-ai-faq td, .lumber th, .lumber td { padding: var(--sp-1) 7px; border-bottom:1px solid var(--border-hairline); text-align:left; vertical-align:top; }
.payment th, .tc-ai-faq th, .lumber th { background: var(--surface-alt); color: var(--ink-muted); font-size: var(--fs-small); text-transform:uppercase; letter-spacing:.04em; }
.payment tbody tr:first-child td { font-weight: 800; }
.lumber tbody tr:nth-child(even) td, .payment tbody tr:nth-child(even) td { background: var(--surface-alt); }
.amt { text-align:right !important; white-space:nowrap; }

/* Terms & Conditions */
.terms { margin-top: var(--sp-5); font-size: var(--fs-legal); color: var(--ink-muted); }
.terms pre { white-space: pre-line; font-family: Arial, Helvetica, sans-serif; line-height: 1.6; margin:0; }
.tc-ai-cover { margin-top: var(--sp-4); padding: var(--sp-3) var(--sp-4); background: var(--surface-tint-navy); border-left:4px solid var(--brand-navy); font-size: var(--fs-small); font-weight:400; text-transform:none; letter-spacing:0; }
.tc-ai-cover p { margin: 0 0 var(--sp-2) 0; }

/* Contract FAQ — own page */
.tc-ai-faq { margin-top: var(--sp-5); page-break-before: always; }
.tc-ai-faq h2 { color: var(--brand-navy); }
.faq-list { margin-top: var(--sp-2); }
.faq-item { break-inside: avoid; padding: var(--sp-3) 0; border-bottom:1px solid var(--border-hairline); }
.faq-item:last-child { border-bottom: 0; }
.faq-q { font-weight:800; color: var(--brand-navy); margin-bottom: var(--sp-1); }
.faq-a { color: var(--ink); }

/* Lumber exhibit — appendix */
.lumber { page-break-before: always; font-size: var(--fs-legal); color: var(--ink-muted); }

.footer { margin-top: var(--sp-4); border-top:1px solid var(--border); padding-top: var(--sp-3); font-size: var(--fs-body); color: var(--ink-label); text-align:center; }
```

Wrap the Accept CTA block in the template with `<div class="page-break-1"></div>` immediately
after it (an empty div is enough for Chromium to honor `break-before: page` on the next
rendered element — or apply the class directly to the next section's opening element, e.g. the
Detailed Scope `<h2>`) so page 1 always ends there regardless of scope-item count.

## 6. What NOT to change

- `tc.text` content, `tc.faq_items` Q/A content, `tc.summary_bullets`/`review_prompts`/
  `ai_disclaimer`/`cover_letter` text — legal content is untouched, only its container markup.
- `accept_url`, the `<a href="{{ accept_url }}">` target, and the accept-token flow.
- `tc.include_terms` / `tc.include_contract_faq` conditionals — keep both gates exactly where
  they are (`:320,327,336`).
- The unconditional inline lumber exhibit vs. the `include_lumber_chart`-gated attached PDF —
  two different things today; don't collapse them without Jon/Tim confirming intent.
- `quote_line_items` / tier price sourcing in `api/routes/proposals.py` — the good/better/best
  data-shape issue (§1.5) is a data problem, not something this CSS/markup pass fixes.
- Jinja variable names and the `ProposalRenderContext` field contract — no new context vars
  introduced; the tier-card loop and FAQ stack use only fields already passed in.
