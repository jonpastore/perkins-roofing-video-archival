# Roofing estimator: overhead allocation model — independent review requested

You are reviewing analysis done by another AI. The human believes that AI has been
"inventing and missing things." Find errors, unsupported leaps, and omissions. Be adversarial.
Do not be agreeable. If a conclusion is right, say which parts are load-bearing and which are
decoration.

## BUSINESS CONTEXT

Perkins Roofing, South Florida. Two branches: Jupiter (profitable) and Miami (losing money or
breaking even every quarter since Q2 2024). We are building an estimator to REPLACE the owner's
(Tim's) Google Sheets pricing calculators. Price = materials + labor + overhead + profit.
Profit is explicitly negotiable and has levers; cost and materials must be exactly right.

Zones: FBC (Palm Beach / Lee / St. Lucie) and HVHZ (Miami-Dade / Broward, stricter code).
Roof classes: sloped and low-slope. Four sheet quadrants total.

## VERIFIED FACTS (read from source: live Google Sheets via API, emails, and their job-costing DB)

Tim, email 2026-07-30 08:30:
- Jupiter daily office overhead = $1,470/day. Miami = $4,257/day.
- "My assumption is to have 1.5 crews on any given day (one demo crew and one other crew ---
  either repairs, tile install, metal install, shingle install)"
- Miami needs 4 crews/day min (2 re-roof + 2 repair) "otherwise that branch is losing money."
- "Before I started using 'days' for more OH accuracy we were using the tab on the sheets for
  OH Metrics (which are still a nice, loose guide, but not as accurate). This is literally
  based on 15 years of experience combined with the recommended days per task using the
  roofing estimator's manual that is used for the contracting license."

Tim, email 2026-07-30 11:40:
- Confirmed the OH Metrics screenshots he sent were the MIAMI location.
- "The numbers I provided you are what I use for Jupiter and what any franchisee should use."
- Shared the Jupiter OH sheet; will not share Miami's (it lists salaries).

Tim, email 2026-07-24, per-day overhead rates BY ROOF TYPE:
  tile $745/day, shingle $700/day, metal $850/day, demo/dry-in $1,050/day

His "OH Metrics" spreadsheet tab (he calls this the OLDER, less accurate method):
- Formula in every cell: OH per square = (daily OH / men) x crew_size / squares_per_day
- Three bases: $460 @ 9 men, $345 @ 12 men, $275 @ 15 men.
  460*9 = 4140, 345*12 = 4140, 275*15 = 4125 -> all imply ~$4,140/day. This is MIAMI.
- Crew sizes, derived from his own "squares per day / squares per man" columns:
  removal, demo/dry-in, SA underlayment = 5 men; ALL installs (shingle, 13" tile, barrel
  tile, metal) = 3 men.
- Productivity assumptions: tile install 8 sq/day, shingle 25, metal 5.5, barrel 4.

His Jupiter "2026 OH Average" sheet (newly shared) logs men on site every working day:
- 157 logged days: mean 6.17 men/day, median 6, range 1-12.
- His own monthly averages written in the sheet: 6.8, 5.8, 4.2, 4.8, 6.8 (mean 5.68).

His actual day counts on 30 homes he sent imply productivity of:
  tile 7.1 sq/day, shingle 18.8 sq/day, metal 8.0 sq/day
