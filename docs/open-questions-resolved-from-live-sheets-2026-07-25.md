# Open questions vs the LIVE sheets — what Tim has already answered (2026-07-25)

Jon's instruction: *"we should verify all open questions are not answered in cell comments in the
live sheets in either low slope or regular pricing."* Done. **Six of the twelve open questions in the
Tim draft are already answered on the sheets** — three of them by cells we had never read, one by a
value our own config already carries and the email wrongly calls blank.

Method as in `low-slope-comment-audit-2026-07-25.md`: all three live sheets pulled as grid **plus**
`.xlsx` export for `xl/threadedComments/*.xml`, giving a real cell ref per comment. 230 comment nodes
across the three. Corpus: `~/perkins-corpus/tim_lowslope_comments_by_cell.json`.

| sheet | id | tabs | comments |
|---|---|---|--:|
| `***Sloped Roof Price Calculator` (live) | `1qxfKRRvmQS_NYu3AE2KQgek421Wzftu3xVmGECFH-ig` | Tim (HVHZ), FBC, Custom Tile Calc, Marco, Josh, OH Metrics, Jupiter | 90 |
| `**Low-Slope Roof Price Calculator` (live) | `1hTGWCWzIVLgWwNFln_AYBnEcKkj0tLbaZiv82zHXWWQ` | Tim, Josh, Marco, Overhead Metrics, Jupiter | 79 |
| `NEW ***Sloped Roof Price Calculator` | `1KHHGIytrl8snkYrUkYCghiyJInieXtm8FTm1Rhu97JY` | same shape as live sloped | 61 |

---

## 1. Answered — drop from the ask

### A1. Sloped-HVHZ commission is 15%. (was OI-7)

`Tim (HVHZ)!A27` = **"ESTIMATED COMMISSION (15% of P)"**. `FBC!A27` = **"(10% of P)"**. Identical on
the live *and* NEW sheets. The split is not sloped-vs-low-slope, it is **branch**: Miami/HVHZ 15%,
Jupiter/FBC 10% — which is why low-slope "looked like" 15% (that calculator is Miami's).

**This is a live defect.** `commission_pct.sloped_hvhz` is `null`, and `core/pricing_config.py:208`
falls back to `sloped` = 0.10, so every sloped HVHZ job pays commission a third light. Fix: set
`sloped_hvhz: 0.15`.

### A2. PM incentive — our config is already right; the email's description is wrong.

Two different schemes, one per branch, both on the sheets and both already in the fixture:

| | live sheet | our `pm_incentive` |
|---|---|---|
| HVHZ | `N7/N8`: Residential **$150**, Commercial **$300** | `residential_lt20` 150, `commercial_*` 300 ✓ |
| FBC | `N7–N9`: <20 sq **$50**, 20–50 **$100**, >50 **$250** | 50 / 100 / 250 ✓ |

The email says *"your sheet reads size-only … but ours also keys on residential vs commercial"* —
that describes the FBC tab only; the HVHZ tab is exactly the res/comm scheme we implement. The single
real gap: **HVHZ has no residential band above 20 squares** (`residential_lt20` is the only
residential key). Narrow the question to that.

### A3. Verea and the specialty tile upgrades are priced — in two places.

The email says Verea Spanish "S", Verea Caribbean and custom tile field-tile costs are *"blank, so
those brands can't be priced."* They are not blank:

- **Upgrade adders**, `N2–O4` on all four price-guide tabs — and our `specialty_tile_upgrade` already
  matches them exactly: Santa Fe Clay "S" $160, Verea "S" $195, Verea Caribbean "S" $120 (HVHZ) /
  Terracottagres "S" Rustic $120 (FBC).
- **Field-tile costs**, `Custom Tile Calc`: Verea Spanish "S" field $297.04 → total $312.81; Verea
  Caribbean field $230 → total $249; Eagle $147.59/$152.41; West Lake $145.71/$157.70; Crown
  $143.19/$147.49; Other/Custom $310 → $370. Plus `A46–A50`: Tejas Borja 93 SQ +$340 (colours) /
  +$395 (white) / +$465 (premium) per SQ, Verea Flat 123 SQ +$445 per SQ.

What *is* blank is `cuts_calc.standard_tile` for anything but Eagle, and Terracottagres on the NEW
sheet (`O3` empty). Narrow the question to those.

### A4. 3–5 storeys: $1,200 minimum, already implemented.

`D13`: *"3-5 Stories (min. add $1,200 delivery and trash chute)"* — matches
`roof_height_3_5_flat_add: 1200` (used at `core/estimator.py:790`). The per-square adder `E13` is
literally "-" on every tab, and `6+ (need a crane)` likewise. So only the **6+ crane** case is
genuinely open, and we already route it to manual review.

### A5. Tile dumpster threshold — the wording answers the boundary question for HVHZ.

`A28`: HVHZ *"TILE ROOF DUMPSTER (**more than 15 sq.**) $300"*; FBC *"(**every 30 sq.**) $300"*.
Both match `tile_dumpster_threshold {HVHZ: 15, FBC: 30}` and `tile_dumpster_cost: 300`. "More than
15" reads **exclusive**, while `tile_dumpster_boundary_inclusive` defaults to **true**. Not a clean
kill — `Custom Tile Calc` says *"Miami Branch (every 17.5 SQ)"* and *"Jupiter Branch (every 17.5
SQ)"*, a third threshold — so keep the question, but ask it as "your three tabs say 15, 30 and 17.5"
rather than as an abstract boundary question.

