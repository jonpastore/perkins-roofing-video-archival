"""100% line-coverage tests for core/publish_planner.py.

Tests cover: select_seed pct rounding/edge cases, publish_order pillar-first,
next_cluster pending selection, to_dispatch always-full math, and empty inputs.
"""
import pytest

from core.publish_planner import next_cluster, publish_order, select_seed, to_dispatch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _art(slug, role="support", priority=None, cluster_id=None, status="ready", scheduled_at=None):
    return {
        "slug": slug,
        "role": role,
        "priority": priority,
        "cluster_id": cluster_id,
        "status": status,
        "scheduled_at": scheduled_at,
    }


def _cluster(id, status="pending", position=0):
    return {"id": id, "status": status, "position": position}


# ---------------------------------------------------------------------------
# select_seed
# ---------------------------------------------------------------------------

class TestSelectSeed:
    def test_empty_returns_empty(self):
        assert select_seed([]) == []

    def test_single_item_pct_above_zero_returns_it(self):
        items = [_art("a", priority=1)]
        result = select_seed(items, pct=0.01)
        assert result == items

    def test_single_item_pct_zero_returns_empty(self):
        # ceil(1 * 0) == 0
        items = [_art("a", priority=1)]
        result = select_seed(items, pct=0.0)
        assert result == []

    def test_default_pct_55_rounds_up(self):
        # 10 items * 0.55 = 5.5 → ceil = 6
        items = [_art(str(i), priority=i) for i in range(10)]
        result = select_seed(items)
        assert len(result) == 6

    def test_ranks_by_priority_ascending(self):
        items = [_art("b", priority=2), _art("a", priority=1), _art("c", priority=3)]
        result = select_seed(items, pct=1.0)
        assert [r["slug"] for r in result] == ["a", "b", "c"]

    def test_none_priority_sorts_last(self):
        items = [_art("x", priority=None), _art("y", priority=5), _art("z", priority=1)]
        result = select_seed(items, pct=1.0)
        assert result[-1]["slug"] == "x"

    def test_pct_1_returns_all(self):
        items = [_art(str(i), priority=i) for i in range(5)]
        assert len(select_seed(items, pct=1.0)) == 5

    def test_pct_greater_than_1_clamped_to_all(self):
        items = [_art("a", priority=1), _art("b", priority=2)]
        assert len(select_seed(items, pct=2.0)) == 2

    def test_two_items_pct_half_returns_one(self):
        # ceil(2 * 0.5) == 1
        items = [_art("a", priority=1), _art("b", priority=2)]
        result = select_seed(items, pct=0.5)
        assert len(result) == 1
        assert result[0]["slug"] == "a"

    def test_all_none_priorities_still_returns_correct_count(self):
        items = [_art("a"), _art("b"), _art("c")]
        result = select_seed(items, pct=0.34)  # ceil(3*0.34)=ceil(1.02)=2
        assert len(result) == 2

    def test_three_items_pct_55_returns_two(self):
        # ceil(3 * 0.55) = ceil(1.65) = 2
        items = [_art(str(i), priority=i + 1) for i in range(3)]
        result = select_seed(items, pct=0.55)
        assert len(result) == 2
        assert result[0]["slug"] == "0"


# ---------------------------------------------------------------------------
# publish_order
# ---------------------------------------------------------------------------

