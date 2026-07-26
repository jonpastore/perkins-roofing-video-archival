# Full attachment audit — what Tim's files answer (2026-07-26)

Every attachment Tim has sent, opened and read: 4 workbooks, 39 RoofR PDFs, 3 annotated site photos,
1 zip. Prompted by Jon — I had answered "the 30 homes have no prices" twice from the *one* attachment
I'd opened, while a complete commercial bid sat in the same folder named like a measurement report.

**Files that actually contain prices** (verified by `$` regex across every PDF, plus every workbook):

| file | what it is |
|---|---|
| `Evergrene Project Bid Spreadsheet.xlsx` | **complete 9-building commercial bid**, 312 sq, Tim's own days, OH, base costs and totals |
| `Miramar Project Calculator.xlsx` | commercial flat-roof bid, 142 sq, profit as % of cost |
| `UPDATED Material Prices.xlsx` | **10 dated ABC/Beacon price lists, May 2022 → Apr 2026** |
| `Perkins-worked-examples-4-homes.pdf` | our own output |
| `knowify_jon_test_roof.pdf` | Jon's test |
| `Lumber Schedule.pdf` | lumber |

The 39 RoofR PDFs contain **no dollar figures at all** — confirmed, not assumed. The 30 residential
homes therefore have no price to check against, and none of their addresses match a Knowify project
(matcher self-verified 4,481/4,481).

---

## 1. Questions these files ANSWER

### Q: days per week? — **5, at least on commercial**
`Miramar Project Calculator`, twice: *"Full-Time PM Advisory (Re-Roof 8-10 weeks - **5 days per
week**)"* and *"(Re-Roof - 12 weeks - **5 days per week**)"*. We assume **6**. At 5 days a 6-day job
crosses into a second week, which is +$2,500 under a weekly profit-floor basis. Still needs
confirming for residential crews, but it is the only thing Tim has ever put in writing.

### Q: PM incentive on commercial? — **it is a DAILY RATE, not a band**
- Miramar: *"Additional **$450 daily**"* (8-10 week job) and *"**$300 Daily** (non hoist days)"* (12 week).
- Evergrene: *"Full-time PM (40 days telehandler) **add $225**"* → $9,000.

Our `pm_incentive` is a flat band ($150/$300 HVHZ, $50/$100/$250 FBC). On commercial Tim charges
**per day on site**, $225–$450. Completely different shape, and our commercial path is now reachable.

### Q: Verea and specialty tile pricing? — **answered, and it conflicts with our config**
Evergrene "Upgrade Options", per square: **Verea Caribbean "S" $230**, **Verea Spanish "S" $275**,
**Tejas Borja $395**, **Standing Seam Metal $420**. Our `specialty_tile_upgrade` carries
`verea_caribbean_s: 120`, `verea_s: 195`. Roughly double. Either commercial carries a different
upgrade rate, or the residential sheet is stale — ask, do not silently pick.

### Q: low-slope plywood deck replacement (`plywood_replace: null`)? — **material cost now known**
`5/8" CDX Plywood` at $27.00 (Apr 2026), 0.32 squares per unit → **~$99/sq material** after tax and
waste. Still needs Tim's labour + OH on top, but the material half is no longer blank.

### Q: which office overhead? — **a real commercial data point**
Fed Tim's own Evergrene days, our overhead lands **+8.0%** above his across 284 squares, consistently
per building (+6.9% to +10.1% on seven of eight). So his effective daily overhead on that job runs
~8% *below* the residential daily rates we use ($1,050 demo/flat, $745 tile).

---

## 2. What the attachments reveal that nobody had asked

### F1. A PROJECT is not a JOB — the single biggest structural gap found today
Evergrene is **nine buildings on one site**, and Tim's three annotated photos label them
(Clubhouse, Tiki Hut, Boat House, Gazebo, Pool Pump House, Bus Stop, two Gate Houses). He charges
site costs **once**, in a General Conditions block: green fence + telehandler $22,800, full-time PM
$9,000, cedar nailer $15,000, Polyanchor HV $17,510, skylights $9,540, stucco $20,000…