### A6. Stucco metal / penetrations, roof cuts, ridge vents — confirmed, no ask needed.

`A15`: *"Add $9 per LF for stucco metal and $75 per penetration"* → `stucco_metal_per_lf: 9`,
`penetration_each: 75` ✓. `J11–K14` roof cuts Low $0 / Medium $25 / High $50, **identical in both
zones** ✓. `M12` ridge vents $9.79/LF → `ridge_vent_per_lf: 9.79` ✓.

---

## 2. Sharper, not answered — ask these differently

### S1. 7/12+ and WinterGuard: the newest sheet disagrees with the comments we priced from.

| | our config | live sloped | **NEW sloped** |
|---|--:|---|---|
| 7/12+ adder (`I3`, on the OH block) | **305** both zones | HVHZ $200 / FBC $305 | **$200 both** |
| WinterGuard (`L28`) | **135** both zones | HVHZ $140 / FBC $150 | **$140 both** |

We set both from comment build-ups ($305 twice, $135 twice) on the reasoning that comments beat
headline cells. The NEW sheet — which is newer than either comment — collapses both to a single
zone-independent number that matches *neither*. Ask which sheet wins, not just "confirm $305".

Note also `I3` sits in the **OVERHEAD** block, so 7/12+ is an overhead adder in Tim's structure. That
is consistent with the days/time model, and worth confirming while asking.

### S2. Which sheet governs? — the question that subsumes several others.

The NEW sloped sheet is not a copy with tweaks; it restructures the fixed-fee block and moves most
headline prices:

| | live sloped | NEW sloped |
|---|---|---|
| fixed fees | Delivery+2 SHT plywood+vents **$650**, New Bonus Values **$1,350**, Permit **$500** | Delivery (two deliveries) **$200**, 2 sheets decking + plumbing vents **$350**, Permit + PM bonus **$550** |
| 13" tile base | HVHZ $780 / FBC $770 | HVHZ $765 / FBC $755 |
| 13" tile OH | HVHZ $270 / FBC $185 | HVHZ $340 / FBC $220 |
| barrel tile OH | HVHZ $420 / FBC $350 | HVHZ $540 / FBC $400 |
| metal SS base | HVHZ $1,020 / FBC $750 | HVHZ $1,020 / FBC $1,025 |
| tile demo | $40 / $30 | $35 / $30 |

We quote from the live sheet's structure ($650 + $1,350 + $500 and FBC base $770). If NEW governs,
**every quote's fixed fees and most per-square rates change**. This is the same "published sheet vs
build-up" question the email already asks, but with a concrete third answer: *there are three sheets*.

---

## 3. Still genuinely open — no answer anywhere on the sheets

Searched every comment and cell; nothing addresses these.

1. **$2,500 minimum — per job or per week, and 5/6/7 days a week.** Zero matches for
   `2,500 | minimum | per week` in any comment on any sheet. It exists only in the 7/17 Zoom.
2. **Which crew-size column each branch prices from.** Both sloped and low-slope sheets carry the
   OH-basis grids (low-slope: Jupiter 4/7/10 men on **2023** figures, Miami 9/12/15 on **2025**), but
   nothing says which column is the operating assumption per office.
3. **20-square profit band.** `J6` "15-20 squares $120" and `J7` "20-29 squares $110" — the overlap is
   in every tab of all three sheets, unresolved by any comment.
4. **HVHZ cut-calculator fixed cost per square.** `cuts_calc.fixed_per_sq.HVHZ` is null; the
   `Custom Tile Calc` tab is FBC-shaped and the NEW sheet's version has different coefficients again.
5. **Low-slope generic plywood deck-replacement adder** (`low_slope.deck_types.plywood_replace`).
6. **Gutters** — the 7/17 list is not on any of these sheets.
7. Plus the four new low-slope items from the comment audit: silicone +$25/coat insurance (2024-08-01),
   stucco metal $9/LF vs $9/10LF, FBC TPO overhead $125 vs $135, coatings' 25-square basis and the
   +$100 demo adder.

---

## 4. Also found, not previously tracked

- **"Random Items"** (`M10–N14`) are priced and we carry only one of them: Blown-in ISO (R-19) $135,
  Turbine Vents $257.50, Solar Vents $1,339 HVHZ / $1,489 FBC (live) with *"NOTE: $2,869 for metal
  roof"* / $3,060 on the FBC NEW tab. Only `ridge_vent_per_lf` exists in our config.
- **"Perkins Penny"** discount: −$55/sq on HVHZ tile, −$70/sq on FBC metal. Not modelled.
- **Upgrade ladder on tile dry-in**: TUP 130 mils +$55, Flintlastic SA Cap 160 mils +$105 (live) but
  **+$85 on the NEW sheet**, "$140 per SQ to add MTS" (live HVHZ tile calc says $135).
- **Metal detail adders** (FBC): +$25 stone coated, +$50 for a 180° bend, +$35 XFR vs MTS,
  HVHZ upgrade +$105/sq.

## 5. Actions

1. **Config fix, ship it:** `commission_pct.sloped_hvhz = 0.15` (§A1) — a live under-payment, and the
   sheet states it twice.
2. **Rewrite the email's open list** — drop A1/A4, narrow A2/A3/A5, re-ask S1/S2 with the NEW-sheet
   conflict, keep §3.
3. **Backlog:** random items, Perkins Penny, upgrade ladder, metal detail adders.
