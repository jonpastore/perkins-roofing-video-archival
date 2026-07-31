# CONTINUATION — 2026-07-30 (pm)

**HEAD `5afb0d2`, pushed, tree clean.** Deployed `platform:a86d941` (later commits are docs +
scripts + the WP plugin, none of which the platform image carries). Warranty plugin **1.1.2** live
on staging. Prod migrations still through **0051**.

Supersedes `CONTINUATION-2026-07-30.md` (this morning). Two of its headline claims are now
**disproven** — see §0.

---

## §0 — WHAT THIS MORNING'S DOC GOT WRONG

**1. Miami is NOT priced at $1,400/day.** `miami` config **v27 (2026-07-28)** set
`office_daily_overhead = 4250` and v29 is live. Both adversarial reviews were briefed with the
$1,400 figure and built their lead finding on it. The live per-branch state:

| branch | basis | office_daily_overhead | Tim states | office_men | concurrent_crews |
|---|---|---|---|---|---|
| jupiter | **series** (flipped today) | 1,400 *(inert under series)* | 1,470 | 7 | unset |
| miami | branch | **4,250** | 4,257 | 14 | unset |
| naples | **series** (flipped today) | 1,400 (carried forward) | never stated | None | unset |

Because the estimator charges one job the **whole** branch day, Miami quotes a 30 SQ HVHZ tile roof
at **$2,087/sq** against a **$1,113/sq** median on Miami's own accepted tile work. It is
**over**-priced ~80%, not under-priced 2.9x.

**2. The "sold $/sq" benchmark was Miami PROPOSALS, not Jupiter sales.** The local Knowify mirror
holds ONE tenant and it is the **Miami** company (8,510 projects; 83% Miami-Dade/Broward). Tim's
**Jupiter** company is a separate tenant (30586/28403, 995 projects) reachable only via the Knowify
MCP. And of 3,357 roof-line contracts only **386 were ever accepted** — `BusinessState="Open"`,
which matches invoicing 200/202. `IsSigned` is set on 5% of contracts and is **not** the acceptance
marker. Accepted prices run 4–17% under outstanding proposals.

---

## §1 — THE OVERHEAD ANSWER (Tim's own sheet had it)

**His Jupiter tab builds overhead as `(office/day ÷ men) × crew size ÷ squares per day`, at $200
per man-day.** Verified cell by cell: 3-man tile crew at 8 sq/day = $75/sq; shingle 3 men at 25 =
$24; metal 3 men at 6 = $100; 5-man demo at 25 = $40. The tab's "Re-Roof OH (7 men)" line reads
**$185.72 tile / $105 shingle / $204.75 metal** — his published FBC table to the dollar.

So **his per-square table already splits the office across crews**: a 3-man crew carries 3/7 of the
office, **$600**, not $1,400. That answers the parallel-job question in his own arithmetic. His
7/24 emailed rates sit **above** that share — demo $1,050 vs $1,000 (+5%), tile $745 vs $600
(+24%), shingle $700 vs $600 (+17%), metal $850 vs $600 (+42%) — and that gap is the one number in
the whole exercise that cannot be derived from anything he has sent.

**Scored against the prices he actually charged** (35 priced jobs, his own day counts):

| model | within 5% | within 10% | median |
|---|---|---|---|
| per-square (his table) | 13/35 | 24/35 | −2.4% |
| per-day, his 7/24 rates | 15/35 | 29/35 | +2.2% |
| **crew share @ $200/man** | 12/35 | 25/35 | **−0.3%** |
| crew share @ $210/man | 11/35 | 25/35 | +0.5% |
| flat $1,400/day | 10/35 | 16/35 | +10.3% |

On the last 3 months of accepted Jupiter work (9 jobs, days estimated by us): per-sq −6.5%,
his rates −3.9%, crew share −6.6%, flat $1,400 **+3.5%** — the flat rate only wins there because
our day estimates ran short on those jobs (3 of the 5 checkable are access-flagged), not because
the rate is right.

**Per-square and per-day are the same arithmetic** and cross at one production speed — tile 4.7
sq/day, shingle 8.7, metal 4.6, against his actual 4.3 / 7.7 / 4.7. The per-square table is dead on
at 4/12 pitch (+0.1%, beats the day model 7 of 9) and **16.8% low under 4 sq/day**, **12.6% low**
where he flagged access — it has no pitch or access term, so it can only be right on an ordinary
roof. That is the case for keeping both. **"One model with one knob" was tested and FAILS**
(`scripts/prove_persq_day_equivalence.py`): the collapse is exact only for `days = SQ/p` with no
intercept, the shipped model has intercepts (implied $/sq curves 91–243% across 10–80 SQ), and
`DailyOverheadSeries` quantises days to 0.5 anyway.

