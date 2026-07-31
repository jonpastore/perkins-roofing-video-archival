"""The sweep must not write under $HOME — the job container has no writable home.

2026-07-31: with the ImportError fixed, the next scheduled run got one line further and died on

    PermissionError: [Errno 13] Permission denied: '/home/appuser'

`scripts/fetch_salinity_readings.CACHE` defaults to `Path.home()/perkins-corpus/...`, which is
correct for a laptop run and impossible in the job, which runs as a non-root user with no home.
The job overrides it to a scratch path; the durable cache is the GCS object.

Two failures cost two deploy cycles to find because each was only reachable inside the built image.
This test reaches it locally: it points HOME at a path that cannot be created and asserts run()
still completes and uploads.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from jobs import salinity_sweep


@pytest.fixture
def _stubbed(monkeypatch):
    """Stub GCS + the USGS fetch so only the path handling is under test."""
    from adapters import storage
    from scripts import fetch_salinity_readings as fsr

    uploaded: dict = {}
    monkeypatch.setattr(storage, "object_exists", lambda b, k: False)
    monkeypatch.setattr(storage, "download_file", lambda b, k, d: None)
    monkeypatch.setattr(
        storage, "upload_file",
        lambda local, bucket, key, **kw: uploaded.update(local=local, bucket=bucket, key=key))

    def fake_main():
        # Exactly what the real fetcher does: write the module-global CACHE.
        fsr.CACHE.write_text(json.dumps({"gauges": {"02306028": {"median_us_cm": 46600.0}}}))

    monkeypatch.setattr(fsr, "main", fake_main)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    return uploaded


def test_run_does_not_write_under_an_unwritable_home(monkeypatch, _stubbed, tmp_path):
    # A home that cannot be created, the way the job container behaves.
    monkeypatch.setenv("HOME", str(tmp_path / "nonexistent" / "appuser"))
    monkeypatch.setattr(Path, "home", lambda: Path(tmp_path / "nonexistent" / "appuser"))

    from scripts import fetch_salinity_readings as fsr
    monkeypatch.setattr(fsr, "CACHE", Path.home() / "perkins-corpus/osm/salinity-readings.json")

    out = salinity_sweep.run(slices=24)

    assert out["gauges_cached"] == 1
    assert out["salt_or_brackish"] == 1
    assert _stubbed["key"] == salinity_sweep.GCS_KEY
    # The uploaded file is the scratch copy, not anything under the (unwritable) home.
    assert str(tmp_path) not in _stubbed["local"]
    assert _stubbed["local"].startswith(tempfile.gettempdir())
