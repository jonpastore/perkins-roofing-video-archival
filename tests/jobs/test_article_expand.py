"""Behavioral validation for the article word-target expansion pass (R1).

Regression guard for the defect these tests were written against: generation planned
1800-2500 words, Gemini returned 350-450, nothing re-asked, and no check noticed — so
short articles published to WordPress while scoring green.

The goal is the plan's target (target_words * 0.9, matching the lower bound
core.article_prompt already asks for), floored at Rank Math's RM_MIN_WORDS — NOT the floor
alone, which would score green while shipping a third of the commissioned article.
"""
import json

from core.seo import RM_MIN_WORDS, _word_count
from jobs.article_job import _EXPAND_ROUNDS, _generate_article_json, _word_goal


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


# ── the goal itself ───────────────────────────────────────────────────────────

def test_goal_tracks_the_plan_target_not_the_rank_math_floor():
    # The whole point of #334: 600 is green but is not the article that was commissioned.
    assert _word_goal(1800) == 1620   # cluster
    assert _word_goal(2500) == 2250   # pillar


def test_goal_never_drops_below_the_rank_math_floor():
    # A small target must not authorise an article that scores red.
    assert _word_goal(300) == RM_MIN_WORDS
    assert _word_goal(0) == RM_MIN_WORDS


# ── expansion behaviour ───────────────────────────────────────────────────────

def test_draft_is_expanded_until_it_reaches_the_target_goal():
    # 400 -> 900 -> 1700 clears the 1620 goal; stops as soon as it does.
    llm = _ScriptedLLM(_article(400), _article(900), _article(1700))
    out = _generate_article_json(llm, "base", "roof repair miami", 1800)
    assert _word_count(out["content"]) >= _word_goal(1800)
    assert len(llm.prompts) == 3  # initial + two expansions


def test_draft_clearing_only_the_rank_math_floor_is_still_expanded():
    # Regression guard for the exact bug: 700 words is green but far short of 1800.
    llm = _ScriptedLLM(_article(700), _article(1700))
    out = _generate_article_json(llm, "base", "roof repair miami", 1800)
    assert len(llm.prompts) == 2, "a 700-word draft against an 1800-word plan must be expanded"
    assert _word_count(out["content"]) >= _word_goal(1800)


def test_draft_already_at_target_is_not_expanded():
    llm = _ScriptedLLM(_article(1700))
    out = _generate_article_json(llm, "base", "roof repair miami", 1800)
    assert _word_count(out["content"]) >= _word_goal(1800)
    assert len(llm.prompts) == 1  # no expansion round


def test_expansion_prompt_carries_the_draft_target_and_goal():
    llm = _ScriptedLLM(_article(400), _article(1700))
    _generate_article_json(llm, "base", "roof repair miami", 1800)
    expand = llm.prompts[1]
    assert "EXPAND THIS DRAFT" in expand
    assert "1800" in expand                    # the plan's target
    assert str(_word_goal(1800)) in expand     # the bound it must clear
    assert "PREVIOUS DRAFT" in expand


def test_no_progress_keeps_the_longer_draft_rather_than_regressing():
    # Expansion comes back SHORTER — must not overwrite the better draft.
    llm = _ScriptedLLM(_article(400, "keep"), _article(100, "worse"))
    out = _generate_article_json(llm, "base", "roof repair miami", 1800)
    assert out["title"] == "keep"
    assert _word_count(out["content"]) == 401


def test_expansion_is_bounded_when_model_never_reaches_the_goal():
    # Grows a little each round but never clears the goal: bounded, then give up with the
    # best draft rather than looping (and billing) forever.
    llm = _ScriptedLLM(*[_article(300 + 100 * i) for i in range(_EXPAND_ROUNDS + 1)])
    out = _generate_article_json(llm, "base", "roof repair miami", 1800)
    assert len(llm.prompts) == _EXPAND_ROUNDS + 1  # initial + bounded expansions
    assert _word_count(out["content"]) == 300 + 100 * _EXPAND_ROUNDS + 1  # best draft kept


def test_unparseable_json_still_raises():
    import pytest
    llm = _ScriptedLLM("not json", "not json", "not json")
    with pytest.raises(RuntimeError, match="unparseable"):
        _generate_article_json(llm, "base", "roof repair miami", 1800)


# ── the refine seam (regression guards for the 2208 -> 949 defect) ────────────

def test_refine_prompt_is_not_truncated():
    """refine used to send content_md[:4000] — the editor saw only the first ~600 words of a
    2000+ word article, rewrote that fragment, and returned it as the whole piece."""
    from jobs.article_job import refine_article_content

    long_body = "<h2>H</h2><p>" + ("word " * 3000) + "</p>"   # ~15k chars, way past 4000
    llm = _ScriptedLLM(json.dumps({
        "title": "T", "slug": "s", "metaDescription": "m",
        "content": long_body, "faq": [{"q": "q", "a": "a"}],
    }))
    refine_article_content({"title": "T", "slug": "s", "meta": "m",
                            "content_md": long_body, "faq_json": []}, "kw", llm=llm)
    sent = llm.prompts[0]
    tail_marker = long_body[-200:].strip()[-40:]
    assert tail_marker in sent, "refine prompt dropped the tail of the article"


def test_refine_that_shortens_the_article_is_rejected():
    from jobs.article_job import _refine_without_regressing_length

    long_body = "<h2>H</h2><p>" + ("word " * 2000) + "</p>"
    llm = _ScriptedLLM(json.dumps({
        "title": "shrunk", "slug": "s", "metaDescription": "m",
        "content": "<h2>H</h2><p>" + ("word " * 200) + "</p>",   # editor lost 90%
        "faq": [{"q": "q", "a": "a"}],
    }))
    before = {"title": "keep", "slug": "s", "meta": "m",
              "content_md": long_body, "faq_json": []}
    out = _refine_without_regressing_length(before, "kw", llm=llm)
    assert out["title"] == "keep", "a refine that drops content must not be accepted"
    assert _word_count(out["content_md"]) == _word_count(long_body)


def test_refine_that_preserves_length_is_accepted():
    from jobs.article_job import _refine_without_regressing_length

    body = "<h2>H</h2><p>" + ("word " * 800) + "</p>"
    better = "<h2>Q?</h2><p>" + ("word " * 900) + "</p>"
    llm = _ScriptedLLM(json.dumps({
        "title": "improved", "slug": "s", "metaDescription": "m",
        "content": better, "faq": [{"q": "q", "a": "a"}],
    }))
    out = _refine_without_regressing_length(
        {"title": "old", "slug": "s", "meta": "m", "content_md": body, "faq_json": []},
        "kw", llm=llm)
    assert out["title"] == "improved"