(vs his sheet's 8 / 25 / 5.5 — metal ~45% FASTER than his sheet, shingle ~25% slower)

Sold prices from their job-costing system, RE-ROOFS ONLY (maintenance/repair excluded),
median $/square:
  2026: tile $1,100 (n=45), shingle $689 (n=37), metal $1,252 (n=46)
  2024: tile $1,426, shingle $757, metal $1,697   (2024 was a price spike)
  2020: tile $1,036, shingle $591, metal $1,263

Validation set: 21 of Tim's 30 homes carry a price he actually charged. Their own medians are
tile $1,222/sq, shingle $713/sq, metal $1,688/sq — the 3 metal homes are at 2024 price levels.

## OUR SYSTEM TODAY

Per-branch config: office_daily_overhead, office_men, daily_overhead_rates (the four per-day
by-roof-type numbers), overhead_basis ("branch" = one flat daily number x days; "series" =
per-day-by-roof-type rates x days).

CURRENT STATE: all three branches are overhead_basis="branch" with a flat $1,400/day. The
per-day-by-roof-type rates are stored but NOT IN USE. Miami carries the SAME four rates as
Jupiter despite 2.9x the office burn. office_men: Jupiter 7, Miami 14.

Cost/materials verification vs his sheets, per square at 25 SQ:
- FBC sloped, 5 roof types: our base cost AND our overhead both match his sheet EXACTLY (0.0%)
- HVHZ sloped, 5 roof types: EXACTLY (0.0%)
- Low slope, 8 systems: EXACTLY
- His own worked example end to end: his sheet $18,625, ours $18,475 (-0.8%)
  (the -0.8% is: his example cell uses $125/sq shingle OH while his own OH table on the same
  tab says $105; plus profit $110 vs $100 from a size-sliding profit curve; plus a $100 PM
  incentive line we add)

## MODEL COMPARISON (our quote vs 2026 sold medians, the 21 homes)

                                     tile     shingle   metal
his emailed per-day rates          +11.7%     +1.0%    +3.7%
uniform crews @ $210/man-day       +10.2%     +0.6%    +0.8%
uniform crews @ $238/man-day       +12.4%     +2.5%    +3.3%

$210/man-day = $1,470 / 7 men (7 = our config's ASSUMED headcount)
$238/man-day = $1,470 / 6.17 men (6.17 = his LOGGED average)
"uniform crews" = per-man-day x crew size, crew sizes 5 (demo) and 3 (all installs)

Worked example, 1913 Flower Drive, 35 SQ tile, his day counts 3.5 demo + 6.0 tile,
he charged $45,200:
  his emailed rates:      overhead $8,145, our quote $44,345  (-1.9%)
  uniform @ $210/man:     overhead $7,455, our quote $43,655  (-3.4%)
  uniform @ $238/man:     overhead $8,462, our quote $44,662  (-1.2%)

$210/man x 5-man demo crew = $1,050/day = his emailed demo rate EXACTLY.
His install rates / $210 give 3.55 (tile), 3.33 (shingle), 4.05 (metal) — not whole numbers.

## THE DIRECTION SET BY THE HUMAN

"The sheets have his old formula for per sq by roof type but he uses PER DAY BY ROOF TYPE and
that's what we need to achieve." Note this contradicts an earlier instruction in the same
conversation to "go with uniform pricing," and a still earlier one to "not make it uniform"
because "tile, metal, and shingle have different labor efforts."

## QUESTIONS

1. Is "per day by roof type" (his four emailed rates) a genuinely different model from
   "per-man-day x crew size", or the same model with crew size baked in? If the same, what
   observable would distinguish them?

2. The four rates imply fractional crews (3.55, 3.33, 4.05, 5.00); only demo is whole. Give
   the plausible explanations and how to test between them.

3. Is validating against "2026 median sold $/sq" sound, when the comparison set is 21 specific
   homes and the benchmark is ~45 different jobs? What is wrong with it and what is better?

4. His sheet says metal = 5.5 sq/day; his actual jobs say 8.0. If OH per square is driven by
   squares/day, which should a pricing system use, and why?

5. "1.5 crews" vs a logged mean of 6.17 men/day, when demo (5) + one install crew (3) = 8 men.
   Reconcile, or explain which number is wrong.

6. Miami: $4,257/day burn, 4 crews, 14 men, currently using Jupiter's identical per-day rates,
   and we cannot see the Miami OH breakdown. What breaks, and what is the correct treatment?

7. What has the other AI MISSED entirely? What question should have been asked and wasn't?

8. Circular validation risk: we are tuning overhead against sold prices that already embed
   Tim's own overhead assumption. Does that invalidate the "+0.8% metal" result? How do we
   break the circularity?

9. Given profit is negotiable with levers (size-sliding profit curve, a $2,500/on-site-week
   floor, percent/amount discounts, per-square overrides), does overhead precision even matter
   commercially, or is this optimising the wrong variable?

Be specific and quantitative. Flag anything that looks like motivated reasoning.
