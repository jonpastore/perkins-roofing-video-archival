"""Behavioral validation for the 3-lens adversarial critique loop (R1)."""
import pytest

from core.article_critique import (
    CRITICS,
    blocking,
    critique_prompt,
    parse_findings,
    revise_prompt,
)

_ARTICLE = {
    "title": "Roof Ventilation: A Guide",
    "meta": "meta text",
    "content_md": "<h2>What is it?</h2><p>Body text here.</p>",
    "focus_keyword": "roof ventilation",
    "faq_json": [{"q": "q", "a": "a"}],
}


def test_the_three_lenses_are_actually_different():
    # The whole point of 3 agents: redundant critics find redundant problems.
    prompts = {k: critique_prompt(k, _ARTICLE) for k in CRITICS}
    assert set(prompts) == {"seo", "grounding", "reader"}
    assert "density" in prompts["seo"].lower()
    assert "density" not in prompts["reader"].lower()
    assert "traceable" in prompts["grounding"].lower()
    assert "homeowner" in prompts["reader"].lower()
    # each lens is told to ignore the others' territory, so they don't converge
    assert "another reviewer" in prompts["reader"].lower()


def test_unknown_lens_is_rejected():
    with pytest.raises(ValueError, match="unknown critic lens"):
        critique_prompt("vibes", _ARTICLE)


def test_grounding_critic_gets_the_transcript_and_others_do_not():
    t = "TRANSCRIPT-MARKER tim says flashing costs $400"
    assert "TRANSCRIPT-MARKER" in critique_prompt("grounding", _ARTICLE, t)
    # feeding the transcript to the SEO/reader critics would just burn tokens
    assert "TRANSCRIPT-MARKER" not in critique_prompt("seo", _ARTICLE, t)
    assert "TRANSCRIPT-MARKER" not in critique_prompt("reader", _ARTICLE, t)


def test_article_body_reaches_every_critic():
    for lens in CRITICS:
        assert "Body text here." in critique_prompt(lens, _ARTICLE)


# ── findings parsing (fail-closed on shape, not on content) ───────────────────

def test_parse_findings_keeps_valid_and_drops_malformed():
    parsed = {"findings": [
        {"severity": "blocker", "issue": "invented a price", "fix": "cut it"},
        {"severity": "nonsense", "issue": "x", "fix": "y"},   # bad severity
        {"severity": "major", "issue": "", "fix": "y"},        # empty issue
        "not-a-dict",
        {"severity": "minor", "issue": "wordy", "fix": "trim"},
    ]}
    out = parse_findings(parsed)
    assert [f["severity"] for f in out] == ["blocker", "minor"]


def test_parse_findings_survives_junk():
    assert parse_findings(None) == []
    assert parse_findings("not json") == []
    assert parse_findings({}) == []
    assert parse_findings({"findings": None}) == []


# ── the stop condition ────────────────────────────────────────────────────────

def test_only_blocker_and_major_force_another_round():
    # minor-only must NOT spin the loop — a critic always finds *something*.
    findings = [{"severity": "minor", "issue": "a", "fix": "b"},
                {"severity": "minor", "issue": "c", "fix": "d"}]
    assert blocking(findings) == []

    findings.append({"severity": "major", "issue": "e", "fix": "f"})
    assert len(blocking(findings)) == 1
    findings.append({"severity": "blocker", "issue": "g", "fix": "h"})
    assert len(blocking(findings)) == 2


# ── the reviser prompt ────────────────────────────────────────────────────────

def test_revise_prompt_carries_findings_word_goal_and_no_shorten_rule():
    findings = [{"severity": "blocker", "issue": "invented a cost", "fix": "hedge it"}]
    p = revise_prompt(_ARTICLE, findings, 1620)
    assert "invented a cost" in p
    assert "hedge it" in p
    assert "1620" in p                       # the reviser must know the floor
    assert "Do NOT shorten" in p
    assert "?t= timestamp" in p              # citations must survive revision
    assert "Body text here." in p            # the article itself


def test_revise_prompt_orders_blockers_before_majors():
    findings = [{"severity": "major", "issue": "MAJOR-ONE", "fix": "x"},
                {"severity": "blocker", "issue": "BLOCK-ONE", "fix": "y"}]
    p = revise_prompt(_ARTICLE, findings, 1620)
    assert p.index("BLOCK-ONE") < p.index("MAJOR-ONE")


def test_revise_prompt_forbids_inventing_facts_to_satisfy_a_finding():
    p = revise_prompt(_ARTICLE, [{"severity": "major", "issue": "i", "fix": "f"}], 1620)
    assert "Do not invent facts" in p


def test_run_critics_adds_a_deterministic_blocker_for_unsourced_terms():
    # The LLM lenses judge a model with a model and say "clean" a lot. The string check is the
    # one finding that cannot be talked out of.
    from jobs.article_job import _run_critics

    class _LLM:
        def chat(self, prompt, want_json=False, **kw):
            return '{"findings": []}'          # every lens passes it

    fields = {"content_md": "<p>Use the SuperFlash 9000 membrane on the deck.</p>",
              "title": "T", "meta": "m"}
    out = _run_critics(fields, "wall flashings", "you cut the stucco and put the wall flashing "
                       "into the actual concrete block", llm=_LLM())
    gc = [f for f in out if f.get("lens") == "grounding-check"]
    assert gc, "an invented product name must be flagged even when every LLM lens passes"
    assert gc[0]["severity"] == "blocker"
    assert "SuperFlash 9000" in gc[0]["issue"]


def test_run_critics_grounding_check_is_silent_with_no_transcript():
    # No evidence base -> no claims of fabrication (it would flag an entire article).
    from jobs.article_job import _run_critics

    class _LLM:
        def chat(self, prompt, want_json=False, **kw):
            return '{"findings": []}'

    out = _run_critics({"content_md": "<p>Use the SuperFlash 9000.</p>"}, "kw", "", llm=_LLM())
    assert [f for f in out if f.get("lens") == "grounding-check"] == []
