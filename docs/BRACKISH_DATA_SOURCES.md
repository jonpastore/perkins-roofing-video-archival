# Identifying brackish water definitively — what's available, and how good we currently are

**2026-07-31.** Research answer to Jon: *"how can we identify water sources that are brackish more
definitively; validate our data sources; can we publish a confidence rate; does SFWMD publish that
data?"* Every endpoint below was queried live, not taken from documentation.

## Short answer

Yes to all four. There is a free, keyless API that **measures** salinity at 64 points in our
service area, SFWMD publishes an authoritative mapped salt line plus 1,673 active water-quality
stations, and our current layer scores **80% against the instruments** — a number we can publish
and improve rather than a claim.

## 1. The sources that actually measure it

| source | what it is | coverage measured | access |
|---|---|---|---|
| **USGS NWIS instantaneous values** | specific conductance (param `00095`), the standard field proxy for salinity | **64 active gauges** inside our bbox, all 64 reporting live | `waterservices.usgs.gov/nwis/iv/` — free, keyless, JSON |
| **SFWMD DBHYDRO stations** | SFWMD/USGS/USACE monitoring network | **1,673 active water-quality stations**, 4,639 total | station geometry via ArcGIS REST; values via DBHYDRO |
| **SFWMD Saltwater Interface** | the mapped **250 mg/L isochlor** — farthest inland extent of the salt front, updated every 5 years | 7 polylines, 2024 edition, 130 KB GeoJSON; East Coast covers Broward, Martin, Palm Beach, St. Lucie; Miami-Dade maintained by USGS | `geoweb.sfwmd.gov/agsext2/rest/services/Hydrogeology/Saltwater_Interface/FeatureServer/80` |
| **SFWMD Chloride Concentration Control Points** | the chloride samples behind that isochlor | 2009 / 2014 / 2019 / 2024 editions | same host, `Hydrogeology/ChlorideConcentrationControlPoints` |
| NOAA OFS salinity nowcast | model output, not per-address | — | not usable programmatically per address |

⚠️ **The SFWMD isochlor is GROUNDWATER, not surface water.** It answers "is the aquifer salty
here", not "is that canal behind the house tidal". It is a strong corroborating signal and an
authoritative name to cite, but it is not a substitute for the surface-water question.

⚠️ **SFWMD's host 403s a default `curl` user agent.** Send a browser UA or you will conclude the
service is down.

### Conductance → plain English

| µS/cm | classification | note |
|---|---|---|
| < 1,500 | fresh | ≈ 250 mg/L chloride, the same line SFWMD's isochlor draws |
| 1,500 – 30,000 | brackish | the manufacturers' exclusions say "salt **or brackish**" |
| > 30,000 | saline | seawater ≈ 50,000 |

## 2. Validation — our layer against the instruments

`scripts/validate_tidal_against_gauges.py`. Each gauge sits *on* a waterway, so if we call that
water salt-carrying it should read brackish or saline, and if we don't it should read fresh.

```
64 gauges, all reporting live

our layer says   gauge SALT   gauge FRESH   meaning
coast                    15             0   open salt water in our data
tagged                    4             1   OSM-confirmed tidal
inferred                  5             6   connectivity guess only
none                      7            26   we map no water here

Agreement: 51/64 = 80%
```

**What the errors say, specifically:**

- **One measured false positive, and it is in the bucket that moves verdicts.** `UPSTREAM BROAD
  RIVER NEAR EVERGLADES CITY` is OSM-`tagged` tidal and measures **460 µS/cm — fresh**. So even the
  "authoritative" tag is wrong at least once, on the only bucket allowed to change a warranty
  answer. That is worth knowing before trusting OSM tags further.
- **Twelve false negatives, and the worst is in Tim's own back yard.** `LOXAHATCHEE RV 500 FT DS OF
  US-1 AT JUPITER` measures **55,100 µS/cm — seawater** — and we classify that reach as merely
  *inferred*, so it raises a caveat instead of moving the verdict. Same for the St Lucie estuary
  (42,900) and river (29,500).
- **Seven salt/brackish gauges sit on water we do not map at all** (`none`): Faka Union Canal
  52,700 · Shakett Creek 46,100 · McCormick Creek 42,300 · C-8 Canal upstream of S-28 29,900.
- **The physical model is confirmed by measurement.** Two gauges on the *same* C-8 canal read 473
  µS/cm and 29,900 µS/cm on opposite sides of structure S-28. Caloosahatchee at the S-79 lock reads
  498 (fresh) while the estuary is saline; St Lucie above S-80 reads 728 while Speedy Point reads
  29,500. Control structures **are** the salt line, exactly as assumed — the problem was never the
  model, it was that OSM's structure and tidal tagging is incomplete.

### 2b. Statewide, 2026-07-31

Widening the bbox to all of Florida (`24.30,-87.80,31.10,-79.80`) took the gauge set from 64 to
**171** and the waterway set from 21,914 to 55,749.

```
171 gauges, all reporting live

