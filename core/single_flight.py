"""One-at-a-time job guard built on a Postgres session-scoped advisory lock.

Extracted 2026-07-29 from three byte-identical copies (jobs/ingest_worker,
jobs/knowify_sync, jobs/companycam_sync) that all shared the same defect: they took the lock
and then yielded WITHOUT committing, so the holding session sat "idle in transaction" for the
entire job — minutes to hours.

Why that matters, from a real outage the same day: an idle-in-transaction session holds its
locks and pins the vacuum horizon. Three of them (left behind by finished jobs) blocked a
routine ``ALTER TABLE videos``, and every subsequent reader of that table then queued behind
the blocked ALTER. Prod now also runs with ``idle_in_transaction_session_timeout = 5min``,
which would KILL a lock holder mid-job and silently defeat single-flight.

The fix is one commit. ``pg_try_advisory_lock`` is **session**-scoped, not transaction-scoped
(that is ``pg_advisory_xact_lock``), so committing immediately keeps the lock for the life of
the connection while leaving no open transaction behind.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from sqlalchemy import text

log = logging.getLogger(__name__)


@contextmanager
def single_flight(session_factory: Callable[[], Any], key: int) -> Iterator[bool]:
    """Yield True if this process holds the advisory lock for *key*, False to skip.

    Session-scoped: process death releases it automatically, so a crashed job cannot wedge the
    schedule. No-op on SQLite (always True) — the guard exists for prod concurrency, and tests
    run single-process.
    """
    session = session_factory()
    session.info["platform_scope"] = True  # platform-level; no tenant GUC needed
    is_pg = session.bind.dialect.name == "postgresql"
    held = True
    try:
        if is_pg:
            held = bool(
                session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
            )
            # Close the transaction, KEEP the lock. Without this the holder is
            # idle-in-transaction for the whole job — see the module docstring.
            session.commit()
        yield held
    finally:
        try:
            if held and is_pg:
                session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
                session.commit()
        finally:
            session.close()
