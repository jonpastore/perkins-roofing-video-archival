"""Tests for core/captions_emoji.py — 100% coverage required."""
from core.captions_emoji import (
    KEYWORD_EMOJI_MAP,
    apply_emoji_highlights,
    build_karaoke_word,
    _token,
)


# ---------------------------------------------------------------------------
# _token
# ---------------------------------------------------------------------------

def test_token_lowercases():
    assert _token("Roof") == "roof"


def test_token_strips_punctuation():
    assert _token("roof.") == "roof"
    assert _token("shingle,") == "shingle"


def test_token_strips_apostrophe():
    assert _token("Tim's") == "tims"


def test_token_empty():
    assert _token("") == ""


# ---------------------------------------------------------------------------
# KEYWORD_EMOJI_MAP
# ---------------------------------------------------------------------------

def test_keyword_map_nonempty():
    assert len(KEYWORD_EMOJI_MAP) > 0


def test_keyword_map_roof():
    assert "roof" in KEYWORD_EMOJI_MAP
    assert KEYWORD_EMOJI_MAP["roof"]  # non-empty emoji string


def test_keyword_map_leak():
    assert "leak" in KEYWORD_EMOJI_MAP


def test_keyword_map_hurricane():
    assert "hurricane" in KEYWORD_EMOJI_MAP


def test_keyword_map_warranty():
    assert "warranty" in KEYWORD_EMOJI_MAP


def test_keyword_map_cost():
    assert "cost" in KEYWORD_EMOJI_MAP


def test_keyword_map_tile():
    assert "tile" in KEYWORD_EMOJI_MAP


# ---------------------------------------------------------------------------
# apply_emoji_highlights
# ---------------------------------------------------------------------------

def _word(w, start=0.0, end=0.5):
    return {"word": w, "start": start, "end": end}


def test_apply_emoji_matched_word():
    words = [_word("roof")]
    result = apply_emoji_highlights(words)
    assert result[0]["highlight"] is True
    assert result[0]["emoji"] == KEYWORD_EMOJI_MAP["roof"]


def test_apply_emoji_unmatched_word():
    words = [_word("inspector")]
    result = apply_emoji_highlights(words, keyword_map={})
    assert result[0]["highlight"] is False
    assert result[0]["emoji"] == ""


def test_apply_emoji_case_insensitive():
    words = [_word("ROOF")]
    result = apply_emoji_highlights(words)
    assert result[0]["highlight"] is True


def test_apply_emoji_punctuated_word():
    words = [_word("roof.")]
    result = apply_emoji_highlights(words)
    assert result[0]["highlight"] is True


def test_apply_emoji_does_not_mutate_input():
    words = [_word("roof")]
    apply_emoji_highlights(words)
    assert "highlight" not in words[0]
    assert "emoji" not in words[0]


def test_apply_emoji_preserves_original_keys():
    words = [_word("damage", start=1.0, end=1.5)]
    result = apply_emoji_highlights(words)
    assert result[0]["word"] == "damage"
    assert result[0]["start"] == 1.0
    assert result[0]["end"] == 1.5


def test_apply_emoji_custom_map():
    km = {"tile": "X"}
    words = [_word("tile")]
    result = apply_emoji_highlights(words, keyword_map=km)
    assert result[0]["emoji"] == "X"
    assert result[0]["highlight"] is True


def test_apply_emoji_empty_word_dict():
    words = [{"word": "", "start": 0.0, "end": 0.1}]
    result = apply_emoji_highlights(words)
    assert result[0]["highlight"] is False
    assert result[0]["emoji"] == ""


def test_apply_emoji_none_word_value():
    words = [{"word": None, "start": 0.0, "end": 0.1}]
    result = apply_emoji_highlights(words)
    assert result[0]["highlight"] is False


def test_apply_emoji_multiple_words_mixed():
    words = [_word("roof"), _word("is"), _word("leaking")]
    result = apply_emoji_highlights(words)
    assert result[0]["highlight"] is True
    assert result[1]["highlight"] is False
    assert result[2]["highlight"] is True


def test_apply_emoji_empty_list():
    assert apply_emoji_highlights([]) == []


# ---------------------------------------------------------------------------
# build_karaoke_word
# ---------------------------------------------------------------------------

def test_build_karaoke_word_no_emoji_no_highlight():
    out = build_karaoke_word("roof", 50)
    assert out == r"{\k50}roof"


def test_build_karaoke_word_with_emoji_no_highlight():
    out = build_karaoke_word("roof", 50, emoji="\U0001f3e0", highlight=False)
    assert r"{\k50}" in out
    assert "\U0001f3e0" in out
    assert r"{\c&" not in out


def test_build_karaoke_word_with_highlight_no_emoji():
    out = build_karaoke_word("damage", 30, emoji="", highlight=True)
    assert r"{\k30}" in out
    assert r"{\c&H002222CC&}" in out
    assert r"{\c}" in out


def test_build_karaoke_word_with_highlight_and_emoji():
    out = build_karaoke_word("leak", 40, emoji="\U0001f4a7", highlight=True)
    assert r"{\k40}" in out
    assert r"{\c&H002222CC&}" in out
    assert "\U0001f4a7" in out
    assert r"{\c}" in out


def test_build_karaoke_word_zero_duration():
    out = build_karaoke_word("test", 0)
    assert r"{\k0}" in out


# ---------------------------------------------------------------------------
# Integration: to_ass_karaoke with emoji_map
# ---------------------------------------------------------------------------

def test_to_ass_karaoke_with_emoji_map_contains_emoji():
    from core.captions import caption_events, group_caption_lines, to_ass_karaoke
    words = [
        {"word": "roof", "start": 0.0, "end": 0.4},
        {"word": "damage", "start": 0.5, "end": 0.9},
    ]
    lines = group_caption_lines(words, max_chars=999, max_dur=99.0)
    ass = to_ass_karaoke(lines, emoji_map=KEYWORD_EMOJI_MAP)
    assert KEYWORD_EMOJI_MAP["roof"] in ass
    assert KEYWORD_EMOJI_MAP["damage"] in ass


def test_to_ass_karaoke_without_emoji_map_no_emoji():
    from core.captions import group_caption_lines, to_ass_karaoke
    words = [{"word": "roof", "start": 0.0, "end": 0.4}]
    lines = group_caption_lines(words, max_chars=999, max_dur=99.0)
    ass = to_ass_karaoke(lines, emoji_map=None)
    assert KEYWORD_EMOJI_MAP["roof"] not in ass


def test_to_ass_karaoke_with_empty_emoji_map():
    from core.captions import group_caption_lines, to_ass_karaoke
    words = [{"word": "roof", "start": 0.0, "end": 0.4}]
    lines = group_caption_lines(words, max_chars=999, max_dur=99.0)
    # Empty map = emoji processing active but no matches
    ass = to_ass_karaoke(lines, emoji_map={})
    assert KEYWORD_EMOJI_MAP["roof"] not in ass
    assert r"\k" in ass