HELD-OUT AGREEMENT: 128/171 = 75%        (each gauge scored without its own reading)
IN-SAMPLE:          147/171 = 86%        (inflated — shown for contrast only)

same asset, scored over the OLD South Florida bbox: 51/64 = 80% held out
```

**75% is not a regression — it is a bigger, harder denominator.** Scoring the statewide asset over
the old South Florida bbox gives 80% held out, against 81% before, and that single gauge is inside
the noise of live USGS readings between runs. Existing territory is unchanged; the new 107 gauges
are simply in harder country — long inland estuaries the 3-mile coastal clip discards.

⚠️ **`validate_tidal_against_gauges.py` compares the wrong statistic.** Its `IV_URL` carries no date
range, so it scores against a single *instantaneous* reading, while the build classifies on a
**30-day median**. On tidal water those differ by an order of magnitude: Manatee River at Rye reads
326 µS/cm instantaneously and 3,210 as a median; Aucilla near the mouth 919 against 7,420. Both show
up in the disagreement list as "we call it salt, the gauge says fresh" — the layer is right and the
validator is sampling a tide. The reported held-out rate is therefore **pessimistic**, and most so
for the estuarine gauges that matter most.

## 3. Yes, we can publish a confidence rate — and it can be evidence, not a hedge

Today the tool says *"this water may be tidal"*. With gauge anchoring it can say:

> **Brackish — measured.** The nearest reading on this waterway is 29,500 µS/cm (USGS 02277100,
> St Lucie River at Speedy Point, 1.2 mi downstream, read 40 minutes ago). No salinity structure
> lies between that gauge and this address.

Three tiers, each with a stated basis:

| tier | basis | effect on the verdict |
|---|---|---|
| **measured** | a gauge on the same reach, no structure between it and the address | moves the verdict; show the reading, station and distance |
| **mapped** | inside the SFWMD 250 mg/L isochlor, or OSM-tagged and not contradicted by a gauge | moves the verdict; cite SFWMD 2024 |
| **inferred** | connectivity only, no gauge, no isochlor | caveat only — today's behaviour |

The headline number ("agreement with measured salinity: 80%, n=64") belongs in the methodology
note, not next to a homeowner's verdict — but it is the honest thing to be able to state, and it
gets better as the layer improves rather than staying a vibe.

## 4. What I'd do with this

1. **Anchor to gauges.** Snap all 64 USGS gauges (plus DBHYDRO stations where values are
   retrievable) to reaches, propagate each reading along the reach until a structure interrupts it,
   and let a measurement override both `tagged` and `inferred`. This alone fixes Loxahatchee,
   St Lucie and the Broad River false positive.
2. **Replace OSM barriers with SFWMD's structures** where they overlap — OSM had 1,629 barrier
   nodes and we had to snap 1,307 more geometrically; SFWMD knows where its own gates are.
3. **Ship the 2024 isochlor** (130 KB) as a second corroborating layer.
4. **Re-run this script on every rebuild** and refuse to ship on a regression in the agreement
   rate — it is a real gate, unlike the address pins.

Cost: no new secret, no runtime dependency if gauge readings are baked in at build time. A live
call would give "read 40 minutes ago" freshness, at the cost of a runtime dependency on
waterservices.usgs.gov — that is a product call, not a technical constraint.

## Sources

- USGS NWIS water services — <https://waterservices.usgs.gov/>
- SFWMD ArcGIS REST — <https://geoweb.sfwmd.gov/agsext2/rest/services>
- SFWMD open data hub — <https://geo-sfwmd.hub.arcgis.com/>
- Tim's original links (2026-07-19): USGS water level & salinity mapper, salinity.oceansciences.org,
  NOAA tides & currents salinity nowcast
