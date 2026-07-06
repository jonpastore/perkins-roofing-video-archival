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
# Ends with '?' → flag (Rule 2)
# ---------------------------------------------------------------------------

def test_ends_with_question_mark():
    assert needs_reply("How long does it take?", has_channel_reply=False) is True


def test_ends_with_question_mark_no_space():
    assert needs_reply("Will this work?", has_channel_reply=False) is True


def test_ends_with_question_mark_after_whitespace():
    # Leading/trailing whitespace stripped before checking
    assert needs_reply("  Can you help me?  ", has_channel_reply=False) is True


def test_ends_with_question_mark_stripped():
    assert needs_reply("Can you help me?", has_channel_reply=False) is True


def test_multi_sentence_last_ends_with_question():
    assert needs_reply("Great video. Can you do mine?", has_channel_reply=False) is True


# ---------------------------------------------------------------------------
# First sentence starts with interrogative AND has '?' → flag (Rule 3)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("word,text", [
    ("who",    "Who does the installation around here?"),
    ("what",   "What materials do you use for flat roofs?"),
    ("when",   "When can you come out for an estimate?"),
    ("where",  "Where are you located?"),
    ("why",    "Why does my roof keep leaking?"),
    ("how",    "How much does a full replacement cost?"),
    ("which",  "Which shingles are best for cold climates?"),
    ("can",    "Can you do a free estimate?"),
    ("could",  "Could you help with insurance claims?"),
    ("would",  "Would you be able to come this week?"),
    ("should", "Should I repair or replace my roof?"),
    ("does",   "Does the warranty cover hail damage?"),
    ("do",     "Do you service the downtown area?"),
    ("is",     "Is there a warranty on this work?"),
    ("are",    "Are you licensed and insured?"),
    ("will",   "Will this fix the leak permanently?"),
])
def test_interrogative_first_sentence_with_question_mark(word, text):
    assert needs_reply(text, has_channel_reply=False) is True, (
        f"Expected True for interrogative '{word}' with '?': {text!r}"
    )


def test_question_word_case_insensitive():
    assert needs_reply("HOW much does it cost?", has_channel_reply=False) is True
    assert needs_reply("WHO should I contact?", has_channel_reply=False) is True


# ---------------------------------------------------------------------------
# FALSE POSITIVE guard — plain compliments/statements must return False
# ---------------------------------------------------------------------------

def test_this_is_great_no_flag():
    # "is" appears but it's not a question — no '?'
    assert needs_reply("This is great", has_channel_reply=False) is False


def test_what_a_great_video_no_flag():
    # "What" appears but comment ends with '!' not '?' — exclamatory, not interrogative
    assert needs_reply("What a great video!", has_channel_reply=False) is False


def test_how_informative_no_flag():
    # "how" in an exclamatory statement
    assert needs_reply("How informative this was!", has_channel_reply=False) is False


def test_should_in_statement_no_flag():
    # "should" mid-sentence, no question mark
    assert needs_reply("I think everyone should watch this video.", has_channel_reply=False) is False


def test_can_in_statement_no_flag():
    # "can" mid-sentence in a compliment
    assert needs_reply("I can see why people recommend you.", has_channel_reply=False) is False


def test_does_in_statement_no_flag():
    assert needs_reply("It does seem like quality work.", has_channel_reply=False) is False


def test_is_in_statement_no_flag():
    assert needs_reply("This is really helpful content.", has_channel_reply=False) is False


def test_who_in_statement_no_flag():
    # "who" but not starting the first sentence
    assert needs_reply("I know who to call now. Thanks!", has_channel_reply=False) is False


def test_plain_compliment_no_flag():
    assert needs_reply("Great video, very helpful!", has_channel_reply=False) is False


def test_plain_statement_no_flag():
    assert needs_reply("Thanks for sharing this information.", has_channel_reply=False) is False


def test_pure_compliment_with_what_no_flag():
    assert needs_reply("What a thorough explanation!", has_channel_reply=False) is False


# ---------------------------------------------------------------------------
# Interrogative first sentence but NO '?' → no flag (Rule 3 requires both)
# ---------------------------------------------------------------------------

def test_interrogative_word_no_question_mark_no_flag():
    # Starts with "Is" but ends with period — stated as a fact/observation
    assert needs_reply("Is there a warranty on this", has_channel_reply=False) is False


def test_how_no_question_mark_no_flag():
    # "How long" as a statement observation
    assert needs_reply("How long the installation takes depends on the roof size", has_channel_reply=False) is False


def test_can_no_question_mark_no_flag():
    # "Can" at start but no '?' — borderline but matches the rule
    assert needs_reply("Can see this working great", has_channel_reply=False) is False


# ---------------------------------------------------------------------------
# Edge: '?' mid-sentence only (not at end, interrogative NOT at start)
# ---------------------------------------------------------------------------

def test_question_mark_mid_sentence_no_end_no_leading_interrogative():
    # '?' in middle, statement ends with period, first word is not interrogative
    assert needs_reply("I asked? Then I got the answer.", has_channel_reply=False) is False


# ---------------------------------------------------------------------------
# Empty / degenerate inputs
# ---------------------------------------------------------------------------

def test_empty_string():
    assert needs_reply("", has_channel_reply=False) is False


def test_none_like_empty():
    assert needs_reply("", has_channel_reply=False) is False


def test_just_punctuation():
    assert needs_reply("!!!", has_channel_reply=False) is False


def test_just_question_mark():
    # A bare '?' ends with '?' — technically a question
    assert needs_reply("?", has_channel_reply=False) is True
