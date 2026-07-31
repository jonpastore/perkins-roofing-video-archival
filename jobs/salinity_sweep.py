"""Refresh one slice of the USGS salinity gauges and publish the cache to GCS.

Jon, 2026-07-31: *"we should just poll all of the data from all sensors every day and build the
cache to hit and not do this per query. spread out the requests over the day and hit them all as a
background service on continuous run."*

One hourly schedule covers all 24 slices because the job picks its own slice from the UTC hour, so
there is a single scheduler resource rather than 24, and the load on USGS is a few requests an hour
instead of one daily burst.

WHERE IT LANDS. The readings go to `gs://{project}-media/warranty-tool/salinity-readings.json`.
`scripts/build_tidal_layer.py` prefers that object over the local cache, so a rebuild anywhere
uses current data without anyone remembering to refresh it first.

WHAT IT IS NOT. Nothing here is user-facing and nothing runs per request: the browser never calls
USGS, and no address, coordinate or query is recorded — only station readings.

Run: python -m jobs.salinity_sweep [slices]        (default 24)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

GCS_KEY = "warranty-tool/salinity-readings.json"


def _media_bucket() -> str:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT env var is required for GCS upload")
    return f"{project}-media"


def run(slices: int = 24) -> dict:
    """Refresh the slice belonging to the current hour, merging into the published cache."""
    from adapters.storage import download_file, object_exists, upload_file  # noqa: PLC0415

    # Import late: the fetcher lives in scripts/ and carries the USGS contract, so there is one
    # implementation of "what a reading means" rather than a copy that drifts.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts import fetch_salinity_readings as fsr  # noqa: PLC0415

    bucket = _media_bucket()
    hour = datetime.now(timezone.utc).hour
    index = hour % slices

    # Seed the local cache from GCS so this slice merges into the published set instead of
    # starting from whatever this container happens to have (nothing).
    fsr.CACHE.parent.mkdir(parents=True, exist_ok=True)
    if object_exists(bucket, GCS_KEY):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            download_file(bucket, GCS_KEY, tmp.name)
        fsr.CACHE.write_bytes(Path(tmp.name).read_bytes())
        os.unlink(tmp.name)

    sys.argv = ["fetch_salinity_readings", "--slice", f"{index}/{slices}"]
    fsr.main()

    upload_file(str(fsr.CACHE), bucket, GCS_KEY, content_type="application/json")
    cached = json.loads(fsr.CACHE.read_text()).get("gauges", {})
    salt = sum(1 for g in cached.values()
               if float(g["median_us_cm"]) >= fsr.FRESH_MAX) if cached else 0
    out = {"slice": f"{index}/{slices}", "gauges_cached": len(cached),
           "salt_or_brackish": salt, "gcs": f"gs://{bucket}/{GCS_KEY}"}
    print(json.dumps(out), flush=True)
    return out


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 24)
