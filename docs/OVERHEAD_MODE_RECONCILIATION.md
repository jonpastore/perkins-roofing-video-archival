# Reconciling the two overhead modes — options, with measured numbers (2026-07-24)

The estimator prices overhead two ways and they disagree. This is the decision memo; the fitted
day model behind it is `docs/ROOFR_OVERHEAD_TIERS.md`.

## The one measurement that matters most

Josh's real proposal (`~/perkins-corpus/golden-proposals/knowify_jon_test_roof_2026-07-08.pdf`):
**30 SQ tile re-roof, PERKINS PROTECTOR, $33,000 = $1,100/sq.**

Our engine on the same job (jupiter config, FBC/Palm Beach, tile tear-off, 1 story, low cuts):

| Component | $/sq | $ |
|---|---:|---:|
| Base cost (L+M) | 770.00 | 23,100 |
| Overhead (per-sq mode) | 185.00 | 5,550 |
| Profit | 100.00 | 3,000 |
| Tile demo | 40.00 | 1,200 |
| Fixed (delivery/vents 650, bonus values 1,350, permit 500, dumpster 300, PM 50) | 95.00 | 2,850 |
| **Engine total** | **1,190.00** | **35,700** |
| **Josh sold at** | **1,100.00** | **33,000** |
| **Delta** | **+90.00** | **+2,700 (+8.2%)** |

Same direction and magnitude as the ~$2k PROTECTOR delta flagged in the 2026-07-17 Zoom
($53,910 engine vs $51,950 Tim). So the gap is real, reproducible, and **not** an artifact of
junk demo data.

Note what this says about the catalog: `core/perkins_packages.TILE["PROTECTOR"] = $1,100/sq` is
exactly what Josh charged — but `package_options()` deliberately ignores that number and uses the
engine total instead. **The published price and the cost-up build disagree by 8%.** Josh sells at
the published price.

## The two modes don't disagree in one direction — it depends on size and zone

by-days $/sq minus per-square $/sq (negative = by-days is cheaper), tear-off included:

| Roof | 20 SQ | 30 SQ | 43 SQ | 60 SQ | 90 SQ |
|---|---:|---:|---:|---:|---:|
| FBC 13" tile | +31.75 | +14.25 | −7.79 | −15.67 | −21.50 |
| FBC barrel tile | −133.25 | −150.75 | −172.79 | −180.67 | −186.50 |
| FBC standing seam | +6.25 | −4.17 | −32.91 | −35.83 | −46.39 |
| FBC dimensional shingle | +52.50 | +29.17 | +0.81 | −5.83 | −17.50 |
| HVHZ 13" tile | −53.25 | −70.75 | −92.79 | −100.67 | −106.50 |
| HVHZ barrel tile | −203.25 | −220.75 | −242.79 | −250.67 | −256.50 |
| HVHZ standing seam | −68.75 | −79.17 | −107.91 | −110.83 | −121.39 |
| HVHZ dimensional shingle | +32.50 | +9.17 | −19.19 | −25.83 | −37.50 |

Two things fall out:
1. **by-days crosses over around 30–45 SQ** for 13" tile / metal / shingle: higher on small jobs,
   lower on big ones. That is the economy-of-scale the day model is supposed to capture, and it is
   the *correct* shape — a flat per-square OH cannot express it.
2. **barrel tile is broken in per-square mode, not in the day model.** $350–420/sq of overhead
   against a day-rate-derived $163–217/sq is not economy of scale, it is a different quantity.
   Barrel tile's per-square OH looks like it is carrying material/labour premium, not overhead.

## Three ways to fix it

**Option A — re-rate the days so by-days reproduces per-square at typical size.**
Solve `days(SQ) × rate = per_sq_OH × SQ` at each roof type's median job. Keeps both modes, makes
them agree at the middle, still diverges at the extremes (that is the point). Cheapest change:
new numbers in `daily_overhead_rates`, no schema change. Risk: it back-fits the day rate to a
per-square number that itself may be wrong (see barrel tile).

**Option B — declare by-days authoritative and retire per-square to a fallback.**
Honest about intent (Tim thinks in crew-days; the Zoom asked for time-based OH) and it closes the
Josh gap on jobs ≥43 SQ. But it drops overhead ~$150–250/sq on barrel tile, which is a very large
price move to make on a fitted model with R² 0.70 and no confirmation from Tim.

**Option C (recommended) — separate the two quantities.**
The modes disagree because they are not measuring the same thing. Split overhead into
`crew_overhead` (days × daily rate — genuinely time-driven: crew, equipment, supervision) and
`fixed_overhead_per_sq` (insurance, licensing, office, warranty reserve — not time-driven), then
`OH = days × rate + fixed_per_sq × SQ`. Calibrate `fixed_per_sq` so a median job lands on today's
number, which makes the change revenue-neutral at the middle while restoring the size curve.
Costs a config-shape change plus one engine branch; it is the only option where both inputs keep
meaning and barrel tile's premium stops hiding inside "overhead".

## What is true today (shipped 2026-07-24)

By-days with no days entered auto-fills from squares and carries a `daily_days_auto_filled`
warning; per-square remains the default mode. Nothing here is resolved until Tim answers **which
quantity the $745–1,050/day rates are supposed to cover** — that single answer picks the option.
