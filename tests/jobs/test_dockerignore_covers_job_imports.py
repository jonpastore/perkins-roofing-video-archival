"""A job that imports from scripts/ must have that file un-ignored for the build context.

2026-07-31: the hourly salinity sweep shipped green — CI passed, terraform was clean, the image
built, the scheduler fired on time — and every execution died with

    ImportError: cannot import name 'fetch_salinity_readings' from 'scripts' (unknown location)

`.dockerignore` ignores `scripts/*` and re-includes an explicit allowlist, so the image carried an
EMPTY scripts/ namespace package. Nothing in the local test suite could see it: the module imports
fine from a checkout, and the gap only exists inside the built image.

This is the cheapest thing that fails when the allowlist falls behind the code.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# `from scripts import x` and `import scripts.x`, wherever they sit (these imports are deliberately
# function-local in the jobs, to keep module import cheap).
_IMPORTS = re.compile(r"^\s*(?:from\s+scripts\s+import\s+(\w+)|import\s+scripts\.(\w+))", re.M)


def test_every_script_a_job_imports_is_in_the_build_context() -> None:
    ignore = (ROOT / ".dockerignore").read_text()
    unignored = set(re.findall(r"^!scripts/(\w+)\.py\s*$", ignore, re.M))

    missing = []
    for job in sorted((ROOT / "jobs").glob("*.py")):
        for a, b in _IMPORTS.findall(job.read_text()):
            name = a or b
            if name not in unignored:
                missing.append(f"{job.name} imports scripts.{name}")

    assert not missing, (
        "These jobs import a script that .dockerignore excludes from the image, so they will "
        "raise ImportError at runtime while every local gate passes:\n  "
        + "\n  ".join(missing)
        + "\nFix: add `!scripts/<name>.py` to .dockerignore, after the `scripts/*` line."
    )


def test_the_allowlist_does_not_name_files_that_are_gone() -> None:
    """A stale `!scripts/x.py` is not fatal, but it hides that the real file was renamed."""
    ignore = (ROOT / ".dockerignore").read_text()
    stale = [n for n in re.findall(r"^!scripts/(\w+\.py)\s*$", ignore, re.M)
             if not (ROOT / "scripts" / n).exists()]
    assert not stale, f".dockerignore un-ignores scripts that no longer exist: {stale}"
