# Estimator overhead/labor tiers — backed out of Tim's 30-home OH calculator (2026-07-24)

Source: Tim's "TIME LEARNING (Overhead) for AI Systems" email — Residential OH Calculator
(SLOPED ONLY).xlsx, 30 homes with logged Demo/Shingle/Tile/Metal labor DAYS vs squares.
Stored: ~/perkins-corpus/roofr-attachments/. This calibrates the ENGINE's daily_series overhead
(core/estimator.py DailyOverheadSeries: days × daily_rate) — the dimension the Zoom notes
(docs/plans/2026-07-17-zoom-analysis.md) flagged as the root cause of the $53,910 vs Tim's
$51,950 PROTECTOR delta (engine supports v2 daily_series; the quote-builder wasn't feeding it).

## The "range" is economy-of-scale, not noise
days/SQ falls as job size grows (fixed mobilization spread over more squares) — which is exactly
why small roofs need a per-job minimum margin ($2,500/on-site-week rule):

| Series  | 20-30 SQ | 30-40 | 40-60 | 60+  |
|---------|---------:|------:|------:|-----:|
| Demo    | 0.101    | 0.083 | 0.072 | 0.062|
| Shingle | 0.069    | 0.057 | 0.044 | 0.044|
| Tile    | 0.157    | 0.149 | 0.126 | 0.150|
| Metal   | 0.144    | 0.125 | 0.109 | 0.124|

## Recommended model: fixed setup + marginal per-SQ  (days = setup + rate*SQ)
Least-squares fit over the 30 homes:

| Series  | setup (days) | rate (days/SQ) | R²   | 25 SQ | 50 SQ |
|---------|-------------:|---------------:|-----:|------:|------:|
| Demo    | 1.31         | 0.044          | 0.37 | 2.4   | 3.5   |
| Shingle | 1.06         | 0.024          | 0.38 | 1.6   | 2.2   |
| Tile    | 0.45         | 0.129          | 0.70 | 3.7   | 6.9   |
| Metal   | 0.59         | 0.106          | 0.66 | 3.2   | 5.9   |

- **Tile & Metal fit well (R²≈0.7)** → safe to auto-derive install days from squares.
- **Demo & Shingle are noisy (R²≈0.37)** → they also depend on TEAR-OFF TYPE + layers + access;
  pair with the Zoom "demo selector" (tile haul $65/sq vs shingle $30) rather than SQ alone.

## Existing tier structures already in the config (Exhibit B-2026-07)
- `profit_scale [[1,400],[4,200],[7,160],[14,140],[20,120],[29,110],[null,100]]` — margin scale
  by squares (small jobs 4x margin). `profit_floor_pct 0.13`, `profit_plus_oh_floor_pct 0.33`.
- Zoom-spec'd tiers: PROTECTOR/PREFERRED/3 PREMIUM (Caribbean $290 / Mediterranean $365 /
  Modern $485/sq — verified vs Greener PDF). PREFERRED adder to refresh $160 → $165 (catalog).

## APPLIED (2026-07-24)
1. ✅ **Wired into the engine.** `config["daily_overhead_day_model"]` carries `demo_series`,
   `install_series_by_roof_type`, and the `{setup, rate}` fits above; `core.estimator
   .derive_daily_series()` turns them into labor days (rounded to the required 0.5) and
   `estimate()` auto-fills them whenever `overhead_mode="daily"` arrives with no days — which
   previously fell back silently to per-square OH (the ~$2k PROTECTOR gap). Days the estimator
   types always win, and the days actually used come back on the response as `daily_series`
   (shown in the SPA as "Labor days used").
   - Tear-off adds the demo series on top of the install series (summed when both resolve to
     the same series). A roof type with **no fitted install model — every low-slope system —
     derives nothing** and keeps per-square OH: demo days alone would quote under cost.
   - Config values live in `infra/fixtures/pricing_config_exhibit_b.json` +
     `scripts/seed_daily_overhead_config.py` (idempotent per key; run it to add the model to
     branches seeded before 2026-07-24).
2. ✅ PREFERRED tile adder was **already $165** (`core/perkins_packages.py`, verified vs the
   Greener 7/17 proposal). No change needed.
3. ⛔ Still open: demo/shingle should key off the demo-selector (tear-off type), not SQ alone —
   needs Tim to log tile vs shingle tear-off separately before the fit can be split.

