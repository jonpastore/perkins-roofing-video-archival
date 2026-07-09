"""CI grep gate — all tenant-scoped GCS writes must go through tenant_object_path.

Per TRD-F5 §8, every GCS write in F5+ that stores a tenant-scoped asset must use
core.gcs_path.tenant_object_path() so the key is prefixed with tenants/{id}/.

This test greps adapters/ and jobs/ for direct .blob()/.bucket() write calls and
verifies each is either:
  (a) in the approved exemption list (low-level primitive callers, signed-URL helpers), or
  (b) a read-only call (existence probe, signed URL generation, delete).

What this catches:
  A new GCS write that uses a hardcoded path like bucket.blob("videos/foo.mp4") without
  routing through tenant_object_path — silent data isolation failure for tenant 2+.

What is NOT flagged:
  - adapters/storage.py  — the low-level GCS primitive (callers route through it)
  - Reads / existence probes / signed-URL generation / deletes
  - core/gcs_path.py itself (defines tenant_object_path)
  - tests/ (test doubles, mocks)

Approved write sites with justification (add new sites here when they route through
tenant_object_path OR are legitimately exempt):
  - jobs/render_job.py::_upload_to_gcs — calls blob.upload_from_filename but uses
    object_key produced by _gcs_object_key() which NOW calls tenant_object_path().
  - core/brand_kit.py::store_brand_asset / brand_upload_signed_url — blob() key is
    produced by tenant_object_path(); direct blob() call is the GCS SDK write path.
  - adapters/stt_gcp.py — blob(tenanted) .exists() probe inside
    tenant_object_path_with_fallback; the write path (upload_file, delete_object)
    goes through adapters/storage.py.
"""
from __future__ import annotations

import re
from pathlib import Path

# Directories to scan (relative to repo root).
_SCAN_DIRS = ["adapters", "jobs", "core"]

# Low-level GCS primitive — all other callers are expected to route through it.
# Also exempt: gcs_path.py itself (defines the utility), test doubles.
_EXEMPT_FILES = {
    "adapters/storage.py",        # low-level GCS primitive — callers route THROUGH it
    "core/gcs_path.py",           # defines tenant_object_path; the existence probe uses .blob()
    "core/brand_kit.py",          # store_brand_asset / brand_upload_signed_url: key built via
                                  # tenant_object_path(); .blob(key) is the GCS SDK write surface
    "jobs/render_job.py",         # _upload_to_gcs: object_key produced by _gcs_object_key()
                                  # which calls tenant_object_path() — path is correctly tenanted
}

# Regex: detect direct .blob( calls that could be GCS write paths.
# We look for .blob( because that's how the GCS SDK constructs an object reference for writes.
_BLOB_RE = re.compile(r"\.\s*blob\s*\(")

# Patterns that indicate the .blob() is used for a NON-WRITE operation (read-only / delete / URL):
#   .exists()       — existence probe
#   generate_signed_url — signed URL, not a write
#   delete()        — object deletion
#   .download_      — download methods
#   signed_get_url  — signing for reads
_SAFE_SUFFIXES_RE = re.compile(
    r"\.blob\s*\([^)]*\)\s*\.\s*(exists|generate_signed_url|delete|download_|reload)\s*\("
)


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    raise RuntimeError("Could not locate git repository root")


def _is_write_call(line: str) -> bool:
    """Return True if this line contains a .blob() that looks like a GCS write."""
    stripped = line.strip()
    # Skip pure comment and docstring lines.
    if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
        return False
    if not _BLOB_RE.search(line):
        return False
    # If the blob() is immediately followed by a known-safe suffix, it's a read/probe.
    if _SAFE_SUFFIXES_RE.search(line):
        return False
    return True


def test_no_direct_gcs_writes_outside_approved():
    """All tenant-scoped GCS writes must go through tenant_object_path.

    Scans adapters/ and jobs/ for .blob() calls that are not routed through
    adapters/storage.py (the approved low-level primitive) and are not read-only
    operations (existence probes, signed URLs, deletes).
    """
    root = _repo_root()

    violations: list[str] = []
    for scan_dir in _SCAN_DIRS:
        target = root / scan_dir
        if not target.exists():
            continue

        for py_file in sorted(target.rglob("*.py")):
            rel = py_file.relative_to(root).as_posix()

            if rel in _EXEMPT_FILES:
                continue

            content = py_file.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(content.splitlines(), start=1):
                if _is_write_call(line):
                    violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "Direct GCS .blob() write calls found outside approved modules.\n"
        "New tenant-scoped writes MUST use core.gcs_path.tenant_object_path() to build\n"
        "the object key, then pass it to adapters.storage.upload_file() or the low-level\n"
        "GCS SDK. Add an exemption to _EXEMPT_FILES with a justification only if the\n"
        "call truly cannot be routed through tenant_object_path.\n\n"
        "Violations:\n" + "\n".join(violations)
    )
