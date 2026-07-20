"""censor_spans maps flagged words to merged mute spans."""
from core.censor import censor_spans, mute_audio_filter


def _words(*pairs):
    return [{"word": w, "start": s} for w, s in pairs]


def test_flags_tenant_denylist_word():
    words = _words(("we", 0.0), ("beat", 0.5), ("competitor", 1.0), ("easily", 1.8))
    spans = censor_spans(words, extra_denylist=["competitor"])
    assert spans == [(1.0, 1.8)]  # end = next word's start


def test_last_word_uses_tail_pad():
    words = _words(("hello", 0.0), ("competitor", 2.0))
    assert censor_spans(words, extra_denylist=["competitor"], tail_pad=0.5) == [(2.0, 2.5)]


def test_clean_transcript_no_spans():
    assert censor_spans(_words(("a", 0.0), ("b", 0.4)), extra_denylist=["nope"]) == []


def test_adjacent_flags_merge():
    words = _words(("x", 0.0), ("bad", 0.5), ("worse", 1.0), ("y", 1.5))
    assert censor_spans(words, extra_denylist=["bad", "worse"]) == [(0.5, 1.5)]


def test_case_and_punctuation_insensitive():
    words = _words(("Competitor,", 0.0), ("ok", 0.9))
    assert censor_spans(words, extra_denylist=["competitor"]) == [(0.0, 0.9)]


def test_unordered_input_is_sorted():
    words = _words(("competitor", 2.0), ("we", 0.0), ("beat", 1.0))
    assert censor_spans(words, extra_denylist=["competitor"]) == [(2.0, 2.4)]


def test_mute_filter_empty_when_no_spans():
    assert mute_audio_filter([]) == ""


def test_mute_filter_builds_volume_enable():
    f = mute_audio_filter([(1.0, 1.8), (2.0, 2.5)])
    assert f == "volume=enable='between(t,1.000,1.800)+between(t,2.000,2.500)':volume=0"
