# Tim's Pricing Workbooks — Full Tab Analysis (2026-07-10)

Answers Jon's ask: "figure out why we have so many and what the differences are."
Method: exported both Google Sheets as xlsx (all tabs) and diffed every tab against
`infra/fixtures/pricing_config_exhibit_b.json`.

## The answer: 3 axes, 2 workbooks, 12 tabs

| Axis | Where it lives | What differs |
|---|---|---|
| **Roof type** (sloped vs low-slope) | The 2 separate workbooks | Everything — systems, base costs, OH model |
| **Zone** (HVHZ vs FBC) | Tabs *within* the sloped workbook | Base costs, OH $/sq, adders, pm_incentive, commission |
| **Branch** (Miami vs Jupiter) | OH-metrics tabs within *each* workbook | **Overhead only** (crew size × day-rate ÷ production). Base costs are zone-scoped, not branch-scoped. |

Both of Jon's conflicting recollections were partially right: the workbooks split by
roof type, AND Jupiter appears in "the other" tabs — as an OH-metrics tab inside each
workbook, not as its own workbook.

## Sloped workbook (`1ptSxJYP…`) — 7 tabs

1. **`Tim (HVHZ)`** — HVHZ zone calculator. == Exhibit B HVHZ exactly (re-verified all
   base costs, OHs, profit scale, specialty tiles, adders).
2. **`FBC (Palm  Lee  St. Lucie)`** — FBC zone calculator. == Exhibit B FBC exactly
   (770/1435/395/420/750 base; 105/185/350/205 OH; pitch add 305; tile demo 30; metal
   demo 45; dumpster every 30 sq).
3. **`Custom Tile Calc`** — utility calculator for custom/specialty tile quotes from roof
   measurements (eaves/hips/ridges/valleys LF → per-sq tile cost). Has Miami-branch vs
   Jupiter-branch dumpster rows (currently identical: $700 every 17.5 sq, $20/sq rolls).
   Tile brand tables: Eagle, Crown, West Lake, Verea, Tejas Borja flat tiles.
4. **`Marco`** / 5. **`Josh`** — per-salesperson WORKING COPIES of the FBC calculator,
   byte-identical to each other, with a worked job typed in (41.5 sq tile job →
   $51,677.50 total, 14.77% profit). **No unique pricing** — scratch pads.
5. 6. **`OH Metrics`** — Miami branch OH derivation (2023): OH basis $/man-day at staffing
   levels (9/12/15 men → $460/$345/$275), ÷ crew production (sq/day) → OH per sq.
   E.g. tile re-roof OH: $361.61 (9 men) → $216.18 (15 men).
7. **`Jupiter`** — Jupiter branch OH derivation, same structure, SMALLER basis:
   4/7/10 men → $345/$200/$140. Jupiter tile re-roof OH $271.21 (4 men) → $110.06
   (10 men). Also has Stone Coated Metal rows Miami lacks.

## Low-slope workbook (`1SGLYoOI…`) — 5 tabs

1. **`Tim`** — the calculator (tab 1, already ingested into Exhibit B r2). Worked
   example: 498 sq job → $393,430.
2. **`Josh`**, 3. **`Marco`** — same calculator, per-salesperson copies with their own
   jobs typed in (15 sq / 4 sq). No unique pricing.
4. **`Overhead Metrics`** — Miami low-slope OH derivation (2025; same $460/$345/$275 bases).
5. **`Jupiter`** — Jupiter low-slope OH derivation ($345/$200/$140 bases).

## Reconciliation vs `pricing_config_exhibit_b.json`

- **HVHZ + FBC zone values: MATCH exactly.** No corrections needed.
- **NEW EVIDENCE — resolves OI-7 (sloped HVHZ commission):** `Tim (HVHZ)` A27 =
  "ESTIMATED COMMISSION (**15%** of P)"; FBC tab = 10%. So sloped-HVHZ commission is
  **0.15**, not the engine's 0.10 default. Config flip needs Tim confirmation (revenue
  impact) — surfaced, not auto-applied.
- **NEW EVIDENCE — supports OI-8 (pm_incentive):** HVHZ tab: Residential $150 /
  Commercial $300 (type axis). FBC tab: <20 sq $50 / 20–50 $100 / >50 $250 (size axis).
  Matches fixture values AND explains the odd schema: the two zones use different
  incentive axes. Still awaiting Tim sign-off to activate.
- **Dumpster thresholds** (HVHZ >15 sq, FBC every 30 sq): match fixture.
- **Jupiter branch config**: prod currently duplicates Miami's Exhibit B. Correct fix is
  NOT copied base costs (those are zone-scoped) but **Jupiter overhead** from the Jupiter
  OH tabs — which is exactly what Estimator v2's day-based OH mode models (per-series
  days × branch day-rate). Feed Jupiter day-rates/crew sizes into the branch config.
- **Naples: NO DATA.** No naples tab exists in either workbook. Naples branch config has
  no source — ask Tim (it currently silently duplicates Miami).

## Follow-ups
- [ ] Tim: confirm sloped-HVHZ commission = 15% (OI-7; sheet evidence above).
- [ ] Tim: pm_incentive sign-off (OI-8; both zone matrices now sheet-verified).
- [ ] Tim: Naples branch — which OH basis applies (no tab exists)?
- [ ] Estimator v2: use Jupiter OH tab day-rates as the Jupiter branch day-based-OH
      config; Marco/Josh 41.5-sq FBC job + low-slope 498-sq job are candidate goldens.