class TestPublishOrder:
    def test_empty_returns_empty(self):
        assert publish_order([]) == []

    def test_pillar_before_support(self):
        items = [_art("s1", role="support", priority=1), _art("p1", role="pillar", priority=2)]
        result = publish_order(items)
        assert result[0]["role"] == "pillar"
        assert result[1]["role"] == "support"

    def test_supports_ordered_by_priority(self):
        items = [
            _art("s2", role="support", priority=3),
            _art("s1", role="support", priority=1),
            _art("s3", role="support", priority=5),
        ]
        result = publish_order(items)
        assert [r["slug"] for r in result] == ["s1", "s2", "s3"]

    def test_none_priority_sorts_after_numbered(self):
        items = [
            _art("s_none", role="support", priority=None),
            _art("s_low", role="support", priority=1),
        ]
        result = publish_order(items)
        assert result[0]["slug"] == "s_low"
        assert result[1]["slug"] == "s_none"

    def test_pillar_with_no_priority_still_before_support(self):
        items = [_art("s", role="support", priority=1), _art("p", role="pillar", priority=None)]
        result = publish_order(items)
        assert result[0]["role"] == "pillar"

    def test_multiple_pillars_ordered_by_priority(self):
        items = [
            _art("p2", role="pillar", priority=2),
            _art("p1", role="pillar", priority=1),
        ]
        result = publish_order(items)
        assert [r["slug"] for r in result] == ["p1", "p2"]

    def test_single_item_returned_unchanged(self):
        item = _art("only", role="pillar", priority=1)
        assert publish_order([item]) == [item]


# ---------------------------------------------------------------------------
# next_cluster
# ---------------------------------------------------------------------------

class TestNextCluster:
    def test_empty_returns_none(self):
        assert next_cluster([]) is None

    def test_no_pending_returns_none(self):
        clusters = [_cluster(1, status="active"), _cluster(2, status="complete")]
        assert next_cluster(clusters) is None

    def test_single_pending_returned(self):
        c = _cluster(1, status="pending", position=0)
        assert next_cluster([c]) is c

    def test_lowest_position_selected(self):
        clusters = [
            _cluster(3, status="pending", position=3),
            _cluster(1, status="pending", position=1),
            _cluster(2, status="pending", position=2),
        ]
        result = next_cluster(clusters)
        assert result["id"] == 1

    def test_skips_active_and_complete(self):
        clusters = [
            _cluster(1, status="complete", position=0),
            _cluster(2, status="active", position=1),
            _cluster(3, status="pending", position=2),
        ]
        result = next_cluster(clusters)
        assert result["id"] == 3

    def test_none_position_treated_as_zero(self):
        clusters = [
            _cluster(1, status="pending", position=None),
            _cluster(2, status="pending", position=5),
        ]
        result = next_cluster(clusters)
        # None treated as 0 → id=1 wins
        assert result["id"] == 1


# ---------------------------------------------------------------------------
# to_dispatch
# ---------------------------------------------------------------------------

class TestToDispatch:
    def test_empty_in_flight_dispatches_up_to_target(self):
        ready = [_art(str(i)) for i in range(10)]
        result = to_dispatch([], target=3, ready=ready)
        assert len(result) == 3
        assert result == ready[:3]

    def test_already_at_target_returns_empty(self):
        in_flight = [_art("a"), _art("b"), _art("c")]
        ready = [_art("d")]
        result = to_dispatch(in_flight, target=3, ready=ready)
        assert result == []

    def test_above_target_returns_empty(self):
        in_flight = [_art(str(i)) for i in range(5)]
        result = to_dispatch(in_flight, target=3, ready=[_art("x")])
        assert result == []

    def test_empty_ready_returns_empty(self):
        result = to_dispatch([], target=5, ready=[])
        assert result == []

    def test_partial_fill_when_ready_exhausted(self):
        ready = [_art("a"), _art("b")]
        result = to_dispatch([], target=5, ready=ready)
        assert result == ready  # only 2 available, target=5

    def test_single_slot_dispatches_one(self):
        in_flight = [_art("a"), _art("b"), _art("c"), _art("d")]
        ready = [_art("e"), _art("f")]
        result = to_dispatch(in_flight, target=5, ready=ready)
        assert len(result) == 1
        assert result[0]["slug"] == "e"

    def test_target_zero_returns_empty(self):
        result = to_dispatch([], target=0, ready=[_art("a")])
        assert result == []

    def test_preserves_ready_order(self):
        ready = [_art("z"), _art("a"), _art("m")]
        result = to_dispatch([], target=2, ready=ready)
        assert [r["slug"] for r in result] == ["z", "a"]
