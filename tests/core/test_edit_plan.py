"""Transcript edit plan: fluff cuts, split vs tighten, 15/30 minute rules."""
from __future__ import annotations

from core.edit_plan import (
    EVAL_MAX_SECS,
    LONG_SECS,
    _is_fluff,
    keep_ranges,
    plan,
    recommend,
    topic_blocks,
)


def test_thresholds():
    assert LONG_SECS == 900
    assert EVAL_MAX_SECS == 1800


def _seg(start, end, text):
    return {"start": start, "end": end, "text": text}


TILE = "Foam the tile, set the hip, and check the Miami-Dade notice of acceptance."
METAL = "Standing seam panels need stainless screws in salt air or they rust out."
HOA = "The HOA cannot ban a metal roof after the 2024 Florida law change."


def test_fluff_intro_is_cut_and_keep_range_starts_at_the_point():
    segs = [
        _seg(0, 40, "Hey guys uh thanks for watching smash that like button you know"),
        _seg(40, 100, TILE),
        _seg(100, 130, "Anyway um you know like I said thanks for watching"),
    ]
    out = plan(duration=130, segments=segs)
    assert out["cut_seconds"] >= 50
    assert out["keep"][0]["start"] >= 35
    assert any("tile" in k["label"].lower() or "foam" in (k.get("label") or "").lower()
               or k["start"] >= 40 for k in out["keep"])


def test_under_30_single_topic_with_fluff_recommends_tighten():
    segs = [
        _seg(0, 50, "Um so yeah you know thanks for watching hit subscribe"),
        _seg(50, 400, TILE + " " + TILE),
        _seg(400, 450, "Anyway like I said you know smash subscribe"),
    ]
    out = plan(duration=450, segments=segs, topics=[{"label": "Tile foam method", "start": 50}])
    assert out["action"] == "tighten"
    assert out["target_seconds"] < out["duration"]
    assert out["target_seconds"] > 200


def test_two_substantial_topics_recommends_split():
    segs = [
        _seg(0, 200, TILE),
        _seg(200, 220, "Alright switching gears here"),
        _seg(220, 500, HOA),
    ]
    topics = [
        {"label": "Tile foam method", "start": 0},
        {"label": "HOA metal roof law", "start": 220},
    ]
    out = plan(duration=500, segments=segs, topics=topics)
    assert out["action"] == "split"
    assert len(out["pieces"]) >= 2
    assert out["pieces"][0]["end"] <= 230
    assert out["pieces"][1]["start"] >= 200


def test_over_30_minutes_is_chop_even_with_one_topic():
    segs = [_seg(0, 2000, TILE * 20)]
    out = plan(duration=2000, segments=segs, topics=[{"label": "Tile", "start": 0}])
    assert out["action"] == "chop"
    assert out["duration"] > EVAL_MAX_SECS


def test_empty_transcript_does_not_invent_cuts():
    out = plan(duration=1000, segments=[], topics=[])
    assert out["action"] in {"chop", "unknown"}
    assert out["keep"] == []
    assert out["cut_seconds"] == 0


def test_recommend_prefers_split_when_both_possible():
    rec = recommend(
        duration=1200,
        keep_seconds=900,
        fluff_ratio=0.2,
        n_pieces=3,
    )
    assert rec == "split"


def test_blank_topic_labels_and_zero_length_segments_are_ignored():
    out = plan(
        duration=200,
        segments=[{"start": 10, "end": 10, "text": "x"}, {"start": 20, "end": 80, "text": TILE}],
        topics=[{"label": "  ", "start": 0}, {"label": "Tile", "start": 20}],
    )
    assert out["keep"]
    assert out["action"] in {"tighten", "split", "chop"}


def test_short_video_without_fluff_still_gets_a_verdict():
    out = plan(duration=120, segments=[_seg(0, 120, TILE)])
    assert out["action"] in {"tighten", "unknown"}
    assert out["cut_seconds"] >= 0


def test_zero_duration_segment_is_fluff():
    assert _is_fluff("anything", 0) is True


def test_punctuation_only_and_short_dense_noise_are_fluff():
    assert keep_ranges([_seg(0, 12, "…"), _seg(12, 24, "ok ok")]) == []


def test_keep_ranges_do_not_merge_across_a_wide_gap():
    kept = keep_ranges([
        _seg(0, 30, TILE),
        _seg(80, 120, METAL),
    ])
    assert len(kept) == 2


def test_tiny_topic_blocks_collapse_into_neighbors():
    blocks = topic_blocks(
        [
            {"label": "Tile", "start": 0},
            {"label": "Aside", "start": 200},
            {"label": "HOA", "start": 220},
        ],
        400,
    )
    assert len(blocks) >= 1
    assert blocks[0]["start"] == 0.0
    assert blocks[-1]["end"] == 400


def test_all_tiny_topics_become_one_block():
    blocks = topic_blocks(
        [{"label": "A", "start": 0}, {"label": "B", "start": 10}],
        40,
    )
    assert len(blocks) == 1


def test_recommend_chop_when_over_15_and_no_fluff_or_splits():
    assert recommend(duration=1000, keep_seconds=1000, fluff_ratio=0.0, n_pieces=1) == "chop"


def test_no_transcript_under_15_is_unknown():
    out = plan(duration=200, segments=[])
    assert out["action"] == "unknown"


def test_recommend_tighten_when_one_piece_and_under_30():
    rec = recommend(
        duration=1200,
        keep_seconds=800,
        fluff_ratio=0.25,
        n_pieces=1,
    )
    assert rec == "tighten"
