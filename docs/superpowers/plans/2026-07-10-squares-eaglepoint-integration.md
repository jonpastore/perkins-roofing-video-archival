# Squares / eaglepoint Roof-Measurement Integration — Implementation Plan

Date: 2026-07-10
Author: squares-planner (direct mode)
Status: DRAFT — awaiting Jon sign-off on the flagged decisions (see §11)
Source engine: `SquareQuote/eaglepoint` ml-service, cloned read-only at `/tmp/eaglepoint`
Target: Perkins v2 GCP platform (`video-archival-and-content-gen`, `us-central1`)

Binding rules: `docs/ENGINEERING_RULES.md` (R1 coverage ≥ 97% on `core/` — this repo's
`.coveragerc` actually gates `fail_under = 100`; R2 architect+critic review; R3 100% IaC via
Terraform/Ansible; R4 drift-check clean; R5 Ansible for what TF can't).

---

## 1. Goal & one-paragraph summary

Add a **Squares** capability to the platform: a user enters an address, we geocode it, fetch the
building footprint, run a roof-measurement job, and land the result in the existing
RLS-forced `measurements` table via our own API. The Squares tab then hands off to the Estimator
tab with `num_squares` (and, when available, pitch/edge fields) prefilled. The measurement compute
is the ported eaglepoint ml-service, redeployed as a **Cloud Run service** in this GCP project,
called **synchronously-with-poll** by our `api` service over IAM service-to-service auth. We
deliberately do **not** port eaglepoint's redis/celery/minio/postgres stack; we reuse our Cloud
SQL, GCS, and Firebase-auth'd API. The ml-service is a **stateless compute box** that takes a
lat/lon + footprint and returns measurement JSON; **all persistence and tenancy stay on our side.**

This is the single most important architectural decision and it drives everything below: **eaglepoint's
own DB/MinIO writes are amputated. The ml-service returns JSON; our `api` writes the `measurements`
row under the caller's stamped tenant.** That keeps RLS/tenancy in exactly one place (ours) and avoids
dragging a second Postgres + object store into the project.

---

## 2. What eaglepoint actually is today (verified against `/tmp/eaglepoint`)

- **API:** `ml-service/app/main.py` — `POST /jobs` (202 Accepted) + `GET /health`. Request is
  `{report_id, property_id, lat, lon, queue}`. Async via **Celery+Redis** (`USE_CELERY`), else a
  daemon thread. Results are written **directly to Postgres** (`app/db.py:133-222` → `reports`,
  `report_facets`, `report_edges`) and PDFs/overlays to **MinIO**. There is no "return the result"
  response shape — the caller polls the DB. **We will not use this persistence path.**
- **Pipeline** (`app/pipeline/orchestrator.py:28-215`), production code path:
  1. OSM building footprint via Overpass (`building_footprints.py`) — **the U-Net segmenter
     (`app/pipeline/segmenter.py`, `app/models/unet.py`) exists but is NOT called** (dead code).
  2. Aerial imagery: NAIP via Microsoft Planetary Computer STAC (`imagery/naip.py`), **Mapbox
     Static API fallback** (`imagery/mapbox.py:14-53`, called from `imagery/fetcher.py:23` only when
     NAIP returns None).
  3. LiDAR via USGS 3DEP EPT through **PDAL** (`imagery/elevation.py`, `pipeline/lidar.py:13-24`).
- **LiDAR is NOT disabled by an env var or code flag** (this corrects the prior-review assumption).
  It degrades **silently by dependency**: `fetch_3dep()` returns `None` if PDAL isn't installed or
  `< MIN_LIDAR_POINTS` (100, `config.py:19`) points come back. When None → **basic tier** (footprint
  area only, `pitch=None`, no edges, `waste_factor=None`, confidence 0.70). When present → **full
  tier** (RANSAC plane-fit facets, per-facet pitch, ridge/valley/hip/rake/eave edge lengths, waste
  factor, confidence 0.85). So the reason pitch/edges are "missing" in practice is **PDAL not being
  installed in the image** — a packaging problem, not a feature flag.
- **Outputs (full tier):** `roof_area_sqft`, `roof_area_squares` (= sqft/100), `num_facets`,
  `num_structures`, `waste_factor`, `confidence_score`; per-facet `area_sqft`/`pitch`/`pitch_degrees`/
  `orientation`/`polygon`; per-edge `edge_type`/`length_ft`/`geometry`
  (`pipeline/measurer.py:48-73`, `plane_fitter.py:269-281`, `edge_extractor.py:93-102`).
- **Deps** (`ml-service/requirements.txt`): fastapi, celery[redis], psycopg2, minio, **torch 2.5 +
  torchvision** (only used by the dead segmenter), **open3d 0.18** (RANSAC/geometry — real),
  **rasterio 1.4** (NAIP COG reads — real), shapely, scipy, reportlab (PDF). Base image
  `ghcr.io/osgeo/gdal:ubuntu-small-3.9.3`; **PDAL is NOT installed** in the Dockerfile. Worker memory
  limit is **6Gi**. Full image ≈ 2.5–3 GB.

### 2.1 Immediate consequences for the port
- **torch/torchvision + segmenter + U-Net weights can be dropped entirely** — they are dead code.
  Removing them cuts ~800 MB–1 GB off the image and eliminates the only GPU-shaped dependency.
  **This means the ml-service is CPU-only.** (Decision D3, §11 — confirm we drop the segmenter.)
- **open3d + rasterio + GDAL + (new) PDAL** stay. These are the heavy native deps. open3d on CPU is
  fine; PDAL must be **added to the base image** to make the full (pitch/edge) tier actually work.
- Redis/Celery/MinIO/its-Postgres all go away (§4).

---

## 3. Target architecture in this platform

```
web/Squares.tsx ──(Firebase ID token)──► api (Cloud Run, existing)
                                             │
     1. POST /measurements/geocode  ─────────┤  address → {lat,lon,formatted}
     2. POST /measurements/footprint ────────┤  lat/lon → OSM footprint preview (confirm)
     3. POST /measurements/measure  ─────────┤  creates measurements row (status=pending),
                                             │  then calls ml-service (IAM S2S), polls,
                                             │  updates row with results (tenant-stamped)
                                             ▼
                             ml-service (NEW Cloud Run service, private)
                             /measure  (sync compute; OSM+NAIP[+PDAL LiDAR] → JSON)
                             no DB, no MinIO, no redis — pure function over lat/lon
```

- The ml-service is deployed **`--no-allow-unauthenticated`** (private). Only `api-run-sa` gets
  `roles/run.invoker` on it. `api` mints an OIDC ID token for the ml-service audience and calls it
  (pattern in §5).
- **All `measurements` writes happen in `api` under `get_db_session`**, so the row is stamped with
  the caller's verified `tenant_id` and RLS is enforced exactly as it is for manual entry today.

### 3.1 Sync-with-poll vs. Cloud Run Job vs. Celery — recommendation

**Recommendation: Cloud Run *service* with a synchronous `/measure` endpoint, called by `api` as a
background task, with the `measurements` row acting as the job record the UI polls.** Rationale:

- A single measurement is **seconds-to-low-minutes** (Overpass + one NAIP COG window read + optional
  PDAL EPT query + open3d RANSAC on one property). It fits inside a Cloud Run request. No queue needed
  for launch volume (one contractor, low QPS).
- We already have the **poll primitive for free**: the UI polls `GET /measurements/{id}` and watches
  `status` go `pending → complete|failed` — mirroring how eaglepoint's own `reports.status` worked,
  but on **our** table. No Celery, no Redis, no result backend.
- Cloud Run **Jobs** are the wrong tool: Jobs are for batch/scheduled fan-out (like our ingest/render
  jobs), not request-scoped compute that returns a value to a waiting UI. Using a service keeps the
  request/response contract clean and the IAM binding is `run.invoker` (simpler than the
  `run.developer` + `serviceAccountUser` act-as dance the Jobs use at `infra/main.tf:173-185`).
- To avoid holding an `api` request open for the whole compute, `api` runs the ml-service call in a
  FastAPI `BackgroundTask` (or a short-lived thread): the `POST /measurements/measure` returns
  `{id, status:"pending"}` immediately after inserting the row; the background task calls the
  ml-service, then re-opens a stamped session to write results. **The background task must re-stamp
  tenant** (it runs outside the request's session) — see §6.3, this is the top idempotency/tenancy risk.

**Downside to flag (D5):** Cloud Run request timeout caps the sync compute. We set the ml-service
`timeout` to 900s (same as `api`). If a property ever exceeds that (huge parcel, slow EPT), the
call fails and the row goes `status=failed` with a retry affordance. If real-world p99 turns out to
breach this, we escalate to a Cloud Tasks queue in a later wave — but we do **not** build that
speculative machinery now (YAGNI).

---

## 4. Porting the ml-service (R3 IaC)

### 4.1 Code changes to the vendored ml-service
Vendor the engine under `ml-service/` in this repo (new top-level dir), then:

1. **Amputate persistence.** Replace `POST /jobs` (which writes DB/MinIO) with a new
   `POST /measure` that runs the orchestrator and **returns the measurement dict as the HTTP
   response**. Delete/skip `app/db.py` writes, MinIO upload, and PDF/overlay generation for v1
   (the platform doesn't need eaglepoint's PDF — our proposal PDF is separate). Overlay PNG can
   return as a signed-GCS-URL in a later wave; **descope for v1** (D6).
2. **Drop dead ML.** Remove `torch`, `torchvision`, `segmentation-models-pytorch` from
   `requirements.txt`; delete `app/pipeline/segmenter.py`, `app/models/unet.py`, training
   checkpoints. Confirm nothing in `orchestrator.py` imports them (it doesn't call them today).
3. **Config via env, not defaults.** Keep `MAPBOX_ACCESS_TOKEN`, `MIN_LIDAR_POINTS`,
   `PROPERTY_BBOX_SIZE_M`; drop `DATABASE_URL`, `REDIS_URL`, all `MINIO_*`, `USE_CELERY`.
4. **Request/response contract** (the api↔ml-service seam):
   - Request: `{ "lat": float, "lon": float, "address": str|null }`.
   - Response: `{ tier: "full"|"basic", roof_area_sqft, roof_area_squares, num_facets,
     num_structures, waste_factor|null, confidence_score, pitch_primary|null, facets:[...],
     edges:[...], imagery:{source,gsd,capture_date}, footprint_geojson }`.
   - `pitch_primary` = area-weighted or dominant facet pitch, derived in the ml-service so `api`
     doesn't need geometry logic.

### 4.2 New Dockerfile (ml-service)
- Base: `ghcr.io/osgeo/gdal:ubuntu-small-3.9.3` (already proven for rasterio/GDAL) **plus PDAL**:
  install `pdal` + `python3-pdal` via apt (PDAL is in Debian/Ubuntu repos) so the **full LiDAR tier
  actually runs** — this is the fix for the "pitch silently missing" defect (§ D1). If the apt PDAL
  is too old for the EPT reader, fall back to a `condaforge/mambaforge` base with `pdal python-pdal`
  from conda-forge (heavier but reliable). **Flag D2:** base-image choice (apt-PDAL vs conda-PDAL) is
  a build-reliability tradeoff to settle during Wave 1 spike.
- CPU-only. Target image ~1.2–1.6 GB after dropping torch.
- `CMD uvicorn app.main:app --host 0.0.0.0 --port 8080` (match platform PORT convention).

### 4.3 Terraform (mirror existing patterns in `infra/main.tf`)
Add to `infra/` (new file `infra/ml_service.tf` for clarity):

- `google_service_account.ml_run_sa` (mirror `api-run-sa`, `infra/main.tf:100-116`).
- `google_cloud_run_v2_service "ml_service"` mirroring the `api` service block
  (`infra/main.tf:394-438`): `service_account = ml_run_sa`, `max_instance_count` small (2),
  `resources.limits = { cpu = "4", memory = "6Gi" }` (open3d RANSAC + rasterio windows; matches
  eaglepoint's 6Gi worker), `timeout = "900s"`, and **`ignore_changes` on `image`** (deployed by
  `deploy.sh`, same convention as `api`).
- **Private invoke binding:** `google_cloud_run_v2_service_iam_member` granting
  `roles/run.invoker` on `ml_service` to `serviceAccount:api-run-sa@…`. No public access.
- **Secret:** `google_secret_manager_secret "mapbox_access_token"` (+ version) if we keep Mapbox
  (see D4); wired to ml-service via `deploy.sh --set-secrets`. If we drop Mapbox, no secret.
- **Egress:** ml-service needs outbound internet (Overpass, Planetary Computer, USGS S3). Default
  Cloud Run egress is fine; no VPC connector required unless we later pin egress IPs.

### 4.4 Deploy (R3 — no manual deploys)
Extend `scripts/deploy.sh` to build+push the ml-service image
(`${REGION}-docker.pkg.dev/${PROJECT}/app/ml-service:${git_sha}`) and `gcloud run deploy ml-service
--no-allow-unauthenticated --service-account ml-run-sa@… --cpu 4 --memory 6Gi --timeout 900`. Commit
before deploy (dirty-tree refusal already enforced). Then `scripts/drift_check.sh` must be clean (R4).

---

## 5. API seam (our `api` → ml-service, IAM S2S)

New adapter `adapters/ml_service.py` (adapters are coverage-omitted but need a behavioral validation
per R1):

```python
# Cloud Run service-to-service: mint an OIDC ID token for the ml-service audience.
import google.auth.transport.requests
import google.oauth2.id_token
import requests

ML_URL = os.environ["ML_SERVICE_URL"]  # https://ml-service-xxxx.run.app

def measure(lat: float, lon: float, address: str | None) -> dict:
    auth_req = google.auth.transport.requests.Request()
    token = google.oauth2.id_token.fetch_id_token(auth_req, ML_URL)  # audience = service URL
    r = requests.post(f"{ML_URL}/measure",
                      headers={"Authorization": f"Bearer {token}"},
                      json={"lat": lat, "lon": lon, "address": address},
                      timeout=890)
    r.raise_for_status()
    return r.json()
```

- `ML_SERVICE_URL` is injected as an env var by `deploy.sh` (from the TF output of the ml-service
  URL). This mirrors how the api already uses ADC/`google.auth.default()` in `adapters/gcp_logging.py`.
- The ID token audience is the ml-service base URL — Cloud Run validates it against the
  `run.invoker` binding. This is the first real S2S call in the repo; document it in the adapter.

---

## 6. Tenancy, persistence & the measurements table (RLS)

### 6.1 Schema — new migration `infra/migrations/0024_measurements_squares.sql`
The `measurements` table already exists (`0015_estimates_hash.sql:29-51`) with RLS FORCE'd
(`0018_rls_gcip.sql`) and columns `total_sq, hips_lf, ridges_lf, valleys_lf, rakes_lf, eaves_lf,
wall_flashings_lf, pitch_primary, segments_json JSONB, confidence, raw_payload JSONB,
provenance_note`. It already maps cleanly to eaglepoint outputs. Additive changes only
(`ADD COLUMN IF NOT EXISTS`, next sequential number after `0023`):

- `address VARCHAR`, `lat NUMERIC(9,6)`, `lon NUMERIC(9,6)` — the geocoded input for provenance.
- `tier VARCHAR` — `'full' | 'basic'` (records whether LiDAR pitch was available).
- `imagery_source VARCHAR`, `imagery_captured_at DATE` — NAIP freshness (shown in UI).
- No new table needed. `segments_json` holds facets; `raw_payload` holds the full ml-service
  response (audit); edges/facets go in `segments_json` or a sibling `edges_json` (add
  `edges_json JSONB`). `provider` column already exists → set `provider='squarequote'` for these
  rows (vs `'manual'`).
- **RLS is inherited** — the table is already `FORCE ROW LEVEL SECURITY` with
  `tenant_isolation` policy; new columns need no policy change. Confirm the policy is `FOR ALL`.

### 6.2 API routes — new `api/routes/measurements.py` additions (extend existing file)
All tenant-scoped via `Depends(get_db_session)` + `Depends(require_role("estimating_manage"))`,
matching the existing `create_measurement` at `measurements.py:55-99`:

- `POST /measurements/geocode` `{address}` → `{lat, lon, formatted_address}`. Geocoder choice is
  **D7** (Google Geocoding API vs. Nominatim/OSM). Recommend Google Geocoding (we're already in GCP;
  one API key in Secret Manager) for reliability; Nominatim has a heavy-use ToS.
- `POST /measurements/footprint` `{lat, lon}` → OSM footprint GeoJSON for the confirm step (thin
  proxy to ml-service `/footprint`, or fold into `/measure` with a `preview` flag).
- `POST /measurements/measure` `{lat, lon, address}` →
  1. Insert `Measurement(tenant_id=db.info["tenant_id"], provider="squarequote",
     status="pending", address=…, lat=…, lon=…, created_by=email)`; `flush()`; capture `id`.
  2. Schedule background task to call `adapters.ml_service.measure(...)` and write results.
  3. Return `{id, status:"pending"}` immediately.
- `GET /measurements/{id}` already exists (`measurements.py`) — the UI polls it; returns `status`,
  `total_sq`, `tier`, etc.

### 6.3 CRITICAL: background task must re-stamp tenant (top risk)
The background task runs **outside** the request's `get_db_session` transaction. It must open a fresh
`SessionLocal()` and set `db.info["tenant_id"] = <captured tenant_id>` **before the first query**, so
the `after_begin` event (`core/tenant.py:80-159`) issues `SET LOCAL app.tenant_id` and RLS lets the
`UPDATE` through. If we forget, the non-strict production contract defaults to tenant 1 and logs
CRITICAL (`core/tenant.py:99-113`) — a silent cross-tenant write for tenant≠1. **The plan mandates:
capture `tenant_id` into the closure at request time, re-stamp in the task, and add a negative test
that a task stamped with tenant B cannot update tenant A's row.** This is the single most important
correctness gate in the wave (R2 critic must verify it).

### 6.4 Estimator handoff (the "Use in Estimate" seam)
`api/routes/estimator.py:67` already declares `measurement_id: Optional[int] = None` but the `quote()`
body (lines 78-173) **never reads it** (verified). Wire it:

- In `quote()`, if `body.measurement_id` is set and `num_squares` not explicitly overridden: load the
  `Measurement` (RLS-guarded `db.get`), and prefill `q.num_squares = measurement.total_sq`,
  `q.pitch_7_12`/pitch from `measurement.pitch_primary`, etc. Keep explicit request fields as
  overrides (user can edit after prefill). Record `measurement_id` in the persisted `Estimate.input_json`
  for provenance.
- This is a **`core/` change** (prefill/merge logic belongs in a small pure helper so it's covered
  under the 100% gate), with the route doing only the load + call.

---

## 7. Imagery & the Mapbox ToS question

- **Primary path is NAIP** (public-domain USGS aerial via Microsoft Planetary Computer, no key, no ToS
  problem). Mapbox is **only a fallback** when NAIP has no coverage (`imagery/fetcher.py:23`).
- **Mapbox ToS risk** = its static-tiles are licensed for interactive display, and caching/deriving
  measurements from them is a grey area. **Recommendation (D4): drop the Mapbox fallback for v1.** When
  NAIP is unavailable, return `tier="basic"` with an explicit "imagery unavailable for automated
  measurement — enter squares manually" state, which routes the user to the existing manual-entry path.
  NAIP covers CONUS well; Miami (the launch branch) is fully covered. This removes the ToS exposure and
  a secret entirely. If a licensed high-res source is wanted later, evaluate **NearMap/EagleView
  (paid, measurement-licensed)** or Google's aerial — a separate decision, not this wave.

---

## 8. LiDAR / pitch defect — fix vs. descope

The defect: pitch/edges are absent in practice because **PDAL isn't in the image**, so `fetch_3dep()`
always returns None and every report degrades to basic tier.

**Recommendation: FIX it in Wave 1 by installing PDAL** (§4.2), because pitch materially changes the
squares number — 3D surface area = footprint / cos(pitch), so a 6/12 roof is ~12% larger than its
flat footprint, and steeper roofs diverge more. Shipping "squares" that are really flat-footprint
area would systematically **under-quote** every sloped roof. That's a correctness problem for the core
value prop, not a nice-to-have.

**Fallback descope (if PDAL packaging proves painful in Wave 1 spike):** ship **basic tier only** for
v1, but then the UI must (a) label the number "footprint squares (flat) — pitch not included",
(b) expose a **manual pitch multiplier** so the estimator can gross-up, and (c) set
`confidence=0.70`. This is the explicit accuracy tradeoff to flag to Jon (**D1**): fixed-pitch full
tier vs. flat-footprint basic tier with manual pitch entry. Recommendation is to **fix**, with the
descope as the schedule-relief escape hatch.

---

## 9. Web UI — `web/src/pages/Squares.tsx`

Replace the placeholder (`web/src/pages/Squares.tsx`, currently a 21-line stub) with the flow, using
the existing `apiFetch` client (`web/src/api.ts:91-128`, Firebase-token'd) and the form/results
patterns from `web/src/pages/Estimator.tsx`:

1. **Address input** → `POST /measurements/geocode` → show map pin / formatted address.
2. **Footprint confirm** → `POST /measurements/footprint` → render the OSM polygon over NAIP;
   user confirms it's the right building (Overpass can pick a neighbor).
3. **Measure** → `POST /measurements/measure` → get `{id}`, then **poll `GET /measurements/{id}`**
   every ~2s until `status` is `complete|failed`. Show tier badge (full/basic), squares, pitch,
   waste factor, imagery capture date + freshness note.
4. **"Use in Estimate"** button → navigate to the Estimator tab passing `measurement_id` (route
   state / query param, mirroring existing tab routing), which triggers the §6.4 prefill so
   `num_squares` and pitch land pre-filled. User reviews and calculates the quote.

Failure/edge states to design: geocode miss, wrong footprint, `tier="basic"` (no pitch → prompt
manual pitch), ml-service timeout (`status=failed` + retry).

---

## 10. Wave sequencing (TDD, R1 coverage, R2 review, R4 drift per wave)

Each wave ends with: `pytest --cov=core --cov-fail-under=100` green **+** a behavioral validation for
new I/O (R1), architect+critic deep review with HIGH findings fixed (R2), `ruff check` clean,
Terraform/Ansible applied from git, `scripts/drift_check.sh` clean (R4), committed on the platform
branch. TDD: write the failing test first for every `core/` unit (§ superpowers TDD).

**Wave S0 — Spike & decisions (small, ~0.5 day).** De-risk the two hard unknowns: (a) build the
ml-service image with PDAL and prove `fetch_3dep()` returns points for a Miami address (settles D1/D2);
(b) confirm NAIP coverage for the launch area (settles D4). Output: go/no-go on full-tier, chosen base
image. No production infra yet. Deliverable is a throwaway spike + a decision note appended here.

**Wave S1 — ml-service ported & deployed (medium, ~1–1.5 days).** Vendor `ml-service/`, amputate
DB/MinIO/celery, drop torch/segmenter, add `POST /measure` returning JSON, new Dockerfile (+PDAL),
Terraform (service + private `run.invoker` binding + SA), extend `deploy.sh`. Validation: a hermetic
`scripts/validate_ml_service.py` that hits `/measure` for a known address and asserts the JSON shape
+ a plausible squares range; drift-check clean. `core/` coverage unaffected (ml-service is its own
image, not under `core/`). Gate: architect/critic on the IAM binding (private), egress, image size.

**Wave S2 — API seam + persistence + tenancy (medium, ~1–1.5 days; HIGHEST-RISK wave).** Add
`adapters/ml_service.py` (S2S OIDC), the three `/measurements/*` routes, migration `0024`, and the
background-task write path with **tenant re-stamping** (§6.3). TDD the pure bits in `core/` (response→
row mapping, pitch/area derivation, prefill/merge helper) to the 100% gate. Behavioral validation:
PG-fixture test proving (i) a measure→poll round-trip writes a tenant-stamped row, and (ii) a
**negative** cross-tenant test that a task stamped tenant B cannot update tenant A's measurement
(mirrors the existing RLS fixture tests, e.g. the `0022` proposals-token policy tests). Gate: critic
must sign off on §6.3 explicitly.

**Wave S3 — Estimator handoff (small, ~0.5 day).** Wire `measurement_id` prefill in
`api/routes/estimator.py` via a pure `core/` merge helper (covered), persist `measurement_id` in
`Estimate.input_json`. Validation: a golden case proving measurement→estimate prefill yields the same
total as passing `num_squares` directly. Gate: architect on the override/precedence rules.

**Wave S4 — Squares.tsx UI + handoff (medium, ~1 day).** Implement the four-step flow, polling,
tier/freshness display, failure states, and the "Use in Estimate" navigation with prefill. Validation:
manual smoke against a deployed stack (web has no coverage gate); a Playwright/e2e happy-path is
optional stretch. Gate: designer/architect review of the flow + error states.

**Rough total: ~4.5–5.5 engineering-days** across S0–S4, dominated by S1 (image/PDAL) and S2
(tenancy correctness). S0 exists specifically to pull the two biggest risks forward.

---

## 11. OPEN DECISIONS FOR JON (flag list — resolve before/at S0)

- **D1 — Pitch accuracy tradeoff (most important).** Fix LiDAR by shipping PDAL (full tier: real
  pitch, squares include slope) vs. descope to basic tier (flat-footprint squares + manual pitch
  multiplier, systematically under-quotes sloped roofs). **Recommend: FIX (full tier).** Cost: image
  size + PDAL packaging effort. Escape hatch: basic-tier-only if S0 spike shows PDAL is unreliable.
- **D2 — ml-service base image.** apt PDAL on the GDAL base (light, maybe-old) vs. conda-forge
  `python-pdal` (heavier, reliable). Settle in S0. Affects image size/build reliability, not features.
- **D3 — Drop the dead U-Net/torch stack?** Recommend yes (dead code, ~800 MB–1 GB, only GPU-shaped
  dep). Confirms the ml-service is **CPU-only** (no GPU cost). If Jon wants to keep CV as a future
  footprint source, we keep it out of the runtime image regardless.
- **D4 — Mapbox fallback.** Recommend **drop it** for v1 (ToS grey area on deriving measurements;
  removes a secret). NAIP-only; basic/manual state when NAIP missing. Alternative: license NearMap/
  EagleView later. This is an imagery-licensing call.
- **D5 — Sync-with-poll timeout.** 900s Cloud Run request cap on `/measure`. Recommend accept for
  launch volume; escalate to Cloud Tasks only if real p99 breaches it. (Do not build the queue now.)
- **D6 — PDF/overlay output.** eaglepoint generates a ReportLab PDF + facet overlay PNG. Recommend
  **descope for v1** (our proposal PDF is separate). Later: return overlay as a signed GCS URL.
- **D7 — Geocoder.** Google Geocoding API (recommend; in-GCP, one keyed secret) vs. Nominatim/OSM
  (free, heavy-use ToS). Cost: Google geocoding is ~$5/1k after free tier — negligible at this volume.
- **D8 — GPU cost.** With D3 (drop torch) there is **no GPU** anywhere in this integration; open3d
  RANSAC and PDAL run on CPU. Confirming this closes the "GPU cost" question from the brief: expected
  incremental cost is a small always-warm-to-zero Cloud Run CPU service + NAIP/Overpass egress + the
  geocoding API — no accelerator spend.

---

## 12. Explicit non-goals for this integration (YAGNI guardrails)

- No second Postgres, no MinIO/object-store for measurements, no Redis/Celery, no Cloud Tasks queue
  (unless D5 forces it later).
- No eaglepoint web app, no eaglepoint PDF pipeline in v1 (D6).
- No U-Net/CV footprint path (D3) — OSM footprints only.
- No new tenancy mechanism — reuse `get_db_session` + the RLS-forced `measurements` table verbatim;
  the only new tenancy surface is the background-task re-stamp (§6.3), which is a **reuse** of the
  existing `after_begin` stamping, not a new path.
```
