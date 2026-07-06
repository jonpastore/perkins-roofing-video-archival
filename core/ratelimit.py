"""Per-process concurrency + cooldown guards for expensive fan-out operations.

These are intentionally per-process (not distributed) guards. Cloud Run may
run multiple instances, so a determined attacker with many tokens can still
hit N instances in parallel. The stronger control is a durable per-day budget
backed by platform_config (e.g. a daily YouTube-API-calls counter and a Vertex
spend counter written to the DB at job completion). Add that as a follow-up
when quota abuse becomes a real operational concern.

Usage::

    from core.ratelimit import SingleFlightGuard

    _crawl_guard = SingleFlightGuard(cooldown_seconds=30)

    @router.post("/crawl")
    def crawl(…):
        _crawl_guard.acquire_or_raise("crawl")
        try:
            …
        finally:
            _crawl_guard.release("crawl")
"""

import threading
import time
from typing import Optional

from fastapi import HTTPException

# Minimum seconds between successive runs of the same operation name.
# Override per-guard at construction time.
DEFAULT_COOLDOWN_SECONDS: int = 30


class SingleFlightGuard:
    """Non-blocking lock + cooldown guard for a named operation.

    - ``acquire_or_raise`` is non-blocking: if the lock is already held it
      raises HTTP 409 immediately rather than queuing.
    - If ``cooldown_seconds > 0`` and the operation finished less than
      ``cooldown_seconds`` ago it raises HTTP 429 (caller must wait).
    - ``cooldown_seconds=0`` disables the cooldown (lock-only mode).
    """

    def __init__(self, cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS) -> None:
        self._cooldown = cooldown_seconds
        self._lock = threading.Lock()
        # Guards _last_finished_at mutations (separate from the op lock so we
        # can read the timestamp without holding the op lock).
        self._ts_lock = threading.Lock()
        self._last_finished_at: Optional[float] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire_or_raise(self, op_name: str) -> None:
        """Try to acquire the guard; raise HTTP 409/429 on failure."""
        # Cooldown check — fast path before taking the lock.
        if self._cooldown > 0:
            with self._ts_lock:
                last = self._last_finished_at
            if last is not None:
                elapsed = time.monotonic() - last
                if elapsed < self._cooldown:
                    remaining = int(self._cooldown - elapsed) + 1
                    raise HTTPException(
                        status_code=429,
                        detail=(
                            f"{op_name} ran {int(elapsed)}s ago; "
                            f"retry after {remaining}s "
                            f"(cooldown={self._cooldown}s)"
                        ),
                    )

        acquired = self._lock.acquire(blocking=False)
        if not acquired:
            raise HTTPException(
                status_code=409,
                detail=f"{op_name} is already running; try again shortly",
            )

    def release(self, op_name: str) -> None:  # noqa: ARG002
        """Release the lock and record the finish timestamp."""
        with self._ts_lock:
            self._last_finished_at = time.monotonic()
        self._lock.release()

    def _reset_for_testing(self) -> None:
        """Reset all guard state. Call from test fixtures only."""
        # Release the lock if it's held (e.g. a previous test crashed before finally)
        try:
            self._lock.release()
        except RuntimeError:
            pass  # was not locked — fine
        with self._ts_lock:
            self._last_finished_at = None

    # ------------------------------------------------------------------
    # Context-manager convenience
    # ------------------------------------------------------------------

    def guarded(self, op_name: str):
        """Context manager: acquire on enter, release on exit."""
        return _GuardContext(self, op_name)


class _GuardContext:
    def __init__(self, guard: SingleFlightGuard, op_name: str) -> None:
        self._guard = guard
        self._op = op_name

    def __enter__(self):
        self._guard.acquire_or_raise(self._op)
        return self

    def __exit__(self, *_):
        self._guard.release(self._op)
