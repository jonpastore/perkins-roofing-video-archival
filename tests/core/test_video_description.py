"""Tests for the description prompt rendering — the parts that decide what the model is asked."""
from __future__ import annotations

import re
from dataclasses import dataclass

import pytest

from core.video_description import (
    DEFAULT_PROMPT,
    MAX_HASHTAGS,
    MAX_TRANSCRIPT_CHARS,
    DescriptionError,
    clean,
    enforce,
    fmt_duration,
    render_prompt,
    transcript_text,
)


@dataclass
class Seg:
    text: str
    start: float


def test_transcript_is_joined_in_time_order_not_query_order():
    """Segments come back unordered often enough that relying on the query is a latent bug."""
    segs = [Seg("third", 30.0), Seg("first", 1.0), Seg("second", 12.5)]
    assert transcript_text(segs) == "first second third"


def test_blank_segments_are_dropped():
    assert transcript_text([Seg("  ", 1.0), Seg("real", 2.0), Seg("", 3.0)]) == "real"


def test_no_transcript_is_an_operator_error_not_a_crash():
    """The reviewer can act on 'wait for ingestion'; they cannot act on a 500."""
    with pytest.raises(DescriptionError, match="no transcript"):
        render_prompt("x {transcript}", title="T", duration=60, transcript="   ")


def test_placeholders_are_substituted():
    r = render_prompt("Title={title} Dur={duration} T={transcript}",
                      title="Roof Repair", duration=3661, transcript="hello there")
    assert r.prompt == "Title=Roof Repair Dur=1h 01m T=hello there"
    assert r.transcript_chars == len("hello there")
    assert r.truncated is False


def test_literal_braces_in_an_operator_prompt_do_not_explode():
    """THE reason str.format is not used here.

    An operator will paste a JSON example or a code snippet into the prompt box sooner or later.
    `"{...}".format()` raises KeyError on every unknown brace, which would turn a formatting quirk
    into a 500 on a button press. Unknown braces must pass through untouched.
    """
    tpl = 'Return {"headline": "...", "body": "..."} as JSON.\n{transcript}'
    r = render_prompt(tpl, title="T", duration=10, transcript="abc")
    assert '{"headline": "...", "body": "..."}' in r.prompt
    assert r.prompt.endswith("abc")


def test_a_prompt_that_forgets_the_transcript_placeholder_still_gets_the_transcript():
    """Otherwise every video gets the same generic description and nothing looks broken."""
    r = render_prompt("Write a description.", title="T", duration=10, transcript="roof facts")
    assert "roof facts" in r.prompt


def test_empty_template_falls_back_to_the_default():
    r = render_prompt("   ", title="T", duration=10, transcript="abc")
    assert DEFAULT_PROMPT.split("\n")[0] in r.prompt


def test_long_transcripts_are_truncated_and_say_so():
    long = "x" * (MAX_TRANSCRIPT_CHARS + 500)
    r = render_prompt("{transcript}", title="T", duration=10, transcript=long)
    assert r.transcript_chars == MAX_TRANSCRIPT_CHARS
    assert r.truncated is True
    assert len(r.prompt) == MAX_TRANSCRIPT_CHARS


@pytest.mark.parametrize("secs,want", [
    (3661, "1h 01m"), (252, "4m 12s"), (0, "unknown"), (None, "unknown"), ("nope", "unknown"),
])
def test_duration_formatting(secs, want):
    assert fmt_duration(secs) == want


@pytest.mark.parametrize("raw,want", [
    ("```\nhello\n```", "hello"),
    ("```markdown\nhello\n```", "hello"),
    ("Description: hello", "hello"),
    ("  hello  ", "hello"),
])
def test_model_wrappers_are_stripped(raw, want):
    assert clean(raw) == want


def test_empty_model_output_is_an_error_not_an_empty_description():
    """Storing "" would look like a generated description and read as done."""
    with pytest.raises(DescriptionError):
        clean("   ")


# ---------------------------------------------------------------------------
# enforce() — the post-generation pass (Jon, 2026-08-11: hashtags are a STRICT 5)
# ---------------------------------------------------------------------------

def test_extra_hashtags_are_trimmed_to_the_limit():
    """The model returns eight when asked for "approximately 5". The ceiling is enforced, not asked."""
    out = enforce("Great roof.\n\n#a #b #c #d #e #f #g #h")
    assert len(re.findall(r"#\w+", out.text)) == MAX_HASHTAGS
    # Earliest kept — the model orders them most-relevant first.
    assert "#a" in out.text and "#e" in out.text
    assert "#f" not in out.text and "#h" not in out.text
    assert any("trimmed 3" in f for f in out.fixes)


def test_exactly_five_hashtags_is_left_alone():
    text = "Body copy here.\n\n#one #two #three #four #five"
    out = enforce(text)
    assert out.text == text
    assert out.fixes == () and out.problems == ()


def test_structural_labels_are_stripped():
    """Section 17 of the prompt forbids "Hook:"/"Hashtags:" — that scaffolding is not a caption."""
    out = enforce("Hook: Your roof is failing\n\nBody.\n\nHashtags: #a #b")
    assert "Hook:" not in out.text and "Hashtags:" not in out.text
    assert out.text.startswith("Your roof is failing")
    assert any("structural label" in f for f in out.fixes)


def test_assistant_chatter_is_reported_not_silently_rewritten():
    """Guessing what the model meant on a caption bound for Instagram is worse than flagging it."""
    out = enforce("Here is your caption. Roofs matter.\n\n#a #b #c")
    assert out.problems, "chatter must be surfaced to the reviewer"
    assert "Roofs matter." in out.text  # not deleted — a human decides


def test_no_hashtags_at_all_is_a_reported_problem():
    out = enforce("A caption with no tags on it.")
    assert any("no hashtags" in p for p in out.problems)
    assert out.fixes == ()


def test_a_word_containing_a_hash_is_not_a_hashtag():
    """'C#' and a URL fragment must not count against the 5."""
    out = enforce("Written in C# and see example.com/page#section\n\n#a #b #c #d #e")
    assert len(re.findall(r"(?<![\w#])#\w+", out.text)) == 5
    assert out.fixes == ()


def test_scaffolding_only_output_raises_rather_than_storing_it():
    with pytest.raises(DescriptionError):
        enforce("Hashtags:")
