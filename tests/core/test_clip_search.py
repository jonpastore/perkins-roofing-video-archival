"""Tests for core/clip_search.py — 100% line coverage required."""
from core.clip_search import build_candidates, search_to_clips

# ---------------------------------------------------------------------------
# build_candidates
# ---------------------------------------------------------------------------


def test_build_candidates_empty_chunks():
    assert build_candidates("roof leaks", []) == []


def test_build_candidates_pads_short_window():
    chunks = [{"video_id": "v1", "start": 10.0, "end": 15.0, "text": "flashing failure", "score": 0.9}]
    out = build_candidates("roof leaks", chunks)
    assert len(out) == 1
    c = out[0]
    assert c["end"] - c["start"] == 20.0
    # Symmetric pad: 5s window padded to 20s -> 7.5s each side.
    assert c["start"] == 2.5
    assert c["end"] == 22.5


def test_build_candidates_pad_clamped_at_zero():
    """A window near t=0 pads asymmetrically rather than going negative."""
    chunks = [{"video_id": "v1", "start": 1.0, "end": 3.0, "text": "intro", "score": 0.5}]
    out = build_candidates("roof leaks", chunks)
    assert out[0]["start"] == 0.0
    assert out[0]["end"] == 20.0


def test_build_candidates_caps_long_window():
    chunks = [{"video_id": "v1", "start": 0.0, "end": 90.0, "text": "long segment", "score": 0.8}]
    out = build_candidates("roof leaks", chunks)
    assert out[0]["start"] == 0.0
    assert out[0]["end"] == 60.0


def test_build_candidates_keeps_window_already_in_range():
    chunks = [{"video_id": "v1", "start": 5.0, "end": 35.0, "text": "just right", "score": 0.7}]
    out = build_candidates("roof leaks", chunks)
    assert out[0]["start"] == 5.0
    assert out[0]["end"] == 35.0


def test_build_candidates_skips_malformed_entries():
    chunks = [
        {"video_id": "v1", "start": "bad", "end": 10.0, "text": "t", "score": 1.0},  # ValueError
        None,  # AttributeError on .get
        {"video_id": None, "start": 0.0, "end": 10.0, "text": "no video id", "score": 1.0},
        {"video_id": "v2", "start": 10.0, "end": 5.0, "text": "end<=start", "score": 1.0},
        {"video_id": "v3", "start": 0.0, "end": 30.0, "text": "valid", "score": 1.0},
    ]
    out = build_candidates("roof leaks", chunks)
    assert len(out) == 1
    assert out[0]["video_id"] == "v3"


def test_build_candidates_dedupes_overlaps_keeping_higher_score():
    chunks = [
        {"video_id": "v1", "start": 0.0, "end": 30.0, "text": "low score", "score": 0.3},
        {"video_id": "v1", "start": 5.0, "end": 35.0, "text": "high score overlapping", "score": 0.9},
    ]
    out = build_candidates("roof leaks", chunks)
    assert len(out) == 1
    assert out[0]["text"] == "high score overlapping"


def test_build_candidates_keeps_non_overlapping_same_video():
    chunks = [
        {"video_id": "v1", "start": 0.0, "end": 30.0, "text": "first", "score": 0.9},
        {"video_id": "v1", "start": 40.0, "end": 60.0, "text": "second", "score": 0.5},
    ]
    out = build_candidates("roof leaks", chunks)
    assert len(out) == 2


def test_build_candidates_keeps_overlapping_across_different_videos():
    chunks = [
        {"video_id": "v1", "start": 0.0, "end": 30.0, "text": "vid1", "score": 0.9},
        {"video_id": "v2", "start": 0.0, "end": 30.0, "text": "vid2", "score": 0.8},
    ]
    out = build_candidates("roof leaks", chunks)
    assert len(out) == 2


def test_build_candidates_caps_top_n():
    chunks = [
        {"video_id": f"v{i}", "start": 0.0, "end": 30.0, "text": f"t{i}", "score": float(i)}
        for i in range(30)
    ]
    out = build_candidates("roof leaks", chunks)
    assert len(out) == 24
    # Highest scores kept
    assert out[0]["score"] == 29.0