We quote each building as a standalone job, so **$2,500 of fixed fees (delivery + bonus + permit)
and the $2,500 profit floor apply nine times**:

| building | SQ | Tim $/sq | ours $/sq | delta |
|---|--:|--:|--:|--:|
| Clubhouse | 206 | 1,383 | 1,098 | −20.6% |
| Bus Stop | 3 | 1,588 | 3,332 | **+109.8%** |
| Gazebo | 4 | 1,707 | 2,885 | +69.0% |
| Hood Road Gate | 7 | 1,408 | 2,066 | +46.7% |
| **total** | **284** | 1,343 | 1,238 | **−7.8%** |

The total looks respectable only because the clubhouse being 20% low cancels the small buildings
being 40–110% high. **Compensating errors, not accuracy.** Jarvis #430.

### F2. Tim varies BASE COST per building
Evergrene per-building base (tile): 750, 660, 765, 780, 800, 830, 855, 900, 930. Small and awkward
buildings carry a higher base per square. We use one base per roof type per zone.

### F3. Parapet WALL area is counted as squares
Miramar: *"142 Squares (**134 SQ flat, 8 SQ walls**)"*, against a RoofR report showing 13,326 sqft
(133.26 sq) all flat. So Tim converts parapet wall area into squares and charges it. RoofR reports
`Parapet wall: Xft` and we ignore it entirely.

### F4. Commercial profit is a PERCENTAGE of cost
Miramar: `Profit (14%)` and `Profit (15%)`. Our engine applies the residential per-square
`profit_scale` to commercial unconditionally. Jarvis #427.

### F5. Material costs are up ~8% while selling prices are down ~24% from peak
From the ten dated lists:

| material | 2022-01 | 2023-09 | 2025-05 | **2026-04** |
|---|--:|--:|--:|--:|
| TU Plus (80 mil) | 105.00 | 105.00 | 105.20 | **113.90** (+8.3% YoY) |
| MTS (60 mil) | 104.99 | 104.99 | 105.20 | **114.25** (+8.6%) |
| XFR (80 mil) | 123.80 | 123.80 | 123.80 | **132.25** (+6.8%) |
| 5/8" CDX Plywood | 40.00 | 40.00 | 40.00 | **27.00** (−32%) |

Set against the sold-price trend (tile $1,448 peak 2024H1 → $1,100 now; metal $1,705 → $1,276),
**his materials rose ~8% this year while his realised prices fell**. That is a margin squeeze and
it is the strongest argument yet that the published sheet needs revisiting — not because it is
stale upward, but because cost moved under it.

### F6. The Evergrene Cut Sheet is a full custom tile build-up
`L tear-off 75 · dry-in 85 · tile install 160 · hauling 70 · SA V strips/TU Plus/nails 89 ·
drip metal 30.29 · field tiles & mortar 148.19 · hip/ridge/rake 84.84 · eave closure 57.57 ·
delivery 55` → **base $854.89/sq**, with Eagle at $152.41/sq and Crown at $147.49/sq. This is the
same shape as the sloped Custom Tile Calc and can be checked against `cuts_calc`.

---

## 3. Still genuinely unanswered

7/12+ ($305 vs $200), WinterGuard ($135/$140/$150), the 20-square band, tile dumpster threshold
(15 / 30 / 17.5), repair day rates ($1,185/$1,435 vs $1,400/$1,485), the shingle daily rate ($700 —
still our number, not his), the HVHZ cut-calculator fixed cost, and whether the $2,500 floor is per
job or per week. None of the attachments touch any of these.

## 4. Method note

I answered "no prices in the 30" twice before opening everything, because the bid spreadsheet was
named like the 37 measurement PDFs sitting beside it. The fix is mechanical: enumerate every
attachment and check each for content before generalising from the ones already opened. Same failure
as the all-time median — reasoning from the sample already in hand instead of the population.
