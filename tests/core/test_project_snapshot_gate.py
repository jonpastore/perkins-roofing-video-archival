"""The gate that stops a project proposal being re-priced as a single roof (#430 slice 3).

web/src/pages/Proposals.tsx's edit path re-quotes exactly ONE estimate and rebuilds the snapshot
as `{...baseSnap, total, num_squares, estimate_result, tiers}`. Because it SPREADS the old
snapshot, `buildings` and `project_items` survive — which is worse than losing them: the result is
a contract that still lists nine structures while its scalars describe one, and nothing downstream
can tell which half is true.

These tests encode the invariant: the scalars must keep agreeing with the buildings.
"""
import pytest

from core.proposal import (
    ProjectSnapshotError,
    is_project_snapshot,
    validate_project_snapshot,
)


def _project_snapshot(n: int = 3) -> dict:
    buildings = [{"name": f"B{i}", "squares": 10.0, "total": 12000.0, "profit": 1500.0}
                 for i in range(n)]
    return {
        "pricing_config_hash": "abc123",
        "sent_at_iso": "2026-08-01T00:00:00Z",
        "roof_type": "13_tile",
        "num_squares": 10.0 * n,
        "tiers": {"good": {"total": 36000.0}},
        "deposit_policy": {"mode": "none", "value": 0},
        "floors": {"min_profit_pct": 0.13, "min_profit_plus_oh_pct": 0.33},
        "estimator_version": "v2",
        "buildings": buildings,
        "project_items": [{"key": "gc", "label": "General Conditions", "amount": 36570.0}],
        "project_totals": {"project_total": 72570.0, "profit": 4500.0,
                           "building_count": n, "warnings": []},
    }


def _single_building_snapshot() -> dict:
    """What the SPA produces: same keys, one roof's numbers."""
    return {
        "pricing_config_hash": "abc123", "sent_at_iso": "2026-08-01T00:00:00Z",
        "roof_type": "13_tile", "num_squares": 10.0,
        "tiers": {"good": {"total": 12000.0}},
        "deposit_policy": {"mode": "none", "value": 0},
        "floors": {"min_profit_pct": 0.13, "min_profit_plus_oh_pct": 0.33},
        "estimator_version": "v2",
    }


class TestTheGate:
    def test_a_single_estimate_requote_is_refused(self):
        """The exact SPA payload: spread the old snapshot, overwrite the scalars from one roof."""
        previous = _project_snapshot(9)
        # `{...baseSnap, num_squares, total, tiers}` — buildings SURVIVE the spread.
        incoming = {**previous, "num_squares": 10.0, "total": 12000.0,
                    "tiers": {"good": {"total": 12000.0}}}

        with pytest.raises(ProjectSnapshotError, match="does not match"):
            validate_project_snapshot(previous, incoming)

    def test_dropping_the_project_keys_entirely_is_refused(self):
        with pytest.raises(ProjectSnapshotError, match="drops"):
            validate_project_snapshot(_project_snapshot(9), _single_building_snapshot())

    def test_a_building_count_that_disagrees_is_refused(self):
        previous = _project_snapshot(9)
        incoming = {**previous}
        incoming["buildings"] = incoming["buildings"][:3]
        incoming["num_squares"] = 30.0          # scalars made consistent with the 3...
        # ...but project_totals still claims 9.
        with pytest.raises(ProjectSnapshotError, match="building_count"):
            validate_project_snapshot(previous, incoming)


class TestWhatMustStillBeAllowed:
    """A gate that blocks ordinary edits gets worked around. These must pass."""

    def test_editing_the_deposit_is_allowed(self):
        previous = _project_snapshot(3)
        incoming = {**previous, "deposit_policy": {"mode": "fixed", "value": 5000,
                                                   "amount": 5000}}
        validate_project_snapshot(previous, incoming)   # must not raise

    def test_a_genuine_reprice_of_the_whole_project_is_allowed(self):
        """Every building re-priced together — scalars and buildings still agree."""
        previous = _project_snapshot(3)
        incoming = _project_snapshot(3)
        for b in incoming["buildings"]:
            b["total"] = 13000.0
        incoming["project_totals"]["project_total"] = 75570.0
        validate_project_snapshot(previous, incoming)

    def test_adding_a_building_is_allowed_when_the_scalars_follow(self):
        previous = _project_snapshot(3)
        incoming = _project_snapshot(4)
        validate_project_snapshot(previous, incoming)

    def test_a_single_building_proposal_is_untouched(self):
        """Nothing about this gate may change how an ordinary proposal behaves."""
        validate_project_snapshot(_single_building_snapshot(), _single_building_snapshot())
        validate_project_snapshot(_single_building_snapshot(), {"anything": "goes"})

    def test_not_touching_the_snapshot_is_allowed(self):
        """A title-only PUT sends quote_snapshot=None."""
        validate_project_snapshot(_project_snapshot(9), None)


def test_is_project_snapshot_identifies_the_shape():
    assert is_project_snapshot(_project_snapshot(2)) is True
    assert is_project_snapshot(_single_building_snapshot()) is False
    assert is_project_snapshot(None) is False
    assert is_project_snapshot({"buildings": []}) is False