# ---------------------------------------------------------------------------
# search_to_clips
# ---------------------------------------------------------------------------


def test_search_to_clips_empty_chunks():
    assert search_to_clips("roof leaks", []) == []


def test_search_to_clips_no_score_fn_ranks_by_retrieval_score():
    chunks = [
        {"video_id": "v1", "start": 0.0, "end": 30.0, "text": "low", "score": 0.2},
        {"video_id": "v2", "start": 0.0, "end": 30.0, "text": "high", "score": 0.9},
    ]
    out = search_to_clips("roof leaks", chunks)
    assert [c["video_id"] for c in out] == ["v2", "v1"]
    assert out[0]["reason"] == ""
    assert out[0]["text"] == "high"


def test_search_to_clips_score_fn_ranks_and_recovers_video_id():
    chunks = [{"video_id": "v1", "start": 5.0, "end": 35.0, "text": "flashing failure", "score": 0.5}]

    def fake_score_fn(_prompt):
        return '[{"start": 5.0, "end": 35.0, "score": 88, "reason": "great hook"}]'

    out = search_to_clips("roof leaks", chunks, score_fn=fake_score_fn)
    assert len(out) == 1
    assert out[0]["video_id"] == "v1"
    assert out[0]["score"] == 88
    assert out[0]["reason"] == "great hook"
    assert out[0]["text"] == "flashing failure"


def test_search_to_clips_all_moments_mismatch_falls_back_to_retrieval_score():
    # LLM mutated every window's times → nothing matches back. An empty result
    # would be wrong (candidates exist); retrieval order is the correct fallback.
    chunks = [{"video_id": "v1", "start": 5.0, "end": 35.0, "text": "flashing failure", "score": 0.5}]

    def fake_score_fn(_prompt):
        return '[{"start": 999.0, "end": 1000.0, "score": 50, "reason": "no match"}]'

    out = search_to_clips("roof leaks", chunks, score_fn=fake_score_fn)
    assert len(out) == 1
    assert out[0]["video_id"] == "v1"
    assert out[0]["reason"] == ""


def test_search_to_clips_partial_mismatch_keeps_only_matched_moments():
    # One LLM moment matches a candidate window, one doesn't — the mismatch is
    # skipped, the match survives (no fallback when at least one matches).
    chunks = [
        {"video_id": "v1", "start": 5.0, "end": 35.0, "text": "flashing", "score": 0.5},
        {"video_id": "v2", "start": 100.0, "end": 130.0, "text": "tile", "score": 0.4},
    ]

    def fake_score_fn(_prompt):
        return (
            '[{"start": 5.0, "end": 35.0, "score": 80, "reason": "hook"},'
            ' {"start": 999.0, "end": 1000.0, "score": 70, "reason": "phantom"}]'
        )

    out = search_to_clips("roof leaks", chunks, score_fn=fake_score_fn)
    assert len(out) == 1
    assert out[0]["video_id"] == "v1"
    assert out[0]["score"] == 80


def test_search_to_clips_score_fn_raises_falls_back_to_retrieval_score():
    chunks = [{"video_id": "v1", "start": 0.0, "end": 30.0, "text": "t", "score": 0.4}]

    def bad_score_fn(_prompt):
        raise RuntimeError("LLM unavailable")

    out = search_to_clips("roof leaks", chunks, score_fn=bad_score_fn)
    assert len(out) == 1
    assert out[0]["reason"] == ""


def test_search_to_clips_score_fn_returns_empty_falls_back_to_retrieval_score():
    chunks = [{"video_id": "v1", "start": 0.0, "end": 30.0, "text": "t", "score": 0.4}]

    def empty_score_fn(_prompt):
        return ""

    out = search_to_clips("roof leaks", chunks, score_fn=empty_score_fn)
    assert len(out) == 1
    assert out[0]["reason"] == ""
