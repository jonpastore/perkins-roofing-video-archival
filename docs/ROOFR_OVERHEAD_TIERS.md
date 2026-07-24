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

## TO APPLY (prod-critical — confirm with Tim first)
1. Feed setup+rate above into the daily_series config so the quote-builder auto-fills labor days
   from squares + roof type (closes the ~$2k PROTECTOR gap).
2. Refresh PREFERRED adder $160 → $165.
3. Demo/shingle: drive off the demo-selector (tear-off type), not SQ alone.
