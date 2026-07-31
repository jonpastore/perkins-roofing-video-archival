# CONTINUATION — 2026-07-31 (late)

**HEAD `2115187`, pushed, tree clean. CI + deploy green on that sha. Terraform drift clean (plan
exit 0). Full suite green (`PYTEST_EXIT=0`).** Warranty plugin **1.3.1** live on staging. Prod
migrations through 0051.

Read `CONTINUATION-2026-07-31.md` for the measured-salinity build this continues, and
`CONTINUATION-2026-07-30-pm.md` for the overhead work (Tim's sheet, the unsent email).

---

## §0 — WHAT SHIPPED: THE TOOL ANSWERS FOR THE WHOLE STATE

The bbox went from South Florida to all of Florida. Not a design change — the 3-mile coastal clip
and lazy loading already carried it.

| | before | after |
|---|---|---|
| OSM waterways | 21,914 | **55,749** |
| active USGS salinity gauges | 64 | **171** |
| `tidal.geojson` | 0.93 MB | **1.96 MB**, 6,482 geometries |
| classes | — | 388 `tagged`, 86 `measured` salt, 54 `measured` fresh |

Verified against the live staging asset, not the local build:

```
100 N Ashley Dr, Tampa          210 ft  MEASURED (46,600 uS/cm, HILLSBOROUGH R AT PLATT ST,
                                                  USGS 02306028, 220 ft along the waterway)
1 Independent Dr, Jacksonville  630 ft open water + tidal 1,022 ft measured
101 N Palafox St, Pensacola     2,978 ft, tagged
18989 SE Federal Hwy, Tequesta  1,351 ft measured   <- CONTROL, unchanged
1200 S Pine Island Rd, Plantation  silent            <- NEGATIVE control, still silent
```

**The hourly sweep is now genuinely closed-loop.** It had never once succeeded — see §2.

---

## §1 — THE HEADLINE NUMBER FELL AND THAT IS CORRECT

**Held-out agreement: 75% (128/171)**, against 81% (52/64) before.

**This is a bigger, harder denominator, not a regression.** The *same* statewide asset scored over
the *old* South Florida bbox gives **80% (51/64)**. One gauge of difference, and readings are live
between runs — that is noise, not a code change. Existing territory is untouched; the 107 new
gauges sit in harder country, because long inland estuaries lose to the coastal clip.

Always score a coverage change over BOTH bboxes before believing a rate moved.

---

## §2 — TWO BUGS, EACH HIDING BEHIND THE OTHER, NEITHER VISIBLE LOCALLY

The sweep was declared live yesterday on the strength of a LOCAL invocation. The first real
scheduled fire, 04:17:00 UTC, failed. So did the three retries.

```
1. ImportError: cannot import name 'fetch_salinity_readings' from 'scripts' (unknown location)
   .dockerignore ignores `scripts/*` and re-includes an ALLOWLIST of four files. The fetcher was
   never added, so the image shipped an EMPTY scripts/ namespace package — hence "unknown
   location" rather than ModuleNotFoundError.

2. PermissionError: [Errno 13] Permission denied: '/home/appuser'
   fetch_salinity_readings.CACHE defaults under Path.home(). Right on a laptop, impossible in the
   job: non-root user, no home. In the job that file is pure scratch — the durable cache is the
   GCS object — so it now points at the temp dir.
```

**Neither was reachable from a checkout.** CI was green, terraform was clean, the image built, the
scheduler fired on time, and the job died anyway. Each cost a full deploy cycle to find, because
each only surfaced after the previous one was fixed.

Both fixes ship with a test that **fails without them** (verified by stashing the fix):
`tests/jobs/test_dockerignore_covers_job_imports.py` parses `from scripts import x` out of `jobs/`
and asserts a matching `!scripts/x.py`; `tests/jobs/test_salinity_sweep_scratch_path.py` points
`Path.home()` somewhere the job must not write.

⚠️ The scratch-path test asserts the **invariant** ("never write under home"), not `PermissionError`
itself — pytest's `tmp_path` is creatable, so it cannot reproduce an unwritable home.

**Proof the loop is closed**, from the job's own stdout:

```
171 gauges in the bbox; refreshing 7 (slice 5/24), 30d window
cache now holds 171 gauges (106 windowed, 65 latest-only) -> /tmp/salinity-readings.json
gs://.../warranty-tool/salinity-readings.json   171 gauges, bbox [24.3,-87.8,31.1,-79.8], 05:09:56Z
```

---

## §3 — THE UI DIALOG WAS A DEAD FEATURE, NOT A BROKEN ONE

Jon, testing: *"it looks like map rendering instead of address verification and it's not working."*
The verification was working — Tampa returned 210 ft with its citation in the same screenshot.
Google was painting **"This page can't load Google Maps correctly"** over the address box.

Root-caused by reproduction, and **the first hypothesis was wrong**: it is not the referrer (the
`perkins-setback-widget` key allowlists the staging domain) and not the library load (A/B'd
`libraries=places` on and off headless — both load clean, no `gm_authFailure`). It fires on
**keystroke**:

```
warning: As of March 1st, 2025, google.maps.places.Autocomplete is not available to new customers.
error:   You're calling a legacy API, which is not enabled for your project.
request: .../place/js/AutocompletionService.GetPredictions -> denied
```

This project postdates that cutoff, so the legacy class **can never work here**. The typeahead had
never produced a single suggestion — only the dialog. Removed in 1.3.1; the Geocoder (a different,
enabled API), the Leaflet map, and the warm-on-focus preload all stay.

Restoring it needs Places API (New) + `PlaceAutocompleteElement` + `places-backend.googleapis.com`
on that key's API targets in Terraform. That key is **not in IaC today** (only `squares_key` is).

---

## §4 — TWO REAL PROBLEMS FOUND, DELIBERATELY NOT FIXED

Both are one-constant changes that move numbers the project relies on. **Jon's call.**

**1. `REACH_MI` clips from the wrong thing.** It keeps geometry within 3 mi of the COASTLINE, but
the 1-mile warranty provision bounds ADDRESS-to-water distance. Different quantities. **21
salt/brackish gauges fall outside the clip, and 6 are already in South Florida:**

```
 3.1 mi   52,700 uS/cm  FAKA UNION CANAL BOAT BASIN AT PORT OF ISLES
 3.1 mi   30,700 uS/cm  ST LUCIE RIVER AT SPEEDY POINT, STUART
 4.8 mi   27,600 uS/cm  PEACE RIVER AT HARBOUR HEIGHTS
14.1 mi    4,300 uS/cm  ST JOHNS RV SHANDS BRIDGE (a house 500 ft from it gets NO tidal answer)
```

Widening the bbox did not create this; it made it reachable in far more places. Cost of fixing:
asset size.

**2. `validate_tidal_against_gauges.py` compares the wrong statistic.** Its `IV_URL` carries no date
range, so it scores against a single **instantaneous** reading while the build classifies on a
**30-day median**. On tidal water those differ by an order of magnitude:

```
MANATEE RIVER AT RYE      326 uS/cm instantaneous   vs  3,210 median
AUCILLA RIVER NR MOUTH    919 uS/cm instantaneous   vs  7,420 median
```

Both appear in the disagreement list as "we say salt, the gauge says fresh". **The layer is right;
the validator sampled a tide.** Every held-out rate ever quoted is therefore pessimistic, and most
so for the estuarine gauges that matter most. Fixing it changes a tracked number.

---

## §4b — QUOTED GAUGE VALUES ARE POINT-IN-TIME

Every µS/cm figure in these docs is a **30-day median over a sliding window**, so it moves. The C-8
pair across S-28 was recorded as `473 / 29,900` on 07-30 and reads `465 / 20,450` on 07-31 — same
gauges, same structure, same conclusion. It was caught by fact-checking a client email against the
live cache before sending.

**The ordering is the durable fact** (fresh landward of the structure, salt seaward), not the
number. Re-read `~/perkins-corpus/osm/salinity-readings.json` before quoting a value to anyone.

Also note: 106 of 171 gauges carry a real USGS series (~2,800 samples); the other **65 publish only
a current value**, get `samples=1`, and are overwritten each sweep. We do **not** accumulate our own
history, so those 65 do not improve over time. Banking a daily sample for them would give a genuine
30-day baseline after a month — not built, and it is the honest gap in the "30-day average" story.

---

## §4c — AUTOPILOT RUN, 2026-07-31 (5 commits, all pushed and green)

Jon stepped away with "complete as much as possible, fix forward, do not let blockers stop you."

**`5ccb9f5` — the OAuth store accepted `account_id` and threw it away.** Every method took it and
ignored it, so all accounts on a platform resolved to one secret. Invisible with one account per
platform; for QuickBooks it meant four branch COMPANIES sharing a token. #358 called it a
collision — the parameter was decorative. Now `tenants-{t}-{platform}-{account}-{key}`, with the
legacy id still READ so live tokens survive. ⚠️ Three callers disagreed on the account id and only
interoperated BECAUSE it was discarded (callback wrote `"default"`, reader read `""`, social_job
wrote the TikTok open_id); scoping without reconciling them would have rotated TikTok's token into
a secret nothing reads. All three now use `SINGLE_ACCOUNT`.

**`42c1ead` — a 2011 reading was voiding warranties in 2026.** See §2c in
`docs/BRACKISH_DATA_SOURCES.md`. Found while building the banked-history feature I had just
described to a client, which is the only reason it surfaced at all.

**`9320c90` — the clip measured distance to the coastline, the provision measures distance to the
address.** Now clips `inferred` only. +0.09 MB.

**`e30ca68` — two skips that reported green**, plus the `calc_audience` default finally pinned.

**`6b3cb68` — two warnings so an extrapolated number stops looking measured.** The day model is
fitted on 29 Palm Beach / Treasure Coast homes and shipped to Miami; commercial is priced on the
residential profit scale.

⚠️ **#424's leave-one-cluster-out could not be run: its premise is wrong.** All 29 homes are
distinct single-family addresses. Evergrene is the separate 9-building commercial bid in #430, not
in this dataset. The other two falsification tests DID run —
`scripts/honest_day_model_cv.py` gives honest LOO **83% within a day against a 34% constant-mean
baseline**, and the shipped ≥6/12 steep rule is re-selected in **27/29** folds. The fit is real
where it was fitted.

**Blocked, not skipped:** #444 (GCP budget) — the Cloud Billing API is disabled and
`perkins-deploy-sa` cannot enable it or list billing accounts. The Terraform resource is written
and waits only on `var.billing_account`. Needs console access with billing rights.

### The review caught a false VOID I had just shipped — `b73e7ee`

`critic` + `architect` (opus) and gpt-oss-120b + qwen3.6 reviewed the run. **The critic found a
live customer-facing defect in my own fix.** Exempting `tagged` from the clip put freshwater Dunns
Creek into the verdict-moving set 25 mi inland, because **OSM `tidal=yes` means water LEVEL, not
salinity** — the St Johns' tidal signal runs ~160 mi inland. That is the Golden Gate Estates
failure recreated one paragraph after diagnosing the same category error on a different axis. Now
only `measured` is exempt. Also excluded 78 closed rings (lake polygons flooded through a channel
BFS) and held marginal far-inland readings to a caveat (Blue Spring is a *freshwater* artesian
spring reading 1,620).

The architect independently found that my legacy secret fallback **re-opened the QuickBooks
collision the commit existed to close** — it fired for every platform, so a branch missing its
scoped secret inherited the shared one. Gated on `SINGLE_ACCOUNT`. gpt-oss separately caught that
character-folding account ids was not injective (`a/b` and `a-b` collide); now digest-suffixed.

⚠️ **qwen3.6 passed all three areas as "Correct" and was wrong twice** — it called the fallback
safely gated, and called the `fresh` branch dead code when `build_tidal_layer` sets exactly that
value. Local review is a second opinion, never a gate.

### Two things the review surfaced that are NOT fixed

1. **`api-run-sa` cannot create a secret.** It holds `secretAccessor`, `secretVersionAdder`,
   `viewer` — nothing granting `secretmanager.secrets.create`. `put()` calls `create_secret` for
   any absent secret, so the OAuth connect flow 502s and the "platforms migrate as they
   re-authenticate" story cannot complete. Pre-existing (no `tenants-*` secret has ever existed;
   live social tokens are flat project secrets read by `_from_env`). Fixing means an IAM grant in
   Terraform — a security-scope decision, deliberately left for Jon rather than self-approved.

2. **Banking is correct and currently inert.** Verified against the 13:18 production run: `stale=2`
   proves the new image is live, `history=0` because every latest-only gauge takes the stale
   early-return — and the latest-only set and the stale set are *byte-identical*. All 65 are
   dormant stations, so there is nothing to bank until one resumes. The feature is tested and
   right; it has no input. The email to Tim says we do NOT bank yet, so nothing false went out.

---

## §5 — GOTCHAS EARNED TODAY

- **`.dockerignore` has an ALLOWLIST for `scripts/`.** Adding a job that imports a new script
  requires adding `!scripts/<name>.py`. There is now a test for exactly this.
- **The job container has no writable `$HOME`.** Anything deriving a path from `Path.home()` blows
  up as the non-root user. Use the temp dir; the durable copy belongs in GCS.
- **`.env` sets `GOOGLE_APPLICATION_CREDENTIALS=./infra/vertex-dev-sa.json`, a file that does not
  exist.** Sourcing `.env` therefore BREAKS GCS auth. Use
  `GOOGLE_APPLICATION_CREDENTIALS=$HOME/.config/gcloud/perkins-deploy-sa.json`.
- **`DB_URL` in `.env` is `sqlite:///app/dev.db`.** `wp_install_plugin.py` needs the platform DB:
  `postgresql+psycopg://app:$(gcloud secrets versions access latest --secret=db-password)@127.0.0.1:5432/perkins`
  over the Cloud SQL proxy. ⚠️ **`+psycopg`** — `psycopg2` is not installed, and plain
  `postgresql://` picks it and fails.
- **`resolved_wp_url()` swallows every exception** and returns `""`. An empty target means a config
  or driver problem, not an unset value — probe `PlatformConfig` directly to see the real error.
- **A busy `until` loop with no sleep burns the whole timeout.** Poll with an explicit `sleep`.
- **Google's Maps auth dialog can come from a RUNTIME call, not the script load.** A/B the loader
  headless before blaming the key or the referrer.
- ⚠️ Printing `.env` leaks `WP_PWD`. It appeared in a transcript today; worth rotating.

---

## §6 — OPEN, IN PRIORITY ORDER

1. **The Tim email was SENT 2026-07-31** — copy at `~/perkins-corpus/tim_email_2026-07-31.txt`.
   It was rewritten first to cover the measured-salinity work: why we abandoned map tags and
   SFWMD's groundwater isochlor for instruments, the 30-day median and why tidal water needs one,
   the 1/24-per-hour statewide cycle, the never-blank fallback ladder, and an explicit admission
   of the 65-gauge gap. Its ask narrowed from "which rivers are tidal" to three named rivers that
   genuinely have no USGS instrument (New River nearest gauge 15.4 mi; Miami River's nearest is on
   the Miami CANAL, fresh at 460; Caloosahatchee's is 12 mi up at the S-79 lock).
   ⚠️ Several open Jarvis tasks wait on those same answers (#414 #426 #428 #441 #446 #448) —
   check for his reply and reconcile rather than re-asking.
2. **`REACH_MI` and the validator statistic** — §4, both one constant, both Jon's call.
3. **Miami still charges its whole office day per job** → ~$2,087/sq HVHZ tile against a $1,113/sq
   accepted median. `concurrent_crews: 4` → $1,343/sq, but 4 is a capacity target, not a
   measurement.
4. **Crew share (−0.3%) vs his four rates (+2.2%)** — one config write once he answers.
5. **W3 status is done for the warranty tool**; the SPA's long-running actions (proposal render,
   publish, batch articles) were never scoped. ⚠️ Still an open question for Jon.
6. `naples` carries Jupiter's $1,400 and `office_men = None`; tile +10–12% over sold under every
   overhead model, unexplained.
7. Typeahead migration to `PlaceAutocompleteElement`, if wanted — §3.

---

## ARCHIVE DIRECTIVE (standing, performed for this doc)

When writing a session continuation, move the OLDEST top-level `CONTINUATION-*.md` into
`docs/continuations/` (keep only the latest 3 at top level), fix every inbound link to the moved
file, refresh the docs index's "most recent" pointer, and update related docs.
**Performed:** `CONTINUATION-2026-07-30.md` archived to `docs/continuations/`, the inbound link in
`CONTINUATION-2026-07-30-pm.md` repointed, and README.md's "Most recent" moved to this document.
