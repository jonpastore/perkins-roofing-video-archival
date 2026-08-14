"""Shared migration ledger: skip already-applied files, refuse a silent prod default.

The three runners (apply_migrations_adc.py, apply_migrations_connector.py,
apply_migrations.sh) used to replay every file from MIN_MIGRATION on every run
and default GOOGLE_CLOUD_PROJECT to the production project. An unguarded UPDATE
then re-asserted its original value (or released a live claim) on every future
run. 0059 came within a WHERE-clause of becoming a periodic double-publish.

The ledger is a table the runner creates itself — it is not a migration file,
because a file cannot record that it has been applied until the ledger exists.
"""
from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path

LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    checksum TEXT NOT NULL
)
"""

# SQLite has no TIMESTAMPTZ; the runners talk to Postgres. Tests use this variant.
LEDGER_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    checksum TEXT NOT NULL
)
"""


def require_project() -> str:
    """Refuse to guess the target. The old default was production."""
    project = (os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    if not project:
        raise SystemExit(
            "GOOGLE_CLOUD_PROJECT is required — refusing to default to prod. "
            "Export the project you actually mean to migrate."
        )
    return project


def file_checksum(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ensure_ledger(execute: Callable, *, sqlite: bool = False) -> None:
    execute(LEDGER_DDL_SQLITE if sqlite else LEDGER_DDL)


def applied_checksums(fetchall: Callable) -> dict[str, str]:
    """filename -> checksum for every recorded file."""
    rows = fetchall("SELECT filename, checksum FROM schema_migrations")
    return {row[0]: row[1] for row in rows}


def record_applied(execute: Callable, filename: str, checksum: str) -> None:
    execute(
        "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
        (filename, checksum),
    )


def record_applied_sqlite(execute: Callable, filename: str, checksum: str) -> None:
    execute(
        "INSERT INTO schema_migrations (filename, checksum) VALUES (?, ?)",
        (filename, checksum),
    )


def decide(filename: str, checksum: str, applied: dict[str, str]) -> str:
    """'apply' | 'skip' | raise SystemExit on a checksum mismatch.

    A file that changed after it was recorded must not be silently re-run
    (non-idempotent UPDATEs) and must not be silently skipped (the change
    would never land). Write a new migration instead.
    """
    previous = applied.get(filename)
    if previous is None:
        return "apply"
    if previous != checksum:
        raise SystemExit(
            f"{filename} was already applied with a different checksum. "
            "Do not edit an applied migration — add a new file."
        )
    return "skip"
