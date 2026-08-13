"""An interrupted promotion must become claimable again — "promoting" was an orphan state.

Migration 0058 made a FAILED promotion retryable. This is the case one step earlier: the process
DIES holding the claim, so nothing raises and no except/finally runs. `promoting` and `publishing`
are not in CLAIMABLE, so such a row was invisible to every future run with `attempts` never
incremented, while the surviving job reported success — the 277-row incident's shape, one state
further along and harder to see, because 0058's attempts counter cannot detect it.

Only elapsed time distinguishes "a dead run held this" from "a live sibling holds this", which is
why the fix needed a claimed_at column rather than more status values.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from core.scheduler import (
    CLAIMABLE,
    IN_FLIGHT_RELEASE,
    STALE_CLAIM_MINUTES,
    stale_claims,
)

NOW = datetime(2026, 8, 13, 12, 0, 0)


def _row(status, minutes_ago=None):
    return {"status": status,
            "claimed_at": None if minutes_ago is None else NOW - timedelta(minutes=minutes_ago)}


def test_an_in_flight_state_is_not_claimable_which_is_why_this_exists():
    for state in IN_FLIGHT_RELEASE:
        assert state not in CLAIMABLE, (
            f"{state!r} became claimable — two runs could then both claim the same row, which is "
            "the double-publish this whole mechanism exists to prevent"
        )


def test_a_dead_claim_is_reaped():
    assert stale_claims([_row("promoting", 45)], NOW)


def test_a_LIVE_sibling_is_never_stolen():
    """The promote cron fires every 15 min and a publish can overlap. Reaping a live claim would
    cause the exact double-publish the claim prevents."""
    assert stale_claims([_row("promoting", 5)], NOW) == []
    assert stale_claims([_row("publishing", STALE_CLAIM_MINUTES - 1)], NOW) == []


def test_a_pre_migration_orphan_has_no_stamp_and_must_still_be_reaped():
    """Rows stranded BEFORE 0059 have claimed_at NULL. Skipping them would leave exactly the
    rows this was written to rescue stranded forever."""
    assert len(stale_claims([_row("promoting"), _row("publishing")], NOW)) == 2


def test_states_that_are_not_in_flight_are_left_alone():
    """`held` in particular is a HUMAN decision (7 production rows, 2026-08-12). Reaping it would
    publish something someone deliberately held back."""
    untouched = [_row("scheduled"), _row("error", 9999), _row("held", 9999),
                 _row("published", 9999), _row("awaiting_social", 9999)]
    assert stale_claims(untouched, NOW) == []


def test_each_in_flight_state_releases_to_something_claimable_or_retryable():
    """A reap that released to another dead-end would just move the stranding."""
    assert IN_FLIGHT_RELEASE["promoting"] in CLAIMABLE
    # social_job's own selector picks up awaiting_social; it is that job's claimable state.
    assert IN_FLIGHT_RELEASE["publishing"] == "awaiting_social"
