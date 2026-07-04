"""Tests for core/miniseries.py — pure mini-series planner."""

import pytest
from core.miniseries import propose_parts, rank_candidates


# ---------------------------------------------------------------------------
# rank_candidates
# ---------------------------------------------------------------------------


def test_rank_candidates_sorts_by_density_desc():
    videos = [
        {"video_id": "a", "duration": 100, "graph_nodes": 5},   # density 0.05
        {"video_id": "b", "duration": 100, "graph_nodes": 10},  # density 0.10
        {"video_id": "c", "duration": 50,  "graph_nodes": 3},   # density 0.06
    ]
    result = rank_candidates(videos)
    assert [v["video_id"] for v in result] == ["b", "c", "a"]


def test_rank_candidates_tiebreak_by_duration_desc():
    # Same density (graph_nodes / duration = 0.1), different durations
    videos = [
        {"video_id": "short", "duration": 100, "graph_nodes": 10},  # density 0.1
        {"video_id": "long",  "duration": 200, "graph_nodes": 20},  # density 0.1
    ]
    result = rank_candidates(videos)
    assert result[0]["video_id"] == "long"
    assert result[1]["video_id"] == "short"


def test_rank_candidates_adds_density_field():
    videos = [{"video_id": "x", "duration": 200, "graph_nodes": 10}]
    result = rank_candidates(videos)
    assert result[0]["density"] == pytest.approx(10 / 200)


def test_rank_candidates_zero_duration_clamps_to_one():
    videos = [{"video_id": "z", "duration": 0, "graph_nodes": 5}]
    result = rank_candidates(videos)
    assert result[0]["density"] == pytest.approx(5.0)


def test_rank_candidates_empty_list():
    assert rank_candidates([]) == []


def test_rank_candidates_preserves_original_fields():
    videos = [{"video_id": "v1", "duration": 60, "graph_nodes": 3, "extra": "keep"}]
    result = rank_candidates(videos)
    assert result[0]["extra"] == "keep"


def test_rank_candidates_single_video():
    videos = [{"video_id": "only", "duration": 300, "graph_nodes": 12}]
    result = rank_candidates(videos)
    assert len(result) == 1
    assert result[0]["video_id"] == "only"
    assert result[0]["density"] == pytest.approx(12 / 300)


# ---------------------------------------------------------------------------
# propose_parts — even split when nodes < min_parts
# ---------------------------------------------------------------------------


def test_propose_parts_even_split_when_no_nodes():
    parts = propose_parts("v1", 120.0, [], min_parts=4, max_parts=7)
    assert len(parts) == 4
    _assert_non_overlapping_within_duration(parts, 120.0)
    assert parts[0]["title"] == "Part 1"
    assert parts[3]["title"] == "Part 4"


def test_propose_parts_even_split_when_fewer_nodes_than_min():
    nodes = [{"label": "flashing", "start": 30}]
    parts = propose_parts("v1", 100.0, nodes, min_parts=4, max_parts=7)
    assert len(parts) == 4
    _assert_non_overlapping_within_duration(parts, 100.0)
    # Even split → "Part N" titles
    for i, p in enumerate(parts):
        assert p["title"] == f"Part {i + 1}"


def test_propose_parts_even_split_exactly_min_minus_one_nodes():
    # min_parts=4, supply 3 nodes → still triggers even split
    nodes = [
        {"label": "A", "start": 10},
        {"label": "B", "start": 20},
        {"label": "C", "start": 30},
    ]
    parts = propose_parts("v1", 80.0, nodes, min_parts=4, max_parts=7)
    assert len(parts) == 4


def test_propose_parts_even_split_covers_full_duration():
    parts = propose_parts("v1", 90.0, [], min_parts=4, max_parts=7)
    assert parts[0]["start"] == pytest.approx(0.0)
    assert parts[-1]["end"] == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# propose_parts — count clamping (many nodes → capped at max_parts)
# ---------------------------------------------------------------------------


def test_propose_parts_capped_at_max_parts():
    # 20 nodes → must be capped at max_parts=7
    nodes = [{"label": f"Topic {i}", "start": i * 10} for i in range(20)]
    parts = propose_parts("v1", 200.0, nodes, min_parts=4, max_parts=7)
    assert len(parts) == 7


def test_propose_parts_exactly_min_nodes_gives_min_parts():
    # 4 nodes → 5 natural parts (4+1), still within [4,7]
    nodes = [{"label": f"T{i}", "start": i * 20} for i in range(4)]
    parts = propose_parts("v1", 100.0, nodes, min_parts=4, max_parts=7)
    assert min_parts_valid(len(parts), 4, 7)


def test_propose_parts_count_within_range_for_moderate_nodes():
    nodes = [{"label": f"T{i}", "start": i * 15} for i in range(6)]
    parts = propose_parts("v1", 120.0, nodes, min_parts=4, max_parts=7)
    assert 4 <= len(parts) <= 7


