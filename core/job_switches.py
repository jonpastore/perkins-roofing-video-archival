"""Admin-controlled on/off flags for scheduled jobs.

PlatformConfig (Admin → Platform Settings) wins; else env; default off.
These replace Terraform `paused=true` so Tim/Jon can flip a job without an apply.
"""
from __future__ import annotations

import os

KNOWIFY_SYNC = "KNOWIFY_SYNC_ENABLED"
PROPOSAL_REMINDERS = "PROPOSAL_REMINDERS_ENABLED"
CONTENT_GEN = "CONTENT_GEN_MODE"
TRUE = frozenset({"1", "true", "yes", "on"})


def parse_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in TRUE


def read_flag(key: str, default: bool = False) -> bool:
    """platform_config row first, then env, then default."""
    try:
        from app.models import PlatformConfig, PlatformSessionLocal  # noqa: PLC0415

        with PlatformSessionLocal() as db:
            db.info["platform_scope"] = True
            row = db.get(PlatformConfig, key)
            if row is not None and (row.value or "").strip():
                return parse_bool(row.value, default)
    except Exception:
        pass
    return parse_bool(os.getenv(key), default)


def knowify_sync_enabled() -> bool:
    return read_flag(KNOWIFY_SYNC, default=False)


def proposal_reminders_enabled() -> bool:
    return read_flag(PROPOSAL_REMINDERS, default=False)


def content_gen_enabled() -> bool:
    """True when the daily cron will write a new pillar campaign (drafts only)."""
    from core.content_cadence import read_mode  # noqa: PLC0415

    return read_mode() == "dump"
