"""Render must not run the same part twice concurrently.

Found by the code-review audit, 2026-08-13. render_job was the ONLY heavy job without a
single-flight guard (ingest_worker 8274123, knowify_sync 8274124, tokens 8274125,
companycam_sync 8274126 all have one), and it is externally triggerable via
POST /clips/{id}/render with no dedupe.

The gcs_url idempotency check inside render_part cannot cover this: nothing is written until the
upload finishes, so two concurrent renders of the same part BOTH see "not rendered yet". Both then
pull a ~2 GB source into memory-backed /tmp and spend ~an hour, and the loser violates
uq_social_series_part_platform and is discarded.
"""
from __future__ import annotations

from contextlib import contextmanager

import jobs.render_job as RJ


def test_lock_key_is_unique_per_series_and_part():
    assert RJ._render_lock_key(3, 1) != RJ._render_lock_key(3, 2)
    assert RJ._render_lock_key(3, 1) != RJ._render_lock_key(4, 1)
    assert RJ._render_lock_key(3, 1) == RJ._render_lock_key(3, 1)


def test_lock_key_never_collides_with_a_job_level_lock():
    """A collision would make one series silently block an unrelated cron."""
    job_keys = {8274123, 8274124, 8274125, 8274126}
    keys = {RJ._render_lock_key(s, p) for s in range(300) for p in range(30)}
    assert not (keys & job_keys)
    assert len(keys) == 300 * 30, "keys must not alias across (series, part)"


def test_a_second_render_of_the_same_part_is_skipped_not_run(monkeypatch):
    """THE POINT: the loser returns immediately instead of burning an hour and 2 GB."""
    ran = []

    @contextmanager
    def _lock_denied(_factory, _key):
        yield False

    monkeypatch.setattr(RJ, "_render_part_locked", lambda *a, **k: ran.append(1))
    monkeypatch.setattr("core.single_flight.single_flight", _lock_denied)

    out = RJ.render_part(7, 0)

    assert out["skipped"] is True
    assert out["reason"] == "already_rendering"
    assert out["series_id"] == 7 and out["part_index"] == 0
    assert ran == [], "the body must not run when the lock is held elsewhere"


def test_the_holder_does_run(monkeypatch):
    """And the guard must not block the ordinary single-render case."""
    @contextmanager
    def _lock_granted(_factory, _key):
        yield True

    monkeypatch.setattr(RJ, "_render_part_locked",
                        lambda *a, **k: {"skipped": False, "gcs_url": "gs://x/y.mp4"})
    monkeypatch.setattr("core.single_flight.single_flight", _lock_granted)

    assert RJ.render_part(7, 0)["gcs_url"] == "gs://x/y.mp4"
