"""Tests for core/speech_cleanup.py — 100% line coverage required."""
from core.speech_cleanup import (
    DEFAULT_PAD,
    build_cleanup_cmd,
    detect_fillers,
    keep_segments,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def w(word: str, start: float, end: float) -> dict:
    return {"word": word, "start": start, "end": end}


# ---------------------------------------------------------------------------
# detect_fillers — single-word fillers
# ---------------------------------------------------------------------------


def test_no_fillers_no_cuts():
    words = [w("the", 0.0, 0.2), w("roof", 0.3, 0.7), w("leaks", 0.8, 1.2)]
    assert detect_fillers(words) == []


def test_um_detected():
    words = [w("um", 0.0, 0.3), w("yes", 0.4, 0.8)]
    cuts = detect_fillers(words)
    assert len(cuts) == 1
    assert cuts[0] == {"start": 0.0, "end": 0.3}


def test_uh_detected():
    words = [w("roof", 0.0, 0.3), w("uh", 0.4, 0.6), w("it", 0.7, 0.9)]
    cuts = detect_fillers(words)
    assert len(cuts) == 1
    assert cuts[0] == {"start": 0.4, "end": 0.6}


def test_er_detected():
    cuts = detect_fillers([w("er", 0.0, 0.2)])
    assert len(cuts) == 1
    assert cuts[0]["start"] == 0.0


def test_ah_detected():
    cuts = detect_fillers([w("ah", 1.0, 1.2)])
    assert len(cuts) == 1
    assert cuts[0] == {"start": 1.0, "end": 1.2}


def test_hmm_detected():
    cuts = detect_fillers([w("hmm", 2.0, 2.4)])
    assert len(cuts) == 1


def test_like_detected():
    words = [w("it", 0.0, 0.2), w("like", 0.3, 0.5), w("falls", 0.6, 0.9)]
    cuts = detect_fillers(words)
    assert len(cuts) == 1
    assert cuts[0] == {"start": 0.3, "end": 0.5}


def test_mixed_case_filler():
    words = [w("Um", 0.0, 0.3), w("okay", 0.4, 0.8)]
    cuts = detect_fillers(words)
    assert len(cuts) == 1
    assert cuts[0]["start"] == 0.0


def test_punctuation_tolerant_filler():
    words = [w("um,", 0.0, 0.3), w("right", 0.4, 0.7)]
    cuts = detect_fillers(words)
    assert len(cuts) == 1


def test_multiple_fillers_in_sequence():
    words = [w("um", 0.0, 0.2), w("uh", 0.3, 0.5), w("roof", 0.6, 1.0)]
    cuts = detect_fillers(words)
    assert len(cuts) == 2
    assert cuts[0] == {"start": 0.0, "end": 0.2}
    assert cuts[1] == {"start": 0.3, "end": 0.5}


def test_filler_at_end():
    words = [w("roof", 0.0, 0.5), w("um", 0.6, 0.9)]
    cuts = detect_fillers(words)
    assert len(cuts) == 1
    assert cuts[0] == {"start": 0.6, "end": 0.9}


def test_empty_words_list():
    assert detect_fillers([]) == []


# ---------------------------------------------------------------------------
# detect_fillers — multi-word fillers ("you know")
# ---------------------------------------------------------------------------


def test_you_know_detected():
    words = [w("you", 1.0, 1.2), w("know", 1.3, 1.6), w("the", 1.7, 1.9)]
    cuts = detect_fillers(words)
    assert len(cuts) == 1
    assert cuts[0] == {"start": 1.0, "end": 1.6}


def test_you_know_case_insensitive():
    words = [w("You", 0.0, 0.2), w("Know", 0.3, 0.5)]
    cuts = detect_fillers(words)
    assert len(cuts) == 1
    assert cuts[0] == {"start": 0.0, "end": 0.5}


def test_you_know_at_end_of_list():
    words = [w("right", 0.0, 0.4), w("you", 0.5, 0.7), w("know", 0.8, 1.0)]
    cuts = detect_fillers(words)
    assert len(cuts) == 1
    assert cuts[0] == {"start": 0.5, "end": 1.0}


def test_partial_phrase_not_matched():
    # "you" alone should not be cut (not in single fillers)
    words = [w("you", 0.0, 0.3), w("should", 0.4, 0.7)]
    cuts = detect_fillers(words)
    assert cuts == []


def test_multi_word_filler_not_cut_if_incomplete_at_boundary():
    # Only one word left — "you know" requires two words
    words = [w("you", 0.0, 0.3)]
    cuts = detect_fillers(words)
    assert cuts == []


# ---------------------------------------------------------------------------
# detect_fillers — stutter repeats
# ---------------------------------------------------------------------------


def test_immediate_stutter_repeat():
    words = [w("the", 0.0, 0.2), w("the", 0.25, 0.45), w("roof", 0.5, 0.9)]
    cuts = detect_fillers(words)
    assert len(cuts) == 1
    assert cuts[0] == {"start": 0.25, "end": 0.45}


def test_triple_stutter():
    words = [
        w("the", 0.0, 0.2),
        w("the", 0.25, 0.45),
        w("the", 0.5, 0.7),
        w("roof", 0.8, 1.2),
    ]
    cuts = detect_fillers(words)
    assert len(cuts) == 2
    assert cuts[0] == {"start": 0.25, "end": 0.45}
    assert cuts[1] == {"start": 0.5, "end": 0.7}


def test_stutter_case_insensitive():
    words = [w("The", 0.0, 0.2), w("the", 0.25, 0.45), w("roof", 0.5, 0.9)]
    cuts = detect_fillers(words)
    assert len(cuts) == 1
    assert cuts[0]["start"] == 0.25


def test_stutter_with_punctuation():
    words = [w("roof.", 0.0, 0.4), w("roof", 0.5, 0.9)]
    cuts = detect_fillers(words)
    assert len(cuts) == 1


def test_non_consecutive_repeat_not_cut():
    words = [w("the", 0.0, 0.2), w("roof", 0.3, 0.6), w("the", 0.7, 0.9)]
    cuts = detect_fillers(words)
    assert cuts == []


# ---------------------------------------------------------------------------
# detect_fillers — custom filler set
# ---------------------------------------------------------------------------


def test_custom_filler_set():
    words = [w("basically", 0.0, 0.4), w("roof", 0.5, 0.9)]
    cuts = detect_fillers(words, fillers={"basically"})
    assert len(cuts) == 1
    assert cuts[0]["start"] == 0.0


def test_empty_filler_set_only_catches_stutters():
    words = [w("um", 0.0, 0.3), w("roof", 0.4, 0.8)]
    cuts = detect_fillers(words, fillers=set())
    assert cuts == []


def test_empty_filler_set_still_catches_stutters():
    words = [w("roof", 0.0, 0.4), w("roof", 0.5, 0.9)]
    cuts = detect_fillers(words, fillers=set())
    assert len(cuts) == 1


def test_empty_word_in_list_skipped():
    words = [w("", 0.0, 0.1), w("roof", 0.2, 0.6)]
    cuts = detect_fillers(words)
    assert cuts == []


def test_none_word_value_skipped():
    words = [{"word": None, "start": 0.0, "end": 0.1}, w("roof", 0.2, 0.6)]
    cuts = detect_fillers(words)
    assert cuts == []


# ---------------------------------------------------------------------------
# keep_segments — basic inversion
# ---------------------------------------------------------------------------


def test_no_cuts_returns_whole_clip():
    segs = keep_segments(10.0, [])
    assert segs == [{"start": 0.0, "end": 10.0}]


def test_single_cut_in_middle():
    cuts = [{"start": 2.0, "end": 3.0}]
    segs = keep_segments(10.0, cuts, pad=0.0)
    assert len(segs) == 2
    assert segs[0] == {"start": 0.0, "end": 2.0}
    assert segs[1] == {"start": 3.0, "end": 10.0}


def test_cut_at_start():
    cuts = [{"start": 0.0, "end": 1.0}]
    segs = keep_segments(5.0, cuts, pad=0.0)
    assert len(segs) == 1
    assert segs[0] == {"start": 1.0, "end": 5.0}


def test_cut_at_end():
    cuts = [{"start": 4.0, "end": 5.0}]
    segs = keep_segments(5.0, cuts, pad=0.0)
    assert len(segs) == 1
    assert segs[0] == {"start": 0.0, "end": 4.0}


def test_pad_shrinks_keeps():
    cuts = [{"start": 2.0, "end": 3.0}]
    segs = keep_segments(10.0, cuts, pad=0.1)
    assert len(segs) == 2
    assert abs(segs[0]["end"] - 1.9) < 1e-9
    assert abs(segs[1]["start"] - 3.1) < 1e-9


def test_multiple_cuts():
    cuts = [{"start": 1.0, "end": 2.0}, {"start": 5.0, "end": 6.0}]
    segs = keep_segments(10.0, cuts, pad=0.0)
    assert len(segs) == 3
    assert segs[0] == {"start": 0.0, "end": 1.0}
    assert segs[1] == {"start": 2.0, "end": 5.0}
    assert segs[2] == {"start": 6.0, "end": 10.0}


def test_cuts_sorted_out_of_order():
    cuts = [{"start": 5.0, "end": 6.0}, {"start": 1.0, "end": 2.0}]
    segs = keep_segments(10.0, cuts, pad=0.0)
    assert len(segs) == 3
    assert segs[0]["start"] == 0.0


def test_adjacent_keeps_not_merged_when_gap_positive():
    # Two cuts close together — keep between them is small but positive → two separate keeps
    cuts = [{"start": 1.0, "end": 1.05}, {"start": 1.1, "end": 1.15}]
    segs = keep_segments(5.0, cuts, pad=0.0)
    # keep before: [0, 1.0]; keep between: [1.05, 1.1]; keep after: [1.15, 5.0]
    assert len(segs) == 3
    assert all("start" in s and "end" in s for s in segs)


def test_pad_causes_inner_keep_to_vanish():
    # Cuts so close that the keep between them collapses entirely due to padding
    cuts = [{"start": 1.0, "end": 1.1}, {"start": 1.2, "end": 1.3}]
    segs = keep_segments(5.0, cuts, pad=0.2)
    # keep between cuts: keep_end=1.2-0.2=1.0, keep_start=1.1+0.2=1.3 → 1.0 < 1.3 → dropped
    # Result: keep [0, 0.8] and keep [1.5, 5.0]
    assert len(segs) == 2
    assert abs(segs[0]["end"] - 0.8) < 1e-9
    assert abs(segs[1]["start"] - 1.5) < 1e-9


def test_entire_clip_cut_falls_back_to_whole():
    # A cut that spans the entire clip with large pad
    cuts = [{"start": 0.0, "end": 10.0}]
    segs = keep_segments(10.0, cuts, pad=0.0)
    # No keeps survive — fallback returns whole clip
    assert segs == [{"start": 0.0, "end": 10.0}]


def test_default_pad_value():
    cuts = [{"start": 2.0, "end": 3.0}]
    segs = keep_segments(10.0, cuts)
    # Uses DEFAULT_PAD
    assert abs(segs[0]["end"] - (2.0 - DEFAULT_PAD)) < 1e-9
    assert abs(segs[1]["start"] - (3.0 + DEFAULT_PAD)) < 1e-9


# ---------------------------------------------------------------------------
# build_cleanup_cmd
# ---------------------------------------------------------------------------


def test_single_keep_no_concat():
    segs = [{"start": 0.0, "end": 10.0}]
    cmd = build_cleanup_cmd("in.mp4", "out.mp4", segs)
    assert cmd[0] == "ffmpeg"
    assert "in.mp4" in cmd
    assert "out.mp4" in cmd
    # Single-keep path: no concat filter, just trim
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "concat" not in fc
    assert "trim" in fc
    assert "[v0]" in fc
    assert "[a0]" in fc


def test_single_keep_maps():
    segs = [{"start": 1.0, "end": 5.0}]
    cmd = build_cleanup_cmd("src.mp4", "dst.mp4", segs)
    assert "-map" in cmd
    v_map_idx = [i for i, x in enumerate(cmd) if x == "-map"]
    assert cmd[v_map_idx[0] + 1] == "[v0]"
    assert cmd[v_map_idx[1] + 1] == "[a0]"


def test_multiple_keeps_uses_concat():
    segs = [{"start": 0.0, "end": 2.0}, {"start": 3.0, "end": 7.0}]
    cmd = build_cleanup_cmd("in.mp4", "out.mp4", segs)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "concat=n=2" in fc
    assert "[vout]" in fc
    assert "[aout]" in fc


def test_multiple_keeps_maps():
    segs = [{"start": 0.0, "end": 2.0}, {"start": 3.0, "end": 7.0}]
    cmd = build_cleanup_cmd("in.mp4", "out.mp4", segs)
    assert "[vout]" in cmd
    assert "[aout]" in cmd


def test_three_keeps_filter_labels():
    segs = [
        {"start": 0.0, "end": 1.0},
        {"start": 2.0, "end": 3.0},
        {"start": 4.0, "end": 5.0},
    ]
    cmd = build_cleanup_cmd("in.mp4", "out.mp4", segs)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "concat=n=3" in fc
    assert "[v0]" in fc
    assert "[v1]" in fc
    assert "[v2]" in fc
    assert "[a0]" in fc
    assert "[a1]" in fc
    assert "[a2]" in fc


def test_cmd_contains_codec_flags():
    segs = [{"start": 0.0, "end": 5.0}]
    cmd = build_cleanup_cmd("i.mp4", "o.mp4", segs)
    assert "-c:v" in cmd
    assert "libx264" in cmd
    assert "-c:a" in cmd
    assert "aac" in cmd


def test_cmd_overwrite_flag():
    segs = [{"start": 0.0, "end": 5.0}]
    cmd = build_cleanup_cmd("i.mp4", "o.mp4", segs)
    assert "-y" in cmd


def test_single_keep_trim_times():
    segs = [{"start": 1.5, "end": 8.3}]
    cmd = build_cleanup_cmd("in.mp4", "out.mp4", segs)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "start=1.5" in fc
    assert "end=8.3" in fc


def test_multiple_keeps_trim_times():
    segs = [{"start": 0.0, "end": 2.0}, {"start": 3.5, "end": 9.0}]
    cmd = build_cleanup_cmd("in.mp4", "out.mp4", segs)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "start=0.0" in fc
    assert "end=2.0" in fc
    assert "start=3.5" in fc
    assert "end=9.0" in fc


# ---------------------------------------------------------------------------
# Integration: detect → keep → cmd pipeline
# ---------------------------------------------------------------------------


def test_pipeline_filler_then_cmd():
    words = [
        w("so", 0.0, 0.3),
        w("um", 0.4, 0.6),
        w("the", 0.7, 0.9),
        w("roof", 1.0, 1.4),
    ]
    cuts = detect_fillers(words)
    assert len(cuts) == 1
    segs = keep_segments(2.0, cuts, pad=0.0)
    cmd = build_cleanup_cmd("clip.mp4", "clean.mp4", segs)
    assert "clip.mp4" in cmd
    assert "clean.mp4" in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "concat=n=2" in fc


def test_pipeline_no_fillers_single_segment():
    words = [w("great", 0.0, 0.5), w("roof", 0.6, 1.2)]
    cuts = detect_fillers(words)
    segs = keep_segments(1.5, cuts)
    assert segs == [{"start": 0.0, "end": 1.5}]
    cmd = build_cleanup_cmd("in.mp4", "out.mp4", segs)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "concat" not in fc


