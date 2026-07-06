"""Tests for core/miniseries.py — pure mini-series planner."""

import pytest

from core.miniseries import clean_title, propose_clips, propose_parts, rank_candidates

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
    # At least some part titles should contain a node label (now embedded in composite
    # titles like "Flashing (Part 2)" or "Metal Roof — Flashing (Part 2)")
    label_set = {n["label"] for n in nodes}
    assert any(any(lbl in t for lbl in label_set) for t in titles)


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


# ---------------------------------------------------------------------------
# clean_title
# ---------------------------------------------------------------------------


def test_clean_title_strips_emoji_and_hashtags():
    assert clean_title("\U0001F3E0 Roof Repair 101 #roofing #diy") == "Roof Repair 101"


def test_clean_title_none_and_empty():
    assert clean_title(None) == ""
    assert clean_title("") == ""
    assert clean_title("\U0001F525\U0001F525") == ""


def test_clean_title_collapses_whitespace_and_leading_junk():
    assert clean_title("—  Gutters   Guide  ") == "Gutters Guide"


# ---------------------------------------------------------------------------
# propose_clips — content-driven, REAL seconds (the fixed logic)
# ---------------------------------------------------------------------------


def _assert_real_second_clips(clips, duration):
    """Every clip must be real seconds: in-bounds, positive-length, chronological, non-overlapping.

    Explicitly guards against the old 0/.25/.5/.75-of-1 fraction bug.
    """
    assert clips, "expected at least one clip"
    prev_end = -1.0
    for c in clips:
        assert c["start"] >= 0.0
        assert c["end"] > c["start"]
        if duration > 0:
            assert c["end"] <= duration + 1e-6
        # Not a degenerate fraction-of-1 window
        assert not (c["start"] == 0.0 and c["end"] <= 1.0 and duration > 1.0)
        assert c["start"] >= prev_end - 1e-6  # non-overlapping, chronological
        prev_end = c["end"]


def test_propose_clips_uses_real_node_start_times():
    nodes = [
        {"kind": "topics", "label": "Flashing", "start": 40.0},
        {"kind": "ctas", "label": "Free Inspection", "start": 120.0},
        {"kind": "claims", "label": "Warranty", "start": 200.0},
    ]
    clips = propose_clips("Roof Tips", 300.0, nodes)
    _assert_real_second_clips(clips, 300.0)
    starts = {c["start"] for c in clips}
    # Real node anchors preserved (not fractions)
    assert 40.0 in starts and 120.0 in starts and 200.0 in starts


def test_propose_clips_titles_include_name_topic_and_part_n():
    nodes = [{"kind": "topics", "label": "Flashing", "start": 30.0}]
    clips = propose_clips("\U0001F3E0 Roof Repair #diy", 200.0, nodes)
    t = clips[0]["title"]
    assert "Roof Repair" in t       # cleaned source video name
    assert "Flashing" in t          # topic
    assert t.rstrip().endswith("(Part 1)")  # Part N at the END
    assert "\U0001F3E0" not in t and "#" not in t


def test_propose_clips_clip_length_bounded_20_60():
    nodes = [{"kind": "ctas", "label": "CTA", "start": 10.0}]
    clips = propose_clips("V", 600.0, nodes, clip_len=40.0)
    length = clips[0]["end"] - clips[0]["start"]
    assert 20.0 <= length <= 60.0


def test_propose_clips_clamps_to_duration():
    nodes = [{"kind": "ctas", "label": "End CTA", "start": 95.0}]
    clips = propose_clips("V", 100.0, nodes, clip_len=40.0)
    for c in clips:
        assert c["end"] <= 100.0


def test_propose_clips_caps_at_max_clips():
    nodes = [{"kind": "topics", "label": f"T{i}", "start": i * 30.0} for i in range(12)]
    clips = propose_clips("V", 1000.0, nodes, max_clips=5)
    assert len(clips) <= 5


def test_propose_clips_prioritizes_ctas_and_claims():
    nodes = [
        {"kind": "topics", "label": "Topic", "start": 10.0},
        {"kind": "topics", "label": "Topic2", "start": 20.0},
        {"kind": "ctas", "label": "Call Now", "start": 300.0},
        {"kind": "claims", "label": "Big Claim", "start": 350.0},
    ]
    clips = propose_clips("V", 400.0, nodes, max_clips=2)
    labels = " ".join(c["title"] for c in clips)
    # The two highest-value nodes (cta + claim) should win over the topics.
    assert "Call Now" in labels and "Big Claim" in labels


def test_propose_clips_fallback_no_nodes_still_real_seconds():
    clips = propose_clips("Roofing Basics", 300.0, [])
    _assert_real_second_clips(clips, 300.0)
    # No node → evenly spaced real windows, NOT 0-0.25 fractions
    assert clips[0]["end"] > 1.0


def test_propose_clips_zero_duration_gives_single_bounded_clip():
    clips = propose_clips("V", 0.0, [{"kind": "topics", "label": "X", "start": 5.0}])
    assert len(clips) == 1
    assert clips[0]["start"] == 0.0
    assert clips[0]["end"] > 0.0


def test_propose_clips_regression_not_fraction_of_one():
    """The old bug: duration defaulted to 1 → parts at 0/.25/.5/.75. Must never happen."""
    nodes = [{"kind": "topics", "label": "A", "start": 60.0}]
    clips = propose_clips("V", 240.0, nodes)
    assert not any(c["end"] <= 1.0 for c in clips)


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


def test_propose_topic_clips_multi_source():
    from core.miniseries import propose_topic_clips
    sources = [
        {"video_id": "A", "video_title": "Metal Roof Basics", "duration": 300,
         "graph_nodes": [{"label": "underlayment for metal roofs", "start": 40, "kind": "claims"}]},
        {"video_id": "B", "video_title": "Underlayment Layers", "duration": 120,
         "graph_nodes": [{"label": "metal roof underlayment layers", "start": 22, "kind": "ctas"}]},
        {"video_id": "C", "video_title": "Gutters", "duration": 200,
         "graph_nodes": [{"label": "gutter cleaning", "start": 10, "kind": "topics"}]},
    ]
    parts = propose_topic_clips("Metal roof underlayment", sources, max_clips=5)
    # C is off-topic → excluded; A and B included, each with its own video_id + real offsets
    assert {p["video_id"] for p in parts} == {"A", "B"}
    assert all(p["end"] > p["start"] for p in parts)
    assert all(p["title"].endswith(f"(Part {i + 1})") for i, p in enumerate(parts))
