# Knowify → our config: what Tim's catalog settles, and what it opens

**Pulled 2026-07-28** from **Perkins Roofing Jupiter, Company 30586 / Tenant 28403** over the MCP,
after Tim granted admin. That is *his* tenant. Every previous pull was Josh's (Company 11267 /
Tenant 9258), which is what he asked us to stop using:

> "I would scrape **my** notify… I update my catalog all the time, way more than Josh does. And
> usually I'll even say, hey, copy and paste this into your notify if I change something.
> **Sometimes I'll even forget.** So I would scrape my notify just because I know it's more updated
> as far as, like, accent items." — Tim, 2026-07-27

Raw: `~/perkins-corpus/knowify/jupiter_catalog_perkins_items_2026-07-28.json` (226 items, 339,753
chars of scope text). Josh's baseline for comparison:
`miami_catalog_perkins_items_2026-07-28.json` (26 items, 54,307 chars).

**Tim's catalog is 8.7x Josh's** and 8 items were modified this month. His accent items are live
prices; Josh's copies of the same items are $0.00 placeholders last touched 2024-10-23.

---

## 1. SETTLED — our number was right

**Tile / PREFERRED is $165.** Our config carried $165 annotated *"verified Greener proposal 7/17:
$7,095/43sq"*; Josh's catalog says $160 and that discrepancy has been an open item. Tim's own
catalog says **$165.00**. Josh is stale. No change needed, and the open item closes.

## 2. APPLIED — accent items, new keys, nothing repriced

Tim named skylights, solar vents and chimneys specifically. We had no price for any of them.
`line_items` is a zone-keyed map of flat add-ons that fire **only** when a quote names the key
(`core/estimator.py:1091`), so these are inert until selected — verified: all three branches quote
the identical total before and after.

| key | price | Knowify item | modified |
|---|--:|---|---|
| `skylight_impact_replacement` | $1,590.00 | (OPTIONAL) Impact Skylight Replacement | 2026-07-02 |
| `skylight_curb_mounted_impact` | $2,860.00 | (OPTIONAL) Install Curb Mounted Impact Glass Skylight (Metal Roof) | 2026-07-02 |
| `solar_vents_metal_roof` | $2,689.00 | (OPTIONAL) Install Solar Roof Vent (Metal Roof) | 2026-02-25 |
| `chimney_cap_replacement` | $2,393.46 | (OPTIONAL) Chimney Cap Replacement | 2024-05-13 |

The convention was already prod-verified: existing `solar_vents` $1,489.00 and `turbine_vents`
$257.50 match his catalog **to the cent**, so these four follow the same one.

⚠️ **HVHZ carries FBC forward and is not measured.** Jupiter is Palm Beach = FBC, so his numbers
are the FBC numbers. The only existing item that differs by zone goes the counter-intuitive way
(`solar_vents` FBC $1,489 vs HVHZ $1,339), so there is no rule to extrapolate. Carrying the number
beats omitting the key, because a missing key is skipped **silently** and the add-on would vanish
from an HVHZ quote with no warning. **Ask Tim for Miami's.**

## 3. NOT APPLIED — real disagreements that need Tim

### 3a. Ridge vent: ours $9.79/LF, his $12.50/LF

`ridge_vent_per_lf` is $9.79. His "(OPTIONAL) Unfiltered CT Shingle Ridge Vents" is **$12.50 per
foot (nearest 4')**. Unlike the accent items this is an **existing** price on a different code path
(`core/estimator.py:1032`, qty x rate, cost-tagged), so changing it reprices live quotes. It is also
not established that his per-foot retail is our per-foot *input* — the accent items are flat
customer prices, this one is marked up. **Do not move it without confirming which side of the
markup his $12.50 sits on.**

### 3b. Tile upgrades: three sources, three answers, all within ~$5

His PREMIUM tiers are **bundles** (double underlayment + colored mortar + the tile), not bare tile
adders, so the like-for-like comparison is the delta over PREFERRED ($165):

| tile | his bundle | delta over PREFERRED | our `specialty_tile_upgrade` | gap |
|---|--:|--:|--:|--:|
| Verea Caribbean "S" | $290 (Caribbean) | $125 | `verea_caribbean_s` $120 | **−$5** |
| Verea Spanish "S" | $365 (Mediterranean) | $200 | `verea_s` $195 | **−$5** |
| Santa Fe clay "S" | $320 (Caribbean +$30) | $155 | `santa_fe_clay_s` $160 | **+$5** |

The sign is not consistent, so this is not one rounding rule. And a **third** source disagrees with
both: the Evergrene proposal analysis (Jarvis #431) read Verea Caribbean/Spanish at **$230/$275**.
Three sources, three answers — this needs him, not more analysis.

### 3c. West Lake is tier-dependent, and we model it as a flat adder

His "(OPTIONAL) Upgrade From Eagle to West Lake Concrete Tiles" is **$17.50/SQ** (we carry $15).
But the PREFERRED scope text says it *"includes any standard 13" concrete tile, **including West
Lake**"* — so the adder applies at PROTECTOR and is **$0 at PREFERRED and above**. A flat adder is
the wrong shape, not just the wrong number. This is another instance of the recurring defect: the
key is shaped by where the number was found rather than by what it varies by.

### 3d. Tim vs Josh — five tier prices, for the record

Not our config's problem, but it is the evidence that Josh's catalog is stale and that quoting off
it was wrong:

| tier item | Tim (Jupiter) | Josh (Miami) |
|---|--:|--:|
| PREFERRED — Shingle Re-Roof | $72.50 | $42.50 |
| PREFERRED — Metal Re-Roof | $125.00 | $115.00 |
| PREFERRED — Tile Re-Roof | $165.00 | $160.00 |
| PREMIUM — Metal Re-Roof | $182.50 | $115.00 |
| PREMIUM — Shingle Re-Roof | $175.00 | $165.00 |
| PROTECTOR — Metal Re-Roof | $1,100.00 | $1,125.00 |

Tim also carries **PROTECTOR — Stone Coated Metal Re-Roof $1,450.00**, which Josh has no entry for.

---

## 4. What the tier names actually mean

Worth stating because it is not obvious from the names and it drives every mapping above:

- **PROTECTOR** = the **base full re-roof price** per square (tile $1,100, metal $1,100,
  shingle $650, flat $850). This is the number the customer pays per square.
- **PREFERRED / PREMIUM** = per-square **upgrade adders** on top of PROTECTOR, each a bundle:
  double-layer Polyglass underlayment (which is what unlocks the SWR insurance credit and My Safe
  Florida Home funding), colored/oxide mortar, and a tile grade. They also carry longer warranties
  and the "Perkins Bonus Values" block.

So PROTECTOR is comparable to our engine's output price, and PREFERRED/PREMIUM are comparable to
`specialty_tile_upgrade` — never the other way round.
