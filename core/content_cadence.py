"""Article generation cadence after the catalogue is primed.

Modes (platform_config / env CONTENT_GEN_MODE):
  off   — cron no-ops
  dump  — one new pillar (+ clusters) per tick; persist drafts only (no promote)

Freshness was removed (2026-08-18): it called next_topic() and could not rewrite
stale pillars. Do not re-add the knob until that selection exists.
"""
from __future__ import annotations

import os

MODE_KEY = "CONTENT_GEN_MODE"
DUMP_PER_RUN_KEY = "CONTENT_DUMP_PER_RUN"
DUMP_CLUSTERS_KEY = "CONTENT_DUMP_CLUSTERS"
TARGET_FRACTION_KEY = "CONTENT_TARGET_FRACTION"
FRESHNESS_PER_DAY_KEY = "CONTENT_FRESHNESS_PER_DAY"
FRESHNESS_BUDGET_KEY = "CONTENT_FRESHNESS_BUDGET"

MODES = frozenset({"off", "dump"})


def _read_raw(key: str) -> str | None:
    try:
        from app.models import PlatformConfig, PlatformSessionLocal  # noqa: PLC0415

        with PlatformSessionLocal() as db:
            db.info["platform_scope"] = True
            row = db.get(PlatformConfig, key)
            if row is not None and (row.value or "").strip():
                return row.value.strip()
    except Exception:
        pass
    raw = os.getenv(key)
    return raw.strip() if raw and raw.strip() else None


def read_mode(default: str = "off") -> str:
    raw = (_read_raw(MODE_KEY) or default).lower()
    return raw if raw in MODES else default


def read_int(key: str, default: int) -> int:
    raw = _read_raw(key)
    if raw is None:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def read_float(key: str, default: float) -> float:
    raw = _read_raw(key)
    if raw is None:
        return default
    try:
        return min(1.0, max(0.0, float(raw)))
    except ValueError:
        return default


def cadence() -> dict:
    """Resolved settings the daily job and the prime runner share."""
    return {
        "mode": read_mode(),
        "dump_per_run": read_int(DUMP_PER_RUN_KEY, 10),
        "dump_clusters": read_int(DUMP_CLUSTERS_KEY, 2),
        "target_fraction": read_float(TARGET_FRACTION_KEY, 0.5),
        "freshness_per_day": read_int(FRESHNESS_PER_DAY_KEY, 1),
        "freshness_budget": read_int(FRESHNESS_BUDGET_KEY, 10),
        "enabled": read_mode() != "off",
    }


def should_stop_dump(*, generated: int, potential: int, fraction: float) -> bool:
    """True when generated / potential has reached the configured share."""
    if potential <= 0:
        return True
    return (generated / potential) >= fraction