# ---------------------------------------------------------------------------
# propose_parts — non-overlapping + within duration
# ---------------------------------------------------------------------------


def test_propose_parts_non_overlapping_and_within_duration():
    nodes = [
        {"label": "Shingles", "start": 20},
        {"label": "Flashing", "start": 50},
        {"label": "Gutters",  "start": 80},
        {"label": "Warranty", "start": 110},
    ]
    parts = propose_parts("v1", 150.0, nodes, min_parts=4, max_parts=7)
    _assert_non_overlapping_within_duration(parts, 150.0)


def test_propose_parts_starts_at_zero_ends_at_duration():
    nodes = [{"label": f"N{i}", "start": i * 30} for i in range(5)]
    duration = 180.0
    parts = propose_parts("v1", duration, nodes, min_parts=4, max_parts=7)
    assert parts[0]["start"] == pytest.approx(0.0)
    assert parts[-1]["end"] == pytest.approx(duration)


def test_propose_parts_sequential_start_equals_prev_end():
    nodes = [{"label": f"N{i}", "start": i * 25} for i in range(5)]
    parts = propose_parts("v1", 150.0, nodes, min_parts=4, max_parts=7)
    for i in range(1, len(parts)):
        assert parts[i]["start"] == pytest.approx(parts[i - 1]["end"])


# ---------------------------------------------------------------------------
# propose_parts — titles from node labels
# ---------------------------------------------------------------------------


def test_propose_parts_titles_from_labels():
    nodes = [
        {"label": "Shingles",   "start": 0},
        {"label": "Underlayment","start": 30},
        {"label": "Flashing",   "start": 60},
        {"label": "Gutters",    "start": 90},
    ]
    parts = propose_parts("v1", 120.0, nodes, min_parts=4, max_parts=7)
    titles = [p["title"] for p in parts]
    # At least some part titles should come from node labels
    label_set = {n["label"] for n in nodes}
    assert any(t in label_set for t in titles)


def test_propose_parts_fallback_title_when_no_label():
    nodes = [
        {"label": "", "start": 20},
        {"label": "", "start": 40},
        {"label": "", "start": 60},
        {"label": "", "start": 80},
    ]
    parts = propose_parts("v1", 100.0, nodes, min_parts=4, max_parts=7)
    for i, p in enumerate(parts):
        assert p["title"] == f"Part {i + 1}"


def test_propose_parts_missing_label_key_fallback():
    nodes = [
        {"start": 20},
        {"start": 40},
        {"start": 60},
        {"start": 80},
    ]
    parts = propose_parts("v1", 100.0, nodes, min_parts=4, max_parts=7)
    for i, p in enumerate(parts):
        assert p["title"] == f"Part {i + 1}"


# ---------------------------------------------------------------------------
# propose_parts — custom min/max
# ---------------------------------------------------------------------------


def test_propose_parts_custom_min_max():
    nodes = [{"label": f"T{i}", "start": i * 10} for i in range(10)]
    parts = propose_parts("v1", 100.0, nodes, min_parts=2, max_parts=3)
    assert 2 <= len(parts) <= 3


def test_propose_parts_min_equals_max_forces_exact_count():
    nodes = [{"label": f"T{i}", "start": i * 10} for i in range(10)]
    parts = propose_parts("v1", 100.0, nodes, min_parts=5, max_parts=5)
    assert len(parts) == 5


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _assert_non_overlapping_within_duration(parts, duration):
    for p in parts:
        assert p["start"] >= 0.0
        assert p["end"] <= duration + 1e-9
        assert p["start"] < p["end"]
    for i in range(1, len(parts)):
        assert parts[i]["start"] == pytest.approx(parts[i - 1]["end"])


def min_parts_valid(count, lo, hi):
    return lo <= count <= hi


def test_propose_parts_all_nodes_at_zero_triggers_even_split():
    # All nodes at start=0 → no usable interior boundaries → falls back to even split.
    nodes = [{"label": f"T{i}", "start": 0} for i in range(4)]
    parts = propose_parts("v1", 100.0, nodes, min_parts=4, max_parts=7)
    assert len(parts) == 4
    _assert_non_overlapping_within_duration(parts, 100.0)
    for i, p in enumerate(parts):
        assert p["title"] == f"Part {i + 1}"


def test_propose_parts_forced_n_cuts_with_many_nodes():
    # 6 interior nodes, max_parts=4 → n_cuts=3 < len(interior)=6 → enters sampling branch.
    # Verifies the evenly-sampled cut path produces valid non-overlapping parts.
    nodes = [{"label": f"T{i}", "start": i * 20 + 10} for i in range(6)]
    parts = propose_parts("v1", 200.0, nodes, min_parts=4, max_parts=4)
    assert len(parts) == 4
    _assert_non_overlapping_within_duration(parts, 200.0)
