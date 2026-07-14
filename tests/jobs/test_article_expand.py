"""Behavioral validation for the article word-floor expansion pass (R1).

Regression guard for the defect these tests were written against: generation planned
1800-2500 words, Gemini returned 350-450, nothing re-asked, and no check noticed — so
short articles published to WordPress while scoring green.
"""
import json

from core.seo import RM_MIN_WORDS, _word_count
from jobs.article_job import _generate_article_json


def _article(words: int, title: str = "T") -> str:
    return json.dumps({
        "title": title,
        "slug": "s",
        "content": f"<h2>{title}</h2><p>{'word ' * words}</p>",
        "faq": [{"q": "q", "a": "a"}],
    })


class _ScriptedLLM:
    """Returns each scripted reply in turn; records the prompts it was given."""

    def __init__(self, *replies):
        self._replies = list(replies)
        self.prompts = []

    def chat(self, prompt, want_json=False, **kw):
        self.prompts.append(prompt)
        return self._replies.pop(0) if self._replies else self._replies_exhausted()

    @staticmethod
    def _replies_exhausted():
        raise AssertionError("LLM called more times than the test scripted")


def test_short_draft_is_expanded_to_the_floor():
    llm = _ScriptedLLM(_article(400), _article(700))
    out = _generate_article_json(llm, "base", "roof repair miami", 1800)
    assert _word_count(out["content"]) >= RM_MIN_WORDS
    assert len(llm.prompts) == 2  # initial + one expansion


def test_expansion_prompt_carries_the_draft_and_targets():
    llm = _ScriptedLLM(_article(400), _article(700))
    _generate_article_json(llm, "base", "roof repair miami", 1800)
    expand = llm.prompts[1]
    assert "EXPAND THIS DRAFT" in expand
    assert "1800" in expand           # the plan's target
    assert str(RM_MIN_WORDS) in expand  # the floor it must clear
    assert "PREVIOUS DRAFT" in expand


def test_long_enough_draft_is_not_expanded():
    llm = _ScriptedLLM(_article(700))
    out = _generate_article_json(llm, "base", "roof repair miami", 1800)
    assert _word_count(out["content"]) >= RM_MIN_WORDS
    assert len(llm.prompts) == 1  # no expansion round


def test_no_progress_keeps_the_longer_draft_rather_than_regressing():
    # Expansion comes back SHORTER — must not overwrite the better draft.
    llm = _ScriptedLLM(_article(400, "keep"), _article(100, "worse"))
    out = _generate_article_json(llm, "base", "roof repair miami", 1800)
    assert out["title"] == "keep"
    assert _word_count(out["content"]) == 401


def test_expansion_is_bounded_when_model_never_reaches_the_floor():
    # Grows a little each round but never clears the floor: 2 rounds max, then give up
    # with the best draft rather than looping forever.
    llm = _ScriptedLLM(_article(300), _article(400), _article(500))
    out = _generate_article_json(llm, "base", "roof repair miami", 1800)
    assert len(llm.prompts) == 3  # initial + 2 bounded expansions
    assert _word_count(out["content"]) == 501  # best draft kept despite being short


def test_unparseable_json_still_raises():
    import pytest
    llm = _ScriptedLLM("not json", "not json", "not json")
    with pytest.raises(RuntimeError, match="unparseable"):
        _generate_article_json(llm, "base", "roof repair miami", 1800)
