"""Unit tests for core.comments.needs_reply — pure function, no I/O."""
import pytest
from core.comments import needs_reply


# ---------------------------------------------------------------------------
# has_channel_reply=True — always False regardless of text
# ---------------------------------------------------------------------------

def test_already_replied_question_mark():
    assert needs_reply("Is this a question?", has_channel_reply=True) is False


def test_already_replied_question_word():
    assert needs_reply("How long does installation take", has_channel_reply=True) is False


def test_already_replied_plain():
    assert needs_reply("Great video!", has_channel_reply=True) is False


# ---------------------------------------------------------------------------
# Ends with '?' → flag
# ---------------------------------------------------------------------------

def test_ends_with_question_mark():
    assert needs_reply("How long does it take?", has_channel_reply=False) is True


def test_ends_with_question_mark_no_space():
    assert needs_reply("Will this work?", has_channel_reply=False) is True


def test_ends_with_question_mark_after_whitespace():
    # Leading/trailing whitespace is stripped before checking — still flagged.
    assert needs_reply("  Can you help me?  ", has_channel_reply=False) is True


def test_ends_with_question_mark_stripped():
    # The function checks stripped text for '?'
    text = "Can you help me?"
    assert needs_reply(text, has_channel_reply=False) is True


# ---------------------------------------------------------------------------
# Question words → flag (no '?')
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("word,text", [
    ("who",    "I wonder who does the installation"),
    ("what",   "I want to know what materials you use"),
    ("when",   "Curious when you can come out"),
    ("where",  "Not sure where to start"),
    ("why",    "Not sure why it leaked"),
    ("how",    "Wondering how much it costs"),
    ("can",    "I can see this might work"),
    ("does",   "It does seem expensive"),
    ("is",     "Is there a warranty on this"),
    ("should", "I think I should call you"),
])
def test_question_word_detected(word, text):
    assert needs_reply(text, has_channel_reply=False) is True, f"Expected flag for word '{word}' in: {text!r}"


def test_question_word_case_insensitive():
    assert needs_reply("HOW do I get a quote", has_channel_reply=False) is True
    assert needs_reply("WHO should I contact", has_channel_reply=False) is True


# ---------------------------------------------------------------------------
# Plain statements — no flag
# ---------------------------------------------------------------------------

def test_plain_compliment():
    assert needs_reply("Great video, very helpful!", has_channel_reply=False) is False


def test_plain_statement():
    assert needs_reply("Thanks for sharing this information.", has_channel_reply=False) is False


def test_empty_string():
    assert needs_reply("", has_channel_reply=False) is False


def test_none_like_empty():
    assert needs_reply("", has_channel_reply=False) is False


def test_just_punctuation():
    assert needs_reply("!!!", has_channel_reply=False) is False


# ---------------------------------------------------------------------------
# Edge: question mark mid-sentence (not at end) — still flagged if ends with '?'
# ---------------------------------------------------------------------------

def test_question_mark_mid_sentence_no_end():
    # '?' in middle, statement ends with period → no flag unless question word present
    assert needs_reply("I asked? Then I got the answer.", has_channel_reply=False) is False


def test_multiple_sentences_last_ends_with_question():
    assert needs_reply("Great video. Can you do mine?", has_channel_reply=False) is True