**Recovery identity** (the only non-circular test, finally run): Jupiter bills **465.5 charged
job-days against 392 working days = 1.19** over 19 months — a floor, since low-slope and repairs
are not counted. Miami 0.5–0.7 since 2024.

### Shipped today (pricing)
- `jupiter` + `naples` → `overhead_basis="series"` (v28 each). Reprices −7.6% to −9.4%.
- **`concurrent_crews`** config key (deployed, default 1.0 = unchanged): `overhead = days ×
  office_daily_overhead ÷ crews`, branch basis only — inert under series, where the four rates are
  already per-crew-day. **Not set on any branch.** At Tim's stated 4 Miami crews, that 30 SQ HVHZ
  tile roof goes $2,087/sq → **$1,343/sq**.

---

## §2 — THE WARRANTY TOOL (three defects, one of them mine and shipped)

**It hung forever** at "Locating and measuring…". Root cause reproduced headless:
`RefererNotAllowedMapError` — the staging domain was not on the Maps key allowlist — **and**
`loadGmaps()` could never settle on an auth failure (Google serves the loader 200 and reports via
`gm_authFailure`, so `onerror` never fires). Key updated; `checker.js` now handles `gm_authFailure`
with a 12 s backstop. ⚠️ That key (`perkins-setback-widget`) is **not Terraform-managed** — console
state, not git.

**The brackish gap Tim raised on 2026-07-19 is now partly closed.** `scripts/build_tidal_layer.py`
computes salt-carrying water from OSM at build time (canals are tidal seaward of a control
structure), shipping `assets/tidal.geojson` (0.93 MB, 3,639 geometries). Details in
`docs/WARRANTY_TOOL_TIDAL_LAYER.md`.

⚠️ **I shipped a critical bug and review caught it, not me.** The first build labelled a reach
"confirmed salt water" if *either endpoint* touched the coastline, and applied it to the **whole
way** — a 43-mile Intracoastal way, Golden Gate Main Canal (23.6 mi), Snake Creek (18.9 mi). Golden
Gate Estates, Naples — 8.2 mi inland, behind the weirs, on fresh water — was told two of four
materials were **VOID**. Live ~40 minutes. Fixed at the labelling rule: only an explicit OSM
`tidal=yes`/`salt=yes` tag is authoritative; ways are split at barriers; barriers within 25 m of a
channel count even without a shared node (1,629 → 2,936); geometry is genuinely clipped. A second
review pass then found a **regression pin that could not fail** (it read the globally nearest
segment, almost always inferred), a non-reproducible build (string ids + hash randomisation), and a
latched promise. All fixed and verified.

**⚠️ But the capability is DEFERRED, not done.** OSM tags **none** of the Miami River, New River,
Caloosahatchee or Hillsboro as tidal. Across 30 populated places the verdict-moving layer is
decisive in **zero**. The critical bug was closed by *narrowing the capability*.

---

## §3 — THE RESEARCH THAT CHANGES THE APPROACH (queried live, not from docs)

**USGS NWIS publishes measured salinity, free and keyless** — specific conductance, param `00095`,
**64 active gauges inside our bbox, all 64 reporting**. Scored our layer against them:

```
our layer says   gauge SALT   gauge FRESH
coast                    15             0
tagged                    4             1     <-- a measured FALSE POSITIVE
inferred                  5             6
none                      7            26
Agreement: 51/64 = 80%
```

- **Loxahatchee at US-1, Jupiter = 55,100 µS/cm (seawater)** and we call it a guess. Tim's own
  branch, his own example.
- **Upstream Broad River is OSM-`tagged` and measures 460 µS/cm — fresh.** The only bucket allowed
  to move a verdict contains at least one measured error.
- **The physical model is confirmed by instruments**: two gauges on the same C-8 canal read 473 and
  29,900 µS/cm on opposite sides of structure S-28; Caloosahatchee at the S-79 lock 498 vs a saline
  estuary; St Lucie above S-80 728 vs Speedy Point 29,500. Structures **are** the salt line — the
  model was right, OSM's tagging of it is the weak link.

**SFWMD does publish it** (`docs/BRACKISH_DATA_SOURCES.md`): `Saltwater_Interface` — the mapped
**250 mg/L isochlor**, 2024 edition, 7 polylines / 130 KB; `ChlorideConcentrationControlPoints`;
and DBHYDRO with **1,673 active water-quality stations** (26× USGS density). ⚠️ The isochlor is
**groundwater**, not surface canals — corroborating, not a substitute. ⚠️ Their host **403s a
default curl UA**; send a browser UA or you will think it is down.