**Tim-gate:** the two open confirmations are the noisy demo/shingle fits (R² ≈ 0.37) and whether
the tile/metal setup constants match how he actually schedules crews.

## ⚠️ The two OH modes do not agree — biggest open question for Tim
Measured on Exhibit B with the fitted days (tear-off + install, per SQ of overhead):

| Roof (zone)          | 20 SQ            | 43 SQ            | 80 SQ            |
|----------------------|------------------|------------------|------------------|
| 13" tile (HVHZ)      | 217 vs 270 (−53) | 177 vs 270 (−93) | 168 vs 270 (−102)|
| barrel tile (HVHZ)   | 217 vs 420 (−203)| 177 vs 420 (−243)| 168 vs 420 (−252)|
| standing seam (HVHZ) | 211 vs 280 (−69) | 172 vs 280 (−108)| 161 vs 280 (−119)|
| shingle (HVHZ)       | 158 vs 125 (+33) | 106 vs 125 (−19) | 92 vs 125 (−33)  |

(by-days $/sq vs the configured per-square OH). This gap is **pre-existing** — it is what any
hand-typed by-days quote already produced — but on barrel tile it is ≈ −$10.4k of overhead on a
43-square job, an order of magnitude past the $2k PROTECTOR delta the Zoom was chasing. Either
`daily_overhead_rates` ($745–1,050/day) covers less than the per-square OH does, or the
per-square OH is carrying fixed costs the day rates omit. **Ask Tim which mode is authoritative
before by-days becomes the default;** the margin floors (13% profit / 33% profit+OH, $2,500 per
job and per on-site week) are the only thing currently catching the difference.
Auto-filled quotes carry a `daily_days_auto_filled` warning so they can't pass as hand-checked.

---

## SUPERSEDED 2026-07-24 pm — days are not a function of squares

Tim's own words on the 2026-07-17 Zoom [10:12], which this whole document's model contradicts:

> "two houses that are both **30 squares** but one got towers and all kinds of crazy shit going on
> and one could just be like this up and over — this one is going to take **two days** and the one
> with all the crazy shit going on could take **five or six days** … that's why it's very important
> to do things based on time"

And [09:46]: "the way to **properly** generate the overhead is based on how long the job is going to
take … **this is just a guide** than it is a rule" — i.e. the per-square OH we default to is, in his
framework, explicitly the guide, not the price.

So fitting days from squares alone was the wrong shape from the start. `scripts/fit_days_from_roofr.py`
re-fits days against the COMPLEXITY features in each home's RoofR report, leave-one-out
cross-validated (24 of the 30 homes matched to their report):

| Days for | squares only | + pitch + facets | **+ all cut LFs** | all 10 features |
|---|--:|--:|--:|--:|
| demo | 0.296 | 0.578 | **0.666** | 0.460 |
| tile | 0.638 | 0.790 | **0.802** | 0.753 |
| shingle | 0.300 | −0.057 | **0.364** | 0.231 |
| metal | 0.627 | 0.890 | **0.897** | 0.881 |

(LOO R². "All 10 features" overfits 24 rows — in-sample R² rises while predictive R² falls.)

**Winner: squares + hips + valleys + ridges + rakes + wall-flashing LF.** Tile 0.64→0.80,
metal 0.63→0.90, demo 0.30→0.67. Shingle stays weak (0.36) because his shingle days barely vary
(1–3 days across every home) — there is little signal to learn.

This is exactly the exercise Tim proposed at [10:49–12:40] ("if we just took like 20 or 30
different [RoofR reports] … and you just said tim put how long these are going to take for each
phase … then i can have it back into an algorithm that would support your gut feeling"), and the
2026-07-24 sheet is the data he promised for it.

**We already ingest every one of those inputs** — `measurements.hips_lf / valleys_lf / ridges_lf /
rakes_lf / eaves_lf` are populated from RoofR for the cut calculator, and `QuoteInput` already
accepts them. So the change is: put the fitted coefficients in the pricing config, derive days from
cut geometry instead of squares, and keep per-square OH as the documented guide-level fallback.

⛔ **Still needed from Tim:** the **notes column** he promised at [12:21–12:40] — "i would have a
notes column that says why you think … so that it's creating like the framing of the logic and how
you're coming up with it, then we can turn that … it's like a word problem being turned into an
algebra equation". The delivered sheet has squares + days for all four materials (as promised) but
no notes, so we can fit his numbers without capturing his reasoning. Also 6 of the 30 homes have no
matching RoofR report in the pull.
