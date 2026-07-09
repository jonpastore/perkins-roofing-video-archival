# TRD-F2b — Measurement Service (Google Solar API + Manual Entry)

**Wave:** F2b  
**Date:** 2026-07-08  
**Status:** DRAFT (R2 fixes applied — pending Jon approval)  
**Depends on:** TRD-F2 migration `0015_estimates_hash.sql` (CREATE TABLE measurements stub) — migration 0016 is an ALTER on that table and cannot run before 0015. F2b is NOT parallel to F2 at the migration layer; it begins after 0015 is applied. Code work (provider protocol, Solar adapter) can proceed in parallel with F2 code; the migration gate is sequential.  
**Grounding:** full-funnel plan §5 items 7–8, §9 F2b row; CONTINUATION-2026-07-08 §3 locked decisions; `perkins-squarequote-review` memory; `perkins-ezbids-proposal` memory (Exhibit C Scenario 5); TRD-F2 §2.3 (measurement stub).

---

## 1. Scope

### In scope
- `Measurement` model: total SQ, hip/ridge/valley/rake/eave/wall-flashing linear feet, per-segment pitch/azimuth/area; provider + confidence + raw payload retained.
- `MeasurementProvider` Protocol (Python `typing.Protocol`): standard interface any provider implements.
- `GoogleSolarProvider`: primary production provider using the Google Maps Platform Solar API (`buildingInsights` endpoint). Derives edge lengths from segment geometry. Documented API quotas, pricing, and the Terraform resource for API enablement.
- `ManualEntryProvider`: first-class, clearly-labeled provider. Never silently substituted for a failed automated provider. Provenance stamped on every measurement and every estimate derived from it.
- Address-to-geocode-to-Solar-API flow, including failure modes (no coverage, low quality score, API error) and the manual fallback UX.
- Validation exit gate: Solar API adapter tested against real Perkins property addresses before F2b is declared done.
- Migration: `0016_measurements_solar.sql` (extends the stub table added in migration 0015 with Solar-specific columns).
- API endpoints for creating, fetching, and status-polling measurements; wiring measurement_id into the estimate endpoint.
- Rollout and rollback.