---

## §4 — NEXT: SPEC AND PLAN ARE WRITTEN, NOTHING BUILT

`docs/superpowers/specs/2026-07-30-brackish-confidence.md` +
`docs/superpowers/plans/2026-07-30-brackish-confidence-plan.md`.

- **W1 gauge anchoring** — snap gauges to reaches, propagate along channel distance stopping at
  structures, cap ~2 mi, and let **measurement override both OSM tags and connectivity in both
  directions** (it must be able to *remove* a warning — that is the Broad River case). Gate:
  hold-one-out agreement > 80%.
- **W2 the learning cache** — a low-confidence check records a research request; a scheduled job
  resolves it against USGS/SFWMD/Overpass and stores a determination with provenance and expiry;
  the nightly rebuild folds it in. **The plugin stays static** — determinations feed the build, not
  a runtime call. ⚠️ **Store reach id + a coarse ~1 km cell only — never the address, never the
  exact coordinate.** Today's CompanyCam finding was publishing a client's building at 0.1 m; a
  table of "addresses people checked" is the same mistake in a database.
- **W3 per-phase status** — the tool prints one spinner and, until this week, hung silently.
  ⚠️ **Open question for Jon:** does "each of the rendering actions" also mean the SPA's
  long-running proposal-render / publish / batch actions? Scoped to the warranty tool for now.

---

## §5 — OPEN, IN PRIORITY ORDER

1. **The Tim email is DRAFTED, NOT SENT** — `jon@degenito.ai`, subject "Your sheet answers the crew
   question — plus 7 things I need". Every number traces to a live source. Also saved at
   `~/perkins-corpus/tim_email_2026-07-30.txt`.
2. **Miami still charges its whole office day per job** → ~$2,087/sq HVHZ tile. `concurrent_crews:
   4` takes it to $1,343/sq in one config write, but 4 is Tim's capacity target, not a measurement.
3. **Crew share vs his four rates** — crew share scored best (−0.3%) and is derivable from his own
   tab. One config write once he answers.
4. **Day counts beat rate models.** Our estimate is unbiased across his 30 homes (median 0.0% over
   90 comparisons) but short on access-flagged jobs; every model reads low on the recent nine for
   that reason. Feeding RoofR geometry into more quotes matters more than any rate choice.
5. `naples` carries Jupiter's $1,400 and `office_men = None` — never confirmed with Tim.
6. `office_daily_overhead` stale: 1,400/4,250 vs his stated 1,470/4,257 (Jupiter's is inert under
   series).
7. Tile prices +10–12% over sold under every overhead model. Predates today, unexplained.
8. Portfolio blocked on `permission_property`; TPO history unusable (maintenance $66/sq mixed with
   re-roofs at $1,253/sq).

---

## §6 — GOTCHAS EARNED TODAY

- **Overpass answers HTTP 406 to a bare POST body** — form-encode the query as `data=`.
- **SFWMD's ArcGIS host 403s a default curl UA.**
- **A referrer-rejected Google Maps key returns HTTP 200** and reports through `gm_authFailure`;
  `onerror` never fires, so a promise waiting on the callback hangs forever.
- **`sleep N` chained after a command is blocked** by the harness; use an `until` loop or
  `run_in_background`.
- **String ids + `PYTHONHASHSEED` = a non-reproducible build.** Sort seeds and output.
- **A "regression pin" that measures the wrong thing passes forever.** Ours read the globally
  nearest segment when inferred outnumbers tagged 22:1.
- **Nominatim does not know every address** (the Boynton one fails); Google's geocoder does.
- Pre-push tests: `.venv/bin/python -m pytest tests/api tests/core tests/adapters tests/jobs
  tests/tenancy` (~4,099 tests, ~8 min). The final summary line may not flush to a redirected log —
  **the exit code is the evidence**.
- Cloud SQL proxy is not installed by default any more; `~/bin/cloud-sql-proxy` was fetched this
  session (`/tmp` copies get wiped).

---

## ARCHIVE DIRECTIVE (standing, performed for this doc)

When writing a session continuation, move the OLDEST top-level `CONTINUATION-*.md` into
`docs/continuations/` (keep only the latest 3 at top level), fix every inbound link to the moved
file, refresh the docs index's "most recent" pointer, and update related docs.
**Performed:** `CONTINUATION-2026-07-29.md` archived to `docs/continuations/`, its `README.md` link
repointed, and "Most recent" moved to this document.
