"""Integration health status machine — pure, no I/O (comments+OAuth plan Phase 1.1).

WHY: three same-day credential outages (Principle 5 / pre-mortem 1 of
``docs/plans/2026-07-17-comments-oauth-plan.md``) showed alarms either fire on every
transient blip ("cries wolf") or stay silent on a dead token. The fix is a severity
split: a HARD auth failure (401 / invalid_grant / revoked consent) means the credential
is provably dead, so it alarms on the very FIRST probe cycle. A TRANSIENT failure
(5xx / timeout) is ambiguous, so it only flips to broken after
``TRANSIENT_FAILURE_THRESHOLD`` (3) consecutive failures — Cloud Monitoring's own
dedup/flap-suppression covers job-level noise; this module only owns the row the UI
renders and the one-shot reconnect email.

Email fires only on a transition INTO broken (``should_alert``), never on every
already-broken cycle — that would re-cry-wolf on every 30-minute probe while a token
stays dead. No re-alert cadence in v1 (YAGNI per the plan's Option C decision).

This module has no I/O: callers own persistence, probing, and email sending.
"""
from __future__ import annotations

from dataclasses import dataclass

STATUSES = ("unconfigured", "healthy", "expiring", "broken")
TRANSIENT_FAILURE_THRESHOLD = 3


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of one liveness probe against a provider (adapters own the I/O)."""

    ok: bool
    hard_auth_failure: bool = False  # 401 / invalid_grant / revoked consent
    expiring: bool = False  # ok but nearing expiry per provider metadata
    error: str | None = None


def _validate(prev_status: str, prev_consecutive_failures: int) -> None:
    if prev_status not in STATUSES:
        raise ValueError(f"unknown prev_status: {prev_status!r}")
    if prev_consecutive_failures < 0:
        raise ValueError(
            f"prev_consecutive_failures must be >= 0: {prev_consecutive_failures!r}"
        )


def next_status(
    probe: ProbeResult, prev_status: str, prev_consecutive_failures: int
) -> tuple[str, int]:
    """Compute the next (status, consecutive_failures) from one probe cycle.

    - ``probe.ok`` resets the failure counter to 0 and reports healthy/expiring.
    - ``probe.hard_auth_failure`` breaks on the FIRST occurrence (Principle 5): the
      credential is provably dead, no point waiting for a threshold.
    - Any other failure is transient: the counter increments and only crosses into
      ``broken`` at ``TRANSIENT_FAILURE_THRESHOLD``; below that, ``prev_status`` is
      preserved unchanged (a healthy integration having one 503 stays healthy).
    """
    _validate(prev_status, prev_consecutive_failures)

    if probe.ok:
        return ("expiring" if probe.expiring else "healthy", 0)

    if probe.hard_auth_failure:
        return ("broken", prev_consecutive_failures + 1)

    failures = prev_consecutive_failures + 1
    if failures >= TRANSIENT_FAILURE_THRESHOLD:
        return ("broken", failures)
    return (prev_status, failures)


def should_alert(prev_status: str, new_status: str) -> bool:
    """True iff this cycle is the transition INTO broken (prev != broken -> broken).

    One email per outage, not one per probe cycle while it stays broken.
    """
    for status in (prev_status, new_status):
        if status not in STATUSES:
            raise ValueError(f"unknown status: {status!r}")
    return new_status == "broken" and prev_status != "broken"