### Non-goals (F2b)
- Nearmap / Vexcel oblique imagery integration — the provider interface accommodates it; it is not built here.
- SquareQuote / eaglepoint source integration — the code at `~/projects/eaglepoint` is **reference only** for understanding the measurement model shape. Its source is never imported into this repo (IP separation, confirmed decision). The eaglepoint ml-service is a separate project; no merge.
- LiDAR / USGS 3DEP / PDAL pipeline — explicitly dropped (Jon's direction, 2026-07-08).
- U-Net CV model — dead code in eaglepoint; not reproduced here.
- Mapbox persistence or Google Earth scraping — ToS-prohibited; not built.
- Drone imagery — non-goal globally.
- Native iOS measurement capture (non-goal globally in v1).
- Asynchronous job queue (Cloud Tasks) for Solar requests — the flow is synchronous in F2b (acceptable at single-tenant volume); async queued+notify is the F5 hardening path.

---

## 2. Data model

### 2.1 `measurements` (full schema — extends stub from migration 0015)

```sql
-- Columns added in migration 0016 on top of the stub created in 0015.
ALTER TABLE measurements
    ADD COLUMN IF NOT EXISTS address_input      VARCHAR,
    ADD COLUMN IF NOT EXISTS geocoded_lat       NUMERIC(10,7),
    ADD COLUMN IF NOT EXISTS geocoded_lng       NUMERIC(10,7),
    ADD COLUMN IF NOT EXISTS geocode_source     VARCHAR,        -- "google_geocoding" | "manual_coords"
    ADD COLUMN IF NOT EXISTS solar_building_id  VARCHAR,        -- Google Solar buildingInsightsId
    ADD COLUMN IF NOT EXISTS solar_quality      VARCHAR,        -- "HIGH" | "MEDIUM" | "LOW" | null
    ADD COLUMN IF NOT EXISTS segments_count     INTEGER,
    ADD COLUMN IF NOT EXISTS primary_pitch_deg  NUMERIC(5,2),   -- pitch in degrees (Solar native)
    ADD COLUMN IF NOT EXISTS primary_pitch_ratio NUMERIC(5,2),  -- derived rise/run (e.g. 4.0 for 4/12)
    ADD COLUMN IF NOT EXISTS total_area_sqft    NUMERIC(10,2),  -- sum of all segment areas
    ADD COLUMN IF NOT EXISTS error_code         VARCHAR,        -- "NO_COVERAGE" | "LOW_QUALITY" | "API_ERROR" | null
    ADD COLUMN IF NOT EXISTS error_message      TEXT;
```

Full column set after both migrations:

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `tenant_id` | INTEGER FK tenants | |
| `property_id` | INTEGER nullable | FK to properties (F3); null in F2b |
| `provider` | VARCHAR | "manual" \| "google_solar" \| "nearmap" |
| `status` | VARCHAR | "pending" \| "complete" \| "failed" |
| `address_input` | VARCHAR | raw address string used for geocoding |
| `geocoded_lat` | NUMERIC(10,7) | |
| `geocoded_lng` | NUMERIC(10,7) | |
| `geocode_source` | VARCHAR | "google_geocoding" \| "manual_coords" |
| `solar_building_id` | VARCHAR | buildingInsightsId from Solar API |
| `solar_quality` | VARCHAR | quality tier from Solar response |
| `total_sq` | NUMERIC(10,2) | **Total squares (area / 100 sqft)** |
| `hips_lf` | NUMERIC(10,2) | hip ridge linear feet |
| `ridges_lf` | NUMERIC(10,2) | |
| `valleys_lf` | NUMERIC(10,2) | |
| `rakes_lf` | NUMERIC(10,2) | perimeter rake edges |
| `eaves_lf` | NUMERIC(10,2) | |
| `wall_flashings_lf` | NUMERIC(10,2) | |
| `pitch_primary` | NUMERIC(5,2) | dominant pitch rise/run |
| `primary_pitch_deg` | NUMERIC(5,2) | Solar native degrees |
| `primary_pitch_ratio` | NUMERIC(5,2) | derived ratio |
| `total_area_sqft` | NUMERIC(10,2) | raw sqft before waste |
| `segments_count` | INTEGER | number of roof segments |
| `segments_json` | JSONB | per-segment detail (see §3.2) |
| `confidence` | NUMERIC(4,3) | 0.0–1.0; null for manual |
| `raw_payload` | JSONB | full provider API response |
| `provenance_note` | VARCHAR | "Manual entry by user@x.com on 2026-07-08" |
| `error_code` | VARCHAR | null if success |
| `error_message` | TEXT | null if success |
| `created_at` | TIMESTAMPTZ | |
| `created_by` | VARCHAR | email from auth claims |

### 2.2 `segments_json` structure

Each element in `segments_json` corresponds to one `RoofSegmentSizeAndSunshineStats` entry from the Solar API:

```json
[
  {
    "segment_index": 0,
    "pitch_degrees": 18.4,
    "pitch_ratio": 4.0,
    "azimuth_degrees": 180.0,
    "area_sqft": 850.0,
    "area_sq": 8.5,
    "derived_edges": {
      "ridge_lf": 30.0,
      "eave_lf": 32.0,
      "rake_lf_left": 18.0,
      "rake_lf_right": 18.0,
      "hip_lf": 0.0,
      "valley_lf": 0.0
    },
    "bounding_box": {
      "sw": {"lat": 26.123456, "lng": -80.123456},
      "ne": {"lat": 26.124567, "lng": -80.122345}
    }
  }
]
```

The `derived_edges` block is computed by `core/measurement.py:derive_edges_from_segment()`, not supplied by the Solar API directly. See §3.3 for the derivation algorithm.

---

## 3. Provider mechanics

### 3.1 MeasurementProvider Protocol

```python
# core/measurement.py

from typing import Protocol, runtime_checkable
from dataclasses import dataclass

@dataclass
class MeasurementInput:
    """Inputs common to all providers."""
    address: str                    # full street address
    lat: float | None = None        # if already geocoded
    lng: float | None = None
    manual_sq: float | None = None  # ManualEntryProvider only
    manual_edges: dict | None = None

@dataclass
class MeasurementResult:
    provider: str
    status: str                     # "complete" | "failed"
    total_sq: float | None
    hips_lf: float | None
    ridges_lf: float | None
    valleys_lf: float | None
    rakes_lf: float | None
    eaves_lf: float | None
    wall_flashings_lf: float | None
    pitch_primary: float | None
    segments: list[dict]            # raw segment detail
    confidence: float | None
    raw_payload: dict
    provenance_note: str
    error_code: str | None = None
    error_message: str | None = None

@runtime_checkable
class MeasurementProvider(Protocol):
    provider_name: str              # class attribute

    def measure(self, inp: MeasurementInput) -> MeasurementResult:
        """Synchronous. Raises no exceptions — encodes errors in MeasurementResult."""
        ...

    def is_available(self) -> bool:
        """Returns False if the provider's credentials/config are absent."""
        ...
```

`is_available()` returning False does not trigger a silent fallback. The caller (the API endpoint) checks availability and returns a clear error to the client if the requested provider is unavailable, prompting the user to choose manual entry explicitly.

### 3.2 GoogleSolarProvider

**API used:** Google Maps Platform Solar API — `buildingInsights` endpoint.

```
GET https://solar.googleapis.com/v1/buildingInsights:findClosest
    ?location.latitude={lat}
    &location.longitude={lng}
    &requiredQuality=LOW
    &key={SOLAR_API_KEY}
```

**Key fields extracted from response:**

| Solar API field | Our use |
|---|---|
| `solarPotential.roofSegmentStats[].pitchDegrees` | per-segment pitch |
| `solarPotential.roofSegmentStats[].azimuthDegrees` | per-segment azimuth |
| `solarPotential.roofSegmentStats[].stats.areaMeters2` | per-segment area |
| `solarPotential.roofSegmentStats[].boundingBox` | bounding box for edge derivation |
| `solarPotential.wholeRoofStats.areaMeters2` | total area cross-check |
| `imageryQuality` | quality gate (see §3.4) |
| `name` | buildingInsightsId (stored as `solar_building_id`) |

**Area conversion:**

```
area_sqft = area_meters2 × 10.7639
area_sq   = area_sqft / 100
```

**Total squares:** sum of `area_sq` across all segments, rounded to 2 decimal places. Cross-checked against `wholeRoofStats.areaMeters2` — if they differ by more than 2%, log a warning in the response but do not fail (Solar's own segment stats may not sum exactly to whole-roof stats).

**Dominant pitch:** segment with the largest `area_meters2` wins; its `pitchDegrees` is `primary_pitch_deg`.

**Pitch conversion:**

```
pitch_ratio = tan(pitch_degrees × π/180) × 12
```

Rounded to 1 decimal. Example: 18.43° → `tan(18.43° × π/180) × 12 ≈ 4.0` (4/12 pitch).

### 3.3 Edge derivation from segment geometry

The Solar API does not supply linear edge lengths directly. We derive them from each segment's bounding box and pitch. This is the improvement over eaglepoint's broken centroid-to-centroid approach.

**Algorithm (`core/measurement.py:derive_edges_from_segment`):**

```python
def derive_edges_from_segment(segment: dict) -> dict:
    """
    Derive ridge, eave, and rake lengths from Solar API segment bounding box.

    Assumptions:
      - Segment bounding box SW/NE corners give approximate rectangle footprint.
      - azimuth_degrees identifies the downslope direction (eave faces azimuth).
      - Width (perpendicular to slope run direction) = eave/ridge length.
      - Depth (along slope run direction, as footprint projected) = rake run.
      - Actual rake length = footprint_depth / cos(pitch_degrees × π/180).
      - For a simple gable: eave_lf ≈ ridge_lf ≈ box_width.
      - Hip detection: not attempted from bounding box alone; hips estimated from
        segment adjacency (see below).

    Limitations (documented, not hidden):
      - Bounding box is axis-aligned; diagonal roof orientations introduce error.
      - Accuracy: ±10–15% on rake/eave for non-orthogonal roofs.
      - Complex roofs (dormers, L-shapes) need manual override or a paid provider.
    """
    bb = segment["bounding_box"]
    sw_lat, sw_lng = bb["sw"]["lat"], bb["sw"]["lng"]
    ne_lat, ne_lng = bb["ne"]["lat"], bb["ne"]["lng"]

    # Approximate metric dimensions (1 deg lat ≈ 111,139 m; 1 deg lng ≈ 111,139 × cos(lat) m)
    avg_lat_rad = math.radians((sw_lat + ne_lat) / 2)
    ns_m = abs(ne_lat - sw_lat) * 111139
    ew_m = abs(ne_lng - sw_lng) * 111139 * math.cos(avg_lat_rad)

    azimuth = segment["azimuth_degrees"]
    pitch_rad = math.radians(segment["pitch_degrees"])

    # Width and depth relative to slope direction
    az_rad = math.radians(azimuth % 180)  # fold to 0–180
    width_m  = abs(ew_m * math.cos(az_rad)) + abs(ns_m * math.sin(az_rad))
    depth_m  = abs(ew_m * math.sin(az_rad)) + abs(ns_m * math.cos(az_rad))

    # Convert to feet
    M_TO_FT = 3.28084
    eave_lf  = width_m * M_TO_FT
    ridge_lf = eave_lf                  # simple gable assumption; hip segments set ridge=0 below
    rake_lf  = (depth_m / math.cos(pitch_rad)) * M_TO_FT if pitch_rad > 0 else depth_m * M_TO_FT

    return {
        "ridge_lf":       round(ridge_lf, 1),
        "eave_lf":        round(eave_lf, 1),
        "rake_lf_left":   round(rake_lf / 2, 1),
        "rake_lf_right":  round(rake_lf / 2, 1),
        "hip_lf":         0.0,          # hip detection not available from bounding box alone
        "valley_lf":      0.0,          # valley detection not available from bounding box alone
        "_derivation_note": "bounding-box approximation; ±10-15% on non-orthogonal roofs"
    }
```

**Aggregation across segments:**

After deriving edges per segment:
- `ridges_lf` = sum of `ridge_lf` (shared ridges between adjacent segments are counted once — deduplicated by checking segment adjacency from bounding box overlap)
- `eaves_lf` = sum of `eave_lf`
- `rakes_lf` = sum of `rake_lf_left + rake_lf_right`
- `hips_lf` = 0 (not derivable from bounding boxes alone; marked in provenance)
- `valleys_lf` = 0 (same limitation)

**Provenance note for Solar measurements:**

```
"Google Solar API measurement (quality: HIGH). Edge lengths are bounding-box approximations
(±10–15% on non-orthogonal roofs). Hips and valleys not available from Solar API geometry —
set manually if needed."
```

This note is stored in `provenance_note` and surfaced in the estimate UI so estimators know the limitations.

### 3.4 Quality gate and failure modes

**Quality filter:**

| `imageryQuality` | Action |
|---|---|
| `HIGH` | Proceed. Store `solar_quality="HIGH"`. |
| `MEDIUM` | Proceed with warning. Store `solar_quality="MEDIUM"`. UI warns estimator. |
| `LOW` | Reject. Set `status="failed"`, `error_code="LOW_QUALITY"`. Prompt manual entry. |
| Field absent | Treat as LOW — reject. |

The `requiredQuality=LOW` query parameter is passed to avoid a 404 response from the API for low-quality buildings (the API still returns data; we then apply our own quality gate in code).

**Failure modes and UX responses:**

| Condition | `error_code` | UI behavior |
|---|---|---|
| Address geocode fails | `GEOCODE_FAILED` | "Address not found — enter coordinates or use manual entry" |
| No Solar coverage | `NO_COVERAGE` | "Roof data not available for this address — use manual entry" |
| Low quality rejected | `LOW_QUALITY` | "Roof imagery quality too low — use manual entry" |
| Solar API HTTP error | `API_ERROR` | "Measurement service temporarily unavailable — use manual entry" |
| API quota exceeded | `QUOTA_EXCEEDED` | "Daily measurement limit reached — use manual entry or try tomorrow" |

None of these silently fall back to manual entry. The user must explicitly choose manual entry. The failed `Measurement` row is retained in the DB (for audit and quota tracking).

### 3.5 ManualEntryProvider

Manual entry is a first-class provider, not a fallback band-aid. It is labeled clearly in the UI as "Manual Entry" and never presented as an automated result.

```python
class ManualEntryProvider:
    provider_name = "manual"

    def measure(self, inp: MeasurementInput) -> MeasurementResult:
        if inp.manual_sq is None:
            raise ValueError("manual_sq required for ManualEntryProvider")
        edges = inp.manual_edges or {}
        return MeasurementResult(
            provider="manual",
            status="complete",
            total_sq=inp.manual_sq,
            hips_lf=edges.get("hips_lf"),
            ridges_lf=edges.get("ridges_lf"),
            valleys_lf=edges.get("valleys_lf"),
            rakes_lf=edges.get("rakes_lf"),
            eaves_lf=edges.get("eaves_lf"),
            wall_flashings_lf=edges.get("wall_flashings_lf"),
            pitch_primary=edges.get("pitch_primary"),
            segments=[],
            confidence=None,
            raw_payload={},
            provenance_note=f"Manual entry by {inp.created_by} on {inp.created_at_date}",
            error_code=None,
            error_message=None,
        )

    def is_available(self) -> bool:
        return True  # always available
```

**Provenance stamp on estimate:** when an estimate is created with `measurement_id` pointing to a manual measurement, the estimate result includes:

```json
"measurement_provenance": "Manual entry by estimator@perkins.net on 2026-07-09"
```

This is displayed in the estimate UI and preserved in the quote snapshot (F3). Exhibit C Scenario 5 requires this: manual entry must be clearly labeled in the final proposal.

### 3.6 Address → geocode → Solar API flow

```
POST /measurements/solar
  body: { address: "123 Main St, Miami FL 33101", branch: "miami" }
  ↓
1. Geocode: Google Maps Geocoding API → (lat, lng)
   - Geocoding API is the same GCP project; same API key group (separate key)
   - Store geocoded_lat, geocoded_lng, geocode_source="google_geocoding"
   ↓
2. Solar API: buildingInsights:findClosest at (lat, lng)
   - Full response stored in raw_payload
   - Quality gate applied (§3.4)
   ↓
3. Process: derive edges per segment, aggregate totals
   ↓
4. Persist: INSERT INTO measurements ... status="complete"
   ↓
5. Response: 201 Created with full measurement JSON
```

If step 1 or 2 fails: persist a `status="failed"` row, return 200 with the failure details (not a 5xx — the failure is a business outcome, not a server error). The client shows the appropriate UX (§3.4 table).

**Geocoding API note:** the Geocoding API is a separate billable Google API from the Solar API. Both are enabled in the same GCP project via Terraform. See §5 (infra).

---

## 4. APIs

All endpoints require `manage_estimates` role (admin, web_admin, sales) unless noted.

### 4.1 Create manual measurement

```
POST /measurements/manual
Body:
{
  "address": "123 Main St, Jupiter FL 33477",   // optional for manual
  "total_sq": 28.0,
  "hips_lf": 0,
  "ridges_lf": 45.0,
  "valleys_lf": 0,
  "rakes_lf": 60.0,
  "eaves_lf": 45.0,
  "wall_flashings_lf": 0,
  "pitch_primary": 4.0,    // rise/run ratio
  "branch": "jupiter"
}

Response 201:
{
  "id": 42,
  "provider": "manual",
  "status": "complete",
  "total_sq": 28.0,
  "provenance_note": "Manual entry by estimator@perkins.net on 2026-07-09",
  ...
}
```

### 4.2 Create Solar measurement

```
POST /measurements/solar
Body:
{
  "address": "123 Main St, Miami FL 33101",
  "branch": "miami"
}

Response 201 (success):
{
  "id": 43,
  "provider": "google_solar",
  "status": "complete",
  "solar_quality": "HIGH",
  "total_sq": 28.5,
  "ridges_lf": 45.2,
  "eaves_lf": 46.1,
  "rakes_lf": 58.8,
  "hips_lf": 0,
  "valleys_lf": 0,
  "pitch_primary": 4.0,
  "segments_count": 3,
  "segments_json": [...],
  "confidence": 0.85,
  "provenance_note": "Google Solar API measurement (quality: HIGH). Edge lengths are bounding-box approximations (±10–15% on non-orthogonal roofs). Hips and valleys not available from Solar API geometry.",
  "pricing_config_hash": null   // set when estimate is created
}

Response 200 (failure — NOT a 5xx):
{
  "id": 44,
  "provider": "google_solar",
  "status": "failed",
  "error_code": "NO_COVERAGE",
  "error_message": "No Solar API coverage for this address. Use manual entry.",
  "total_sq": null
}
```

### 4.3 Get measurement

```
GET /measurements/{id}

Response 200: full measurement row as above.
Response 404: if not found OR belongs to different tenant (404-indistinguishable per F4 requirements; enforced at F4 via RLS, ORM filter in F2b).
```

### 4.4 Wiring to estimate endpoint

The `/estimator/quote` endpoint (TRD-F2 §5.2) accepts `measurement_id`. When provided:

- Fetch the measurement by id (tenant-scoped).
- If `status != "complete"`, return 422 with `"measurement_not_ready"`.
- Auto-populate `num_squares` from `measurement.total_sq`.
- Include `measurement_provenance` in the estimate response.
- The estimate's `pricing_config_hash` is stamped as usual; the `measurement_id` FK is also stored on the estimate row.

The estimator can override `num_squares` in the request body even when `measurement_id` is provided (explicit override wins). This supports the case where an estimator adjusts for waste factor.

---

## 5. Infrastructure (Terraform)

Both APIs (Solar + Geocoding) require GCP API enablement and a dedicated API key. All resources are Terraformed per R3.

### 5.1 APIs to enable

```hcl
# infra/solar_apis.tf

resource "google_project_service" "solar_api" {
  project = var.project_id
  service = "solar.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "geocoding_api" {
  project = var.project_id
  service = "geocoding-backend.googleapis.com"
  disable_on_destroy = false
}
```

### 5.2 API keys

```hcl
resource "google_apikeys_key" "solar_api_key" {
  name         = "solar-measurement-key"
  display_name = "Solar + Geocoding API Key (measurement service)"
  project      = var.project_id

  restrictions {
    api_targets {
      service = "solar.googleapis.com"
    }
    api_targets {
      service = "geocoding-backend.googleapis.com"
    }
    # Server-side key: restrict to Cloud Run service account IP is not feasible with API keys.
    # Mitigation: key stored in Secret Manager, never in env vars logged by Cloud Run.
  }
}

# Key stored in Secret Manager, not in Cloud Run env vars directly.
resource "google_secret_manager_secret" "solar_api_key" {
  secret_id = "solar-api-key"
  project   = var.project_id
  replication { auto {} }
}
```

The Cloud Run service account is granted `roles/secretmanager.secretAccessor` on this secret. The application reads it via Secret Manager SDK at startup (not from environment), consistent with the pattern used for other keys in this project.

### 5.3 Cost notes

**Solar API pricing (as of 2026):**

- `buildingInsights:findClosest`: $0.004 per request (4 mills).
- At 100 measurements/day: ~$0.40/day, $12/month.
- Billing alert: set a quota limit in Terraform (`google_project_service` does not support quota limits directly — add a Cloud Monitoring alert at $20/month spend for this API).

**Geocoding API pricing:**

- Standard Geocoding: $0.005 per request (5 mills).
- Same scale: $0.50/day at 100 requests.

Neither API has a free tier beyond the GCP $200/month credit. Jon must confirm billing is enabled and the Solar API is activated on the GCP project before F2b deploys. Tracked as open item §9.3.

---

## 6. Migrations

### Migration `0016_measurements_solar.sql`

```sql
-- Extends the measurements stub table (created in 0015) with Solar-specific columns.
-- All statements are idempotent (ADD COLUMN IF NOT EXISTS).

ALTER TABLE measurements
    ADD COLUMN IF NOT EXISTS address_input       VARCHAR,
    ADD COLUMN IF NOT EXISTS geocoded_lat        NUMERIC(10,7),
    ADD COLUMN IF NOT EXISTS geocoded_lng        NUMERIC(10,7),
    ADD COLUMN IF NOT EXISTS geocode_source      VARCHAR,
    ADD COLUMN IF NOT EXISTS solar_building_id   VARCHAR,
    ADD COLUMN IF NOT EXISTS solar_quality       VARCHAR,
    ADD COLUMN IF NOT EXISTS segments_count      INTEGER,
    ADD COLUMN IF NOT EXISTS primary_pitch_deg   NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS primary_pitch_ratio NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS total_area_sqft     NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS error_code          VARCHAR,
    ADD COLUMN IF NOT EXISTS error_message       TEXT;

CREATE INDEX IF NOT EXISTS ix_measurements_provider
    ON measurements (tenant_id, provider, status);
```

---

## 7. Test plan (TEST-FIRST — all tests written red before any implementation)

**Fail-first is mandatory.** Write the test, run it, confirm it fails for the right reason, implement minimally, make it green.

### 7.1 Provider protocol conformance tests

```python
# tests/test_measurement_protocol.py

def test_manual_provider_satisfies_protocol():
    assert isinstance(ManualEntryProvider(), MeasurementProvider)

def test_solar_provider_satisfies_protocol():
    assert isinstance(GoogleSolarProvider(api_key="x"), MeasurementProvider)

def test_manual_always_available():
    assert ManualEntryProvider().is_available() is True

def test_solar_unavailable_without_key():
    p = GoogleSolarProvider(api_key=None)
    assert p.is_available() is False

def test_solar_unavailable_empty_key():
    p = GoogleSolarProvider(api_key="")
    assert p.is_available() is False
```

### 7.2 Solar API adapter tests (recorded / mock payloads)

Real API responses are recorded once (during development against real Perkins addresses) and committed to `tests/fixtures/solar/`. All unit tests run against these recorded payloads — no live API calls in CI.

```python
# tests/test_solar_provider.py

FIXTURE_DIR = Path("tests/fixtures/solar")

def test_solar_parse_high_quality(mock_solar_response):
    """HIGH quality response → status=complete, total_sq populated."""
    with patch_solar_api(load_fixture("high_quality_28sq.json")):
        result = GoogleSolarProvider(api_key="test").measure(
            MeasurementInput(address="...", lat=25.7617, lng=-80.1918)
        )
    assert result.status == "complete"
    assert result.total_sq == pytest.approx(28.0, abs=1.0)
    assert result.confidence is not None

def test_solar_rejects_low_quality(mock_solar_response):
    with patch_solar_api(load_fixture("low_quality.json")):
        result = GoogleSolarProvider(api_key="test").measure(
            MeasurementInput(address="...", lat=25.7617, lng=-80.1918)
        )
    assert result.status == "failed"
    assert result.error_code == "LOW_QUALITY"
    assert result.total_sq is None

def test_solar_no_coverage(mock_solar_404):
    """404 from Solar API → NO_COVERAGE, not an exception."""
    result = GoogleSolarProvider(api_key="test").measure(
        MeasurementInput(address="...", lat=0.0, lng=0.0)
    )
    assert result.status == "failed"
    assert result.error_code == "NO_COVERAGE"

def test_solar_api_error_does_not_raise(mock_solar_500):
    """5xx from Solar API → API_ERROR result, not an unhandled exception."""
    result = GoogleSolarProvider(api_key="test").measure(
        MeasurementInput(address="...", lat=25.7617, lng=-80.1918)
    )
    assert result.status == "failed"
    assert result.error_code == "API_ERROR"

def test_solar_stores_raw_payload(mock_solar_response):
    with patch_solar_api(load_fixture("high_quality_28sq.json")):
        result = GoogleSolarProvider(api_key="test").measure(...)
    assert result.raw_payload != {}
    assert "solarPotential" in result.raw_payload

def test_solar_building_id_stored(mock_solar_response):
    with patch_solar_api(load_fixture("high_quality_28sq.json")):
        result = GoogleSolarProvider(api_key="test").measure(...)
    assert result.raw_payload.get("name") is not None  # building ID field

def test_solar_area_conversion_correct():
    """1 m² = 10.7639 sqft; verify conversion for a known segment."""
    segment = {"pitchDegrees": 18.43, "azimuthDegrees": 180.0,
                "stats": {"areaMeters2": 265.16}}
    sq = area_meters2_to_sq(segment["stats"]["areaMeters2"])
    assert sq == pytest.approx(28.53, abs=0.1)

def test_solar_pitch_conversion():
    """18.43° → 4.0/12 pitch."""
    ratio = pitch_degrees_to_ratio(18.43)
    assert ratio == pytest.approx(4.0, abs=0.1)

def test_solar_dominant_segment_is_largest_area():
    segments = [
        {"stats": {"areaMeters2": 100}, "pitchDegrees": 10.0, ...},
        {"stats": {"areaMeters2": 265}, "pitchDegrees": 18.43, ...},
    ]
    pitch = dominant_pitch(segments)
    assert pitch == pytest.approx(18.43)
```

### 7.3 Segment geometry edge-derivation unit tests

```python
# tests/test_edge_derivation.py

def test_simple_rectangle_north_facing():
    """Perfect N-facing 30×20 ft footprint → eave≈30, rake≈20."""
    seg = {
        "pitch_degrees": 18.43,
        "azimuth_degrees": 0.0,
        "bounding_box": {
            "sw": {"lat": 25.7000, "lng": -80.1300},
            "ne": {"lat": 25.7002, "lng": -80.1297},  # ~22m × ~27m box
        }
    }
    edges = derive_edges_from_segment(seg)
    assert edges["eave_lf"] == pytest.approx(88.6, abs=5.0)   # 27m in ft
    assert edges["rake_lf_left"] + edges["rake_lf_right"] > 0

def test_flat_roof_no_pitch_correction():
    """0-degree pitch → rake = footprint depth, no /cos(0) NaN."""
    seg = {
        "pitch_degrees": 0.0,
        "azimuth_degrees": 180.0,
        "bounding_box": {
            "sw": {"lat": 25.7000, "lng": -80.1300},
            "ne": {"lat": 25.7003, "lng": -80.1296},
        }
    }
    edges = derive_edges_from_segment(seg)
    assert math.isfinite(edges["ridge_lf"])
    assert math.isfinite(edges["rake_lf_left"])

def test_derivation_note_in_output():
    """Edge derivation result must carry _derivation_note (provenance)."""
    seg = {"pitch_degrees": 15.0, "azimuth_degrees": 90.0,
           "bounding_box": {"sw": {"lat": 25.7, "lng": -80.1}, "ne": {"lat": 25.701, "lng": -80.099}}}
    edges = derive_edges_from_segment(seg)
    assert "_derivation_note" in edges

def test_aggregate_edges_sums_segments():
    segments_derived = [
        {"ridge_lf": 30.0, "eave_lf": 30.0, "rake_lf_left": 15.0, "rake_lf_right": 15.0,
         "hip_lf": 0.0, "valley_lf": 0.0},
        {"ridge_lf": 20.0, "eave_lf": 20.0, "rake_lf_left": 10.0, "rake_lf_right": 10.0,
         "hip_lf": 0.0, "valley_lf": 0.0},
    ]
    agg = aggregate_edges(segments_derived)
    assert agg["ridges_lf"] == pytest.approx(50.0)
    assert agg["eaves_lf"] == pytest.approx(50.0)
    assert agg["rakes_lf"] == pytest.approx(50.0)
```

### 7.4 Fallback provenance tests

```python
# tests/test_measurement_provenance.py

def test_manual_provenance_note_set():
    p = ManualEntryProvider()
    result = p.measure(MeasurementInput(
        address="123 Main", manual_sq=28.0,
        created_by="est@perkins.net", created_at_date="2026-07-09"
    ))
    assert "Manual entry" in result.provenance_note
    assert "est@perkins.net" in result.provenance_note
    assert "2026-07-09" in result.provenance_note

def test_solar_provenance_note_set(mock_solar_response):
    with patch_solar_api(load_fixture("high_quality_28sq.json")):
        result = GoogleSolarProvider(api_key="test").measure(...)
    assert "Google Solar API" in result.provenance_note
    assert "HIGH" in result.provenance_note
    assert "±10–15%" in result.provenance_note

def test_no_silent_fallback_on_solar_failure(mock_solar_500):
    """Solar failure must NOT silently return manual data."""
    result = GoogleSolarProvider(api_key="test").measure(
        MeasurementInput(address="...", lat=25.76, lng=-80.19)
    )
    assert result.provider == "google_solar"
    assert result.status == "failed"
    assert result.total_sq is None   # not populated with any fallback value

def test_estimate_includes_measurement_provenance(db_session, active_config):
    """Estimate created with manual measurement_id → provenance in response."""
    # created_by is NOT NULL on the measurements stub (migration 0015); must always be supplied.
    m = create_manual_measurement(db_session, total_sq=28.0, created_by="est@perkins.net")
    result = estimate_with_measurement(active_config, m.id, db_session)
    assert "measurement_provenance" in result
    assert "Manual entry" in result["measurement_provenance"]
```

### 7.5 Golden measurement-fed estimates

These mirror the TRD-F2 golden files but exercise the `measurement_id` path:

```python
# tests/test_golden_measurement_fed.py

@pytest.mark.parametrize("fixture_path", GOLDEN_FILES)
def test_golden_measurement_fed(fixture_path, db_session, active_config):
    """measurement_id path → same totals as direct manual input."""
    data = json.loads(fixture_path.read_text())
    # created_by is NOT NULL on the measurements table (migration 0015 stub); always supply it.
    m = create_manual_measurement(
        db_session,
        total_sq=data["input"]["num_squares"],
        created_by="test@perkins.net",
    )
    result = estimate_with_measurement(active_config, m.id, db_session)
    assert abs(result["project_total"] - data["expected_total"]) <= max(
        data["tolerance_abs"], data["expected_total"] * data["tolerance_pct"]
    )
```

### 7.6 Migration tests

**Dual-path note:** migration 0016 uses `ADD COLUMN IF NOT EXISTS` (Postgres DDL only) and therefore runs against dev Postgres, not the SQLite unit suite. The SQLite test engine gets the full measurements schema from `Base.metadata.create_all` — it does not execute the `.sql` migration files. Provider and unit tests (§7.1–7.5) run fine on SQLite. Migration idempotency and column-presence assertions are Postgres-side only.

```python
# These tests run against dev Postgres (mark with @pytest.mark.postgres or a separate test file)

def test_migration_0016_idempotent(postgres_session):
    """Running migration 0016 twice against Postgres does not raise."""
    run_migration("0016_measurements_solar.sql", postgres_session)
    run_migration("0016_measurements_solar.sql", postgres_session)  # idempotent via IF NOT EXISTS

def test_migration_0016_columns_present(postgres_session):
    """All Solar-specific columns present after migration — verified on Postgres."""
    columns = get_table_columns(postgres_session, "measurements")
    for col in ["address_input", "geocoded_lat", "geocoded_lng", "solar_building_id",
                "solar_quality", "error_code", "error_message"]:
        assert col in columns
```

### 7.7 Validation exit gate (real Perkins addresses) — BLOCKING

`scripts/validate_solar_measurements.py` — **this is a blocking exit-gate item per R1**. F2b is not done until the script passes against real Perkins addresses. It is not a non-CI nicety; it is the behavioral validation for the Solar adapter path (analogous to `scripts/validate_estimator.py` for the engine path).

```
Usage: python scripts/validate_solar_measurements.py --addresses addresses.txt
```

For each address in the file:
1. Call `POST /measurements/solar` (against the deployed or local dev server with a real Solar API key).
2. Print status, total_sq, quality, provenance_note.
3. Flag any `status="failed"` as a warning (expected for rural/unrecognized addresses).
4. Assert at least 3 addresses return `status="complete"` with `total_sq > 0`.

**Exit-gate requirement (R1 behavioral validation):** at least 3 real Perkins-market addresses — one from each branch market (Miami/Broward, Jupiter/Palm Beach, Naples/Lee) — must return `status="complete"` with `solar_quality` of HIGH or MEDIUM and a plausible `total_sq` value. Jon runs this with a real Solar API key; the script stdout is captured and committed as evidence in the wave notes. F2b MUST NOT be marked done without this evidence present.

### 7.8 API behavioral tests

`tests/test_measurements_api.py` (outside `core/` gate, required by R1):

- `test_api_manual_creates_measurement`: POST /measurements/manual → 201, id returned.
- `test_api_solar_returns_failure_not_5xx`: mock Solar 404 → POST /measurements/solar returns 200 with `status="failed"`.
- `test_api_get_measurement_404_other_tenant`: measurement belonging to a different tenant returns 404 (ORM filter enforced before F4 RLS).
- `test_api_estimate_with_measurement_id`: POST /estimator/quote with valid `measurement_id` → response includes `measurement_provenance`.
- `test_api_estimate_with_failed_measurement_422`: POST /estimator/quote with `measurement_id` pointing to `status="failed"` → 422.

---

## 8. Implementation steps

Steps maintain fail-first TDD order.

1. **Write protocol conformance tests (red)**: `test_measurement_protocol.py`. Confirm red (no `core/measurement.py` yet).

2. **Implement `core/measurement.py`**: `MeasurementProvider` Protocol, `MeasurementInput`, `MeasurementResult`, `ManualEntryProvider`. Write and make green: protocol tests, manual provenance tests.

3. **Write Solar adapter tests (red)**: record a real Solar API response for one Perkins address (dev only, not CI) and commit as `tests/fixtures/solar/high_quality_28sq.json`. Write all Solar adapter tests. Confirm red.

4. **Implement `adapters/solar.py`**: `GoogleSolarProvider` — geocode call, Solar API call, quality gate, area conversion, pitch conversion, dominant pitch. Write no edge derivation yet. Make Solar adapter tests green (excluding edge tests).

5. **Write edge-derivation tests (red)**: all tests in §7.3. Confirm red.

6. **Implement `core/measurement.py:derive_edges_from_segment()` and `aggregate_edges()`**: make edge tests green. Document accuracy limitations in docstring and provenance note.

7. **Write migration 0016 and migration tests (red)**. Apply migration locally. Make tests green.

8. **Implement `api/routes/measurements.py`**: POST /measurements/manual, POST /measurements/solar, GET /measurements/{id}. Wire `adapters/solar.py` to the Solar endpoint. Write and make API behavioral tests green.

9. **Update `api/routes/estimator.py`**: handle `measurement_id` input — fetch measurement, validate status, auto-populate num_squares, stamp provenance in response, store measurement_id FK on estimate row. Write and make measurement-fed golden tests green.

10. **Terraform resources**: add `infra/solar_apis.tf` with API enablement, API key, Secret Manager secret. Apply in dev. Run `drift_check.sh`. Green.

11. **Validation exit gate**: run `scripts/validate_solar_measurements.py` with real Perkins addresses. Capture output as evidence. At least 3 addresses return complete HIGH/MEDIUM measurements.

12. **R2 review**: architect + critic review `core/measurement.py`, `adapters/solar.py`, edge derivation algorithm accuracy, provenance completeness, no silent fallback.

13. **Drift check**: `scripts/drift_check.sh` → clean.

---

## 9. Exit gate

The wave is done when ALL of the following are true:

- [ ] `pytest --cov=core --cov-fail-under=97 tests/test_measurement*.py tests/test_edge_derivation.py tests/test_measurement_provenance.py` green.
- [ ] All provider protocol conformance tests pass.
- [ ] Solar adapter unit tests pass against recorded fixtures (no live API in CI).
- [ ] Edge derivation unit tests pass.
- [ ] No silent fallback test (`test_no_silent_fallback_on_solar_failure`) passes.
- [ ] Manual provenance stamp test passes.
- [ ] Golden measurement-fed estimate tests pass (5 fixtures, ±$0.01).
- [ ] API behavioral tests pass (test_measurements_api.py).
- [ ] Migration 0016 idempotency test passes.
- [ ] **BLOCKING** `scripts/validate_solar_measurements.py` against real Perkins addresses: ≥ 3 addresses (one per branch market) return `status="complete"` with HIGH or MEDIUM quality. Script stdout captured and committed as evidence. Wave is NOT done without this evidence (R1 behavioral validation).
- [ ] Terraform plan clean after `infra/solar_apis.tf` applied: no drift (R4).
- [ ] `ruff check core adapters api jobs` clean.
- [ ] Architect + critic R2 review: no unaddressed HIGH findings.

---

## 10. Rollout / rollback

**Rollout:**

1. Apply migration 0016 via `scripts/apply_migrations_connector.py` (Jon's explicit permission + fresh ADC).
2. Add Solar API key to Secret Manager via Terraform (`terraform apply infra/solar_apis.tf`).
3. Deploy API (clean git tree required per R3-ENFORCE).
4. Run `scripts/validate_solar_measurements.py` with ≥ 3 real addresses.
5. Enable Solar endpoint in Admin → Estimating tab (measurement provider selector).

**Rollback (code):**

Re-deploy prior image. Solar endpoint returns 501 if `adapters/solar.py` is absent — existing manual measurements are unaffected. Migration 0016 columns are additive; old code ignores them.

**Rollback (Terraform — API keys):**

`terraform destroy -target=google_apikeys_key.solar_api_key` disables the key. The Secret Manager secret is left intact (no API calls will succeed without a valid key). Do not delete the secret — it costs nothing and avoids re-provisioning friction.

**Rollback (migration):**

Migration 0016 is additive (ADD COLUMN IF NOT EXISTS). No rollback DDL. If columns must be removed, do so manually with Jon's explicit permission.

---

## 11. Risks and open items

### Open items

1. **Real Solar API recorded fixtures** — `tests/fixtures/solar/high_quality_28sq.json` must be recorded against a real Perkins address during development (not generated synthetically). Jon must confirm Solar API is enabled and billed on the GCP project before recording. Tracked as §10.4 in the plan.

2. **Edge derivation accuracy** — bounding-box-based edge lengths are documented as ±10–15% on non-orthogonal roofs. For the estimating engine, `num_squares` (area-based) is the primary input; edges feed line items like ridge vents and stucco metal. Inaccuracy on edge lengths is a tolerable UX tradeoff for free Solar data. **Document clearly in the estimate UI; do not present as survey-grade.** If Tim or Josh find the inaccuracy unacceptable, the paid-upgrade seam (Nearmap/Vexcel) is the resolution path.

3. **GCP billing for Solar + Geocoding APIs** — Jon must confirm billing is enabled and set a spend alert. Both APIs are pay-per-use from first request. Estimated cost: < $25/month at current Perkins volume. **Jon action before rollout.**

4. **`python-jcs` or equivalent** — used for RFC 8785 canonicalization in TRD-F2; not needed in F2b, but note the shared dep.

5. **Nearmap / Vexcel oblique upgrade path** — the `MeasurementProvider` Protocol is the seam. A `NearMapProvider` class satisfies the same protocol; the API endpoint dispatches by `provider` parameter. No further design work needed in F2b — documented here for the F5+ implementer.

6. **Hip and valley detection** — currently 0 for Solar-derived measurements (bounding box cannot distinguish). If Tim's estimating workflows require accurate hip/valley linear feet (for specific line items), the resolution is either: (a) manual override in the UI after Solar measurement, or (b) Nearmap/Vexcel with true oblique imagery and edge detection. Document in the UI tooltip.

7. **Async measurement UX** — Solar + Geocoding round trip is typically 2–5 seconds; synchronous in F2b. If latency becomes a UX problem at higher volume, wrap in a Cloud Tasks queue with a polling endpoint (pattern: POST → 202 Accepted → GET /measurements/{id} for status). Not built in F2b; design is straightforward.

### Risks

- **eaglepoint source contamination** — the `~/projects/eaglepoint` repo must never be imported into this repo. Reference it for the measurement model shape only. The `core/measurement.py` implementation is written from scratch. CI should add a grep check: `grep -r "from eaglepoint" core adapters api` must return empty.
- **Google Maps Platform ToS** — using Solar API output to compute roofing estimates is permitted use (Google's own documentation positions `buildingInsights` for exactly this class of application). The prohibition is on scraping Google Earth / Maps imagery, which we do not do. The Solar API is the ToS-clean path (confirmed in the locked decisions).
- **API key leakage** — key must live in Secret Manager only; never in Cloud Run env vars, git, or logs. Add to the bandit check list (`bandit -c pyproject.toml` should catch hardcoded strings; add a custom grep in CI for the key pattern if needed).
- **Geocoding API billing separate from Solar API** — two separate API quotas and billing lines. Monitor both in Cloud Monitoring alerts.

---

*TRD-F2b — prepared 2026-07-08. Implementation subagents: sonnet (per token policy). R2 review: architect + critic (opus). eaglepoint (`~/projects/eaglepoint`) is read-only reference; never import its source.*
