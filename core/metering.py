"""Per-tenant usage metering — F5-a.

Counters live on a contextvars.ContextVar so they are:
- Thread-safe (each thread has its own context by default in concurrent.futures/threading)
- Async-safe (each task inherits its own copy)
- Cloud-Run-Job-safe (each process gets a clean context automatically)

threading.local() is explicitly rejected per TRD-F5 §5 — it is not context-safe for async
code and provides no advantage over ContextVar in the job (single-threaded) case.

Public API (consumed by for_each_tenant and instrumented adapters):
    reset(tenant_id)          — called by for_each_tenant before fn()
    add(metric, value)        — called by llm.py / stt adapter / render_job
    flush(emit=False)         — called by for_each_tenant after fn(); returns totals dict
"""
from __future__ import annotations

import json
import logging
import time
from contextvars import ContextVar
from typing import Any

log = logging.getLogger(__name__)

# The single ContextVar holding the current tenant's counters.
# Empty dict == "outside a tenant loop context".
_counters: ContextVar[dict[str, Any]] = ContextVar("cost_counters", default={})

_METRICS = ("llm_tokens", "stt_minutes", "render_minutes")


def reset(tenant_id: int) -> None:
    """Initialise (or re-initialise) per-tenant counters.

    Called by for_each_tenant before each tenant's fn().
    """
    _counters.set({
        "tenant_id": tenant_id,
        "llm_tokens": 0,
        "stt_minutes": 0.0,
        "render_minutes": 0.0,
    })


def add(metric: str, value: float | int) -> None:
    """Accumulate *value* onto *metric* for the current tenant context.

    No-ops silently when called outside a tenant loop context (counter dict empty).
    This is intentional — adapters that emit metrics must not fail when called from
    platform-level code paths that run without a tenant context.
    """
    c = _counters.get()
    if not c:
        return
    _counters.set({**c, metric: c.get(metric, 0) + value})


def flush(*, emit: bool = False) -> dict[str, Any]:
    """Return current counters and reset to empty.

    Args:
        emit: When True, emit a structured log event per metric (for_each_tenant
              passes emit=True so every job run produces a metering audit trail).
              When False (default), just return the dict — used in unit tests and
              by callers that will emit the log themselves.

    Returns:
        The accumulated counter dict (includes tenant_id, llm_tokens,
        stt_minutes, render_minutes). Returns {} when called outside a tenant
        loop context (nothing to flush).
    """
    c = _counters.get()
    _counters.set({})

    if not c:
        return {}

    if emit:
        tid = c.get("tenant_id")
        ts = round(time.time(), 3)
        for metric in _METRICS:
            value = c.get(metric, 0)
            log.info(
                json.dumps({
                    "event": "metering_flush",
                    "tenant_id": tid,
                    "metric": metric,
                    "value": value,
                    "ts": ts,
                })
            )

    return c
