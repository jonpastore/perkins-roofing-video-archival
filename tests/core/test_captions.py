"""Tests for core/captions.py — 100% line coverage required."""
import pytest

from core.captions import (
    caption_events,
    group_caption_lines,
    to_ass_karaoke,
    to_srt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_words(*pairs):
    """Build a word list from (word, start, end) tuples."""
    return [{"word": w, "start": s, "end": e} for w, s, e in pairs]


# ---------------------------------------------------------------------------
# group_caption_lines
# ---------------------------------------------------------------------------


def test_group_caption_lines_empty():
    assert group_caption_lines([]) == []


def test_group_caption_lines_single_word():
    words = make_words(("roof", 0.0, 0.5))
    lines = group_caption_lines(words)
    assert len(lines) == 1
    assert lines[0]["text"] == "roof"
    assert lines[0]["start"] == 0.0
    assert lines[0]["end"] == 0.5


def test_group_caption_lines_respects_max_chars():
    # "replacement" = 11 chars (fits in max_chars=15)
    # "replacement insurance" = 21 chars > 15 → break before "insurance"
    # "insurance" = 9 chars (fits); "insurance claim" = 15 chars = exactly max_chars, fits
    words = make_words(
        ("replacement", 0.0, 0.5),
        ("insurance", 0.6, 1.1),
        ("claim", 1.2, 1.6),
    )
    lines = group_caption_lines(words, max_chars=15, max_dur=99.0)
    assert len(lines) == 2
    assert lines[0]["text"] == "replacement"
    assert lines[1]["text"] == "insurance claim"


def test_group_caption_lines_respects_max_dur():
    words = make_words(
        ("wind", 0.0, 0.5),
        ("mitigation", 0.6, 1.2),
        ("discount", 3.5, 4.0),   # 4.0 - 0.0 = 4.0 > max_dur=3.0 → break before this
    )
    lines = group_caption_lines(words, max_chars=999, max_dur=3.0)
    assert len(lines) == 2
    assert "wind mitigation" in lines[0]["text"]
    assert lines[1]["text"] == "discount"


def test_group_caption_lines_skips_empty_words():
    words = [
        {"word": "  ", "start": 0.0, "end": 0.2},
        {"word": "roof", "start": 0.3, "end": 0.8},
        {"word": "", "start": 0.9, "end": 1.0},
        {"word": "damage", "start": 1.1, "end": 1.5},
    ]
    lines = group_caption_lines(words, max_chars=999, max_dur=99.0)
    assert len(lines) == 1
    assert lines[0]["text"] == "roof damage"


def test_group_caption_lines_all_empty_words():
    words = [{"word": "", "start": 0.0, "end": 0.1}]
    assert group_caption_lines(words) == []


def test_group_caption_lines_words_in_output():
    words = make_words(("tile", 0.0, 0.4), ("roof", 0.5, 0.9))
    lines = group_caption_lines(words, max_chars=999, max_dur=99.0)
    assert len(lines[0]["words"]) == 2


def test_group_caption_lines_start_end_from_words():
    words = make_words(("metal", 2.5, 2.9), ("shingle", 3.0, 3.6))
    lines = group_caption_lines(words, max_chars=999, max_dur=99.0)
    assert lines[0]["start"] == 2.5
    assert lines[0]["end"] == 3.6


def test_group_caption_lines_missing_end_defaults_to_start():
    words = [{"word": "test", "start": 1.0}]
    lines = group_caption_lines(words, max_chars=999, max_dur=99.0)
    assert lines[0]["end"] == 1.0


def test_group_caption_lines_multiple_lines_correct_boundaries():
    # 5 words, max_chars=10 → each word forces a new line
    words = make_words(
        ("hurricane", 0.0, 0.5),  # 9 chars — fits in max_chars=10
        ("resistant", 0.6, 1.1),  # "hurricane resistant" = 19 > 10 → new line
        ("shingles", 1.2, 1.7),
    )
    lines = group_caption_lines(words, max_chars=10, max_dur=99.0)
    assert lines[0]["text"] == "hurricane"
    assert lines[1]["text"] == "resistant"
    assert lines[2]["text"] == "shingles"


# ---------------------------------------------------------------------------
# caption_events
# ---------------------------------------------------------------------------


def test_caption_events_empty():
    assert caption_events([]) == []


def test_caption_events_k_cs_first_word_is_zero():
    words = make_words(("roof", 1.0, 1.5), ("repair", 1.6, 2.0))
    events = caption_events(words, max_chars=999, max_dur=99.0)
    assert len(events) == 1
    assert events[0]["words"][0]["k_cs"] == 0


def test_caption_events_k_cs_subsequent_word():
    # word 0 starts at 1.0, word 1 starts at 1.5 → k_cs for word 1 = (1.5 - 1.0) * 100 = 50
    words = make_words(("roof", 1.0, 1.4), ("leak", 1.5, 2.0))
    events = caption_events(words, max_chars=999, max_dur=99.0)
    assert events[0]["words"][1]["k_cs"] == 50


def test_caption_events_structure():
    words = make_words(("Citizens", 0.0, 0.4), ("Insurance", 0.5, 0.9))
    events = caption_events(words, max_chars=999, max_dur=99.0)
    ev = events[0]
    assert "text" in ev
    assert "start" in ev
    assert "end" in ev
    assert "words" in ev
    for w in ev["words"]:
        assert "word" in w
        assert "start" in w
        assert "end" in w
        assert "k_cs" in w


def test_caption_events_k_cs_non_negative():
    # If timestamps are not monotonic (edge case), k_cs must not go negative
    words = [
        {"word": "roof", "start": 0.0, "end": 0.5},
        {"word": "damage", "start": 0.0, "end": 0.5},  # same start
    ]
    events = caption_events(words, max_chars=999, max_dur=99.0)
    for w in events[0]["words"]:
        assert w["k_cs"] >= 0


# ---------------------------------------------------------------------------
# to_ass_karaoke
# ---------------------------------------------------------------------------


def test_to_ass_karaoke_contains_header():
    words = make_words(("roofing", 0.0, 0.5))
    lines = group_caption_lines(words)
    ass = to_ass_karaoke(lines)
    assert "[Script Info]" in ass
    assert "[V4+ Styles]" in ass
    assert "[Events]" in ass


def test_to_ass_karaoke_default_style():
    words = make_words(("roofing", 0.0, 0.5))
    lines = group_caption_lines(words)
    ass = to_ass_karaoke(lines, style="default")
    assert "Arial" in ass
    assert "Dialogue:" in ass


def test_to_ass_karaoke_bold_yellow_style():
    words = make_words(("roofing", 0.0, 0.5))
    lines = group_caption_lines(words)
    ass = to_ass_karaoke(lines, style="bold_yellow")
    assert "BoldYellow" in ass
    assert "Arial Black" in ass


def test_to_ass_karaoke_unknown_style_falls_back_to_default():
    words = make_words(("test", 0.0, 0.4))
    lines = group_caption_lines(words)
    ass = to_ass_karaoke(lines, style="nonexistent_style")
    assert "Default" in ass


def test_to_ass_karaoke_karaoke_tags_present():
    words = make_words(("wind", 0.0, 0.4), ("damage", 0.5, 1.0))
    lines = group_caption_lines(words, max_chars=999, max_dur=99.0)
    ass = to_ass_karaoke(lines)
    assert r"\k" in ass


def test_to_ass_karaoke_timestamps_format():
    words = make_words(("roof", 3661.5, 3662.0))  # 1h 1m 1.5s
    lines = group_caption_lines(words)
    ass = to_ass_karaoke(lines)
    # ASS timestamp: H:MM:SS.cc
    assert "1:01:01.50" in ass


def test_to_ass_karaoke_empty_lines():
    ass = to_ass_karaoke([])
    assert "[Script Info]" in ass
    assert "Dialogue:" not in ass


def test_to_ass_karaoke_line_without_words_key():
    # Lines that have no 'words' key should use raw 'text'
    lines = [{"text": "fallback text", "start": 0.0, "end": 2.0}]
    ass = to_ass_karaoke(lines)
    assert "fallback text" in ass


def test_to_ass_karaoke_multiple_lines():
    words = make_words(
        ("Citizens", 0.0, 0.4),
        ("Insurance", 0.5, 0.9),
        ("renewal", 4.0, 4.5),
    )
    lines = group_caption_lines(words, max_chars=999, max_dur=3.0)
    ass = to_ass_karaoke(lines)
    assert ass.count("Dialogue:") == 2


# ---------------------------------------------------------------------------
# to_srt
# ---------------------------------------------------------------------------


def test_to_srt_empty():
    assert to_srt([]) == ""


def test_to_srt_single_line():
    words = make_words(("roofing", 0.0, 1.0))
    lines = group_caption_lines(words)
    srt = to_srt(lines)
    assert "1\n" in srt
    assert "00:00:00,000 --> 00:00:01,000" in srt
    assert "roofing" in srt


def test_to_srt_numbering():
    words = make_words(
        ("wind", 0.0, 0.5),
        ("damage", 0.6, 1.0),
        ("claim", 5.0, 5.5),
    )
    lines = group_caption_lines(words, max_chars=999, max_dur=2.0)
    srt = to_srt(lines)
    assert "1\n" in srt
    assert "2\n" in srt


def test_to_srt_timestamp_format():
    words = make_words(("test", 3661.123, 3662.456))
    lines = group_caption_lines(words)
    srt = to_srt(lines)
    # SRT: HH:MM:SS,mmm
    assert "01:01:01,123" in srt
    assert "01:01:02,456" in srt


def test_to_srt_no_karaoke_tags():
    words = make_words(("wind", 0.0, 0.5), ("damage", 0.6, 1.0))
    lines = group_caption_lines(words, max_chars=999, max_dur=99.0)
    srt = to_srt(lines)
    assert r"\k" not in srt


def test_to_srt_blocks_separated_by_blank_line():
    words = make_words(
        ("roofing", 0.0, 0.5),
        ("insurance", 5.0, 5.5),
    )
    lines = group_caption_lines(words, max_chars=999, max_dur=2.0)
    srt = to_srt(lines)
    assert "\n\n" in srt


# ---------------------------------------------------------------------------
# _ass_ts and _srt_ts indirectly via to_ass_karaoke / to_srt (edge cases)
# ---------------------------------------------------------------------------


def test_to_srt_zero_timestamp():
    lines = [{"text": "hello", "start": 0.0, "end": 0.0}]
    srt = to_srt(lines)
    assert "00:00:00,000 --> 00:00:00,000" in srt


def test_to_ass_karaoke_zero_timestamp():
    lines = [{"text": "hello", "start": 0.0, "end": 0.0, "words": []}]
    ass = to_ass_karaoke(lines)
    assert "0:00:00.00" in ass
