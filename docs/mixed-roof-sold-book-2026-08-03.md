# Mixed sloped+flat roofs in the sold book — #429b

**2026-08-03.** Analysis of the 890 mixed contracts in the Knowify mirror, and a back-test of the
estimator against them. Reproduce with:

```bash
DB_URL=… PYTHONPATH=. .venv/bin/python scripts/mixed_roof_sold_analysis.py
```

Every number below is from the live mirror (26,063 deliverables / 16,783 contracts), not a
fixture. `#429a` is settled separately and is **not a defect** — see `CONTINUATION-2026-08-03.md`
§4; do not redo it.

---

## The one thing to take away

**The flat section on a mixed roof is small — median 6 squares — and 82% of them are under 12.**
The share (22%) was already known and is the less useful number: a percentage hides that the
typical flat section is a handful of squares, and the absolute size is what decides whether a
per-square minimum applies.

`low_slope.stockmeier_min_sq` is **12** in all three active prod configs, with
`stockmeier_under_min_material_per_sq: 390` beside it. So on a mixed roof the Stockmeier minimum
is **the normal case, not the edge case** — it applies to 4 jobs in 5. The config note still reads
*"floor note only, not engine logic v1"*. That is a defensible v1 scope decision; it is not a
defensible assumption about frequency, and it was written as though the case were rare.

---

## What the book looks like

| | |
|---|---|
| sloped-only jobs | 1,602 |
| **mixed sloped+flat** | **890 (36% of roofs)** |
| flat share of a mixed roof | median **22%** (p25 14%, p75 36%, max 99%) |
| flat **section size** | median **6 sq** (p25 4, p75 10, max 287) |
| under 12 sq | **82%** |
| mixed-job contract value | median $25,496 |

Classification is deliberately tight (see the script's docstring): base scope lines only, never
`(OPTIONAL)`/upgrade tiers, and a flat line whose square count *equals* the sloped one is treated
as same-area underlayment rather than a second section. A naive keyword match returns 1,395
"mixed" contracts, most of which are tier upgrades and MTS underlayment.

---

## ⚠️ The trap: per-line prices are not comparable to the engine

A Knowify scope line's `Price` is **customer-facing and carries its share of the job's fixed
costs**. The engine keeps fixed costs in `project_fixed_costs` and spreads them across the whole
job. Comparing the two directly produces this:

| | engine marginal $/sq for the flat section | sold flat line $/sq |
|---|---|---|
| FBC | $673 | $850 – $1,114 |
| HVHZ | $690 | $850 – $1,114 |

…which reads as **"the engine underprices flat sections by 21–39%"** and is an **allocation
artifact**. The marginal cost of adding 6 flat squares to an existing job legitimately excludes
the $2,500 profit floor and $1,250 commission the sloped section already carries. Priced as a
standalone job, those same 6 squares come to $8,930 — **$1,488/sq** — because the whole floor
lands on six squares.

**Compare whole jobs.** On the median profile (20 sloped + 6 flat = 26 sq, jupiter, palm_beach):

| roof type | engine FBC | engine HVHZ |
|---|---|---|
| 13″ tile | $1,096/sq ($28,490) | $1,188/sq ($30,890) |
| barrel tile | $1,734/sq ($45,090) | $1,823/sq ($47,390) |
| dimensional shingle | $753/sq ($19,590) | $777/sq ($20,190) |
| standing seam metal | $1,084/sq ($28,190) | $1,357/sq ($35,290) |

Sold whole-job $/sq on mixed roofs: **2024 $943 · 2025 $1,067 · 2026 $894** (p25 ≈ $721,
p75 ≈ $1,374).

**Every roof type except barrel tile lands inside the sold interquartile range**, and the sold
median sits between shingle and 13″ tile — which is what a book mixing roof types should look
like. The engine is not systematically underpricing mixed roofs. Barrel tile prices above p75;
that is expected for the most expensive product in the catalogue, not evidence of an error.

---

## The 2026 "price drop" is not one

Flat $/sq by year looks like a 24% decline from 2024:

| year | flat $/sq | sloped $/sq on the **same** jobs |
|---|---|---|
| 2023 | $1,113 | $775 |
| 2024 | $1,114 | $853 |
| 2025 | $998 | $1,099 |
| 2026 | $850 (n=42) | $817 |

**The sloped sections on those same contracts fell too** (2025 $1,099 → 2026 $817, −26%). A
flat-specific price cut would not move the sloped line. With n=42 on a partial year, this is a mix
and sample effect. Do not read it as a price change, and do not act on it — the same slicing
lesson as memory `slice-price-data-by-time`, one level deeper: slicing by time is necessary but
not sufficient, because a partial year is its own artifact.

---

## What is worth putting to Tim

1. **The Stockmeier 12-sq minimum applies to 82% of mixed roofs.** Is the $390/sq under-minimum
   T&M rate what he wants quoted there, and should the engine apply it rather than warn? This is
   the only finding here with money attached.
2. Nothing else. The engine tracks the sold book on whole jobs, so there is no pricing gate to
   raise — per memory `tims-stated-numbers-are-the-input`, a back-test that disagrees with his own
   books would be a margin-squeeze conversation, and this one does not disagree.

## What this does **not** cover

Change orders (`IsChangeOrder`) are excluded throughout, so the analysis describes the roof as
sold, not as built. Lines whose unit is not squares are excluded, which drops per-LF and per-each
work entirely — this is a **$/sq** view of scope lines, never the full contract value.
