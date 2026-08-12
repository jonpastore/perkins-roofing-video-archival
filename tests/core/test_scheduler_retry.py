"""A failed promotion must be retryable — `error` was a terminal state nothing could leave.

WHAT THIS COVERS. jobs/promote_job.py set status='error' on any exception, and BOTH
core/scheduler.py::due and the row-claim required status == 'scheduled'. So one transient
failure parked an article permanently, on a cron that kept running every 15 minutes and kept
returning 200 OK.

Measured in prod 2026-08-12: 434 scheduled_content rows — 157 published, 277 error, zero
pending, zero mid-claim. Every errored row was overdue. The cause was WordPress auth on the
publish call (401 Unauthorized 2026-07-27/28, then 403 Forbidden 2026-08-04/07), and BOTH had
cleared by 08-12 — a probe row flipped back to 'scheduled' published cleanly through the real
Cloud Run path. So all 277 would have published on a later run if anything had retried.
"""
from datetime import datetime, timedelta

import pytest

from core.scheduler import CLAIMABLE, PROMOTE_MAX_ATTEMPTS, due

NOW = datetime(2026, 8, 12, 12, 0)
PAST = NOW - timedelta(days=1)
FUTURE = NOW + timedelta(days=1)


class Row:
    def __init__(self, status, publish_at=PAST, attempts=0):
        self.status = status
        self.publish_at = publish_at
        self.attempts = attempts


def test_an_errored_row_is_retried():
    """THE regression test. This is what 277 prod rows needed and never got."""
    assert due([Row("error")], NOW), "a failed promotion must be tried again"


def test_a_never_tried_row_is_still_due():
    assert due([Row("scheduled")], NOW)


def test_retries_stop_at_the_cap():
    """Bounded, so a genuinely broken row stops instead of hammering WordPress every 15
    minutes forever."""
    assert due([Row("error", attempts=PROMOTE_MAX_ATTEMPTS - 1)], NOW)
    assert not due([Row("error", attempts=PROMOTE_MAX_ATTEMPTS)], NOW)
    assert not due([Row("error", attempts=PROMOTE_MAX_ATTEMPTS + 3)], NOW)


def test_a_future_row_is_never_due_whatever_its_status():
    assert not due([Row("scheduled", publish_at=FUTURE)], NOW)
    assert not due([Row("error", publish_at=FUTURE)], NOW)


def test_terminal_states_are_never_reclaimed():
    """A published row must not be promoted twice, and a reel awaiting the social publisher
    is not the promoter's to touch."""
    for status in ("published", "promoting", "awaiting_social"):
        assert not due([Row(status)], NOW), status


def test_a_row_with_no_publish_at_is_skipped():
    assert not due([Row("scheduled", publish_at=None)], NOW)


def test_missing_attempts_is_treated_as_zero():
    """Rows written before migration 0058 have no attempts value in flight."""
    r = Row("error")
    del r.attempts
    assert due([r], NOW), "a pre-migration row must still be retried"


def test_the_claim_filter_accepts_exactly_what_due_returns():
    """The claim in promote_job filters on CLAIMABLE. If the two ever disagree, due() hands
    back a row the claim then refuses, and the job silently promotes nothing — which is
    indistinguishable in the logs from having nothing to do."""
    assert set(CLAIMABLE) == {"scheduled", "error"}
    for status in CLAIMABLE:
        assert due([Row(status)], NOW), status


@pytest.mark.parametrize("aware", [True, False])
def test_offset_aware_publish_at_still_compares(aware):
    from datetime import timezone
    pa = PAST.replace(tzinfo=timezone.utc) if aware else PAST
    assert due([Row("error", publish_at=pa)], NOW)


def test_a_held_row_is_never_promoted():
    """'held' means a human decided this must not publish yet — distinct from 'error' so
    "we chose not to" is never confused with "it failed". Used 2026-08-12 to hold seven
    production-targeted articles while the client's site was mid-rebuild."""
    assert not due([Row("held")], NOW)
    assert "held" not in CLAIMABLE


def test_releasing_a_held_row_is_just_a_status_flip():
    assert due([Row("scheduled")], NOW), "flipping held -> scheduled releases it"
