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


# ── deterministic guarantees (rm_title_number, rm_kw_in_img_alt, title punctuation) ──

def test_title_keyword_match_tolerates_punctuation():
    """The bug that produced 'Roof Estimate Vs Inspection: Roof Estimate vs. Inspection: Key':
    'roof estimate vs inspection' is not a literal substring of 'Roof Estimate vs. Inspection'."""
    from jobs.article_job import _ensure_title

    out = _ensure_title("Roof Estimate vs. Inspection: Key Differences", "roof estimate vs inspection")
    assert not out.lower().startswith("roof estimate vs inspection: roof estimate")
    assert out.lower().count("estimate") == 1, f"keyword duplicated into title: {out!r}"


def test_title_still_gets_keyword_when_genuinely_absent():
    from jobs.article_job import _ensure_title
    out = _ensure_title("A Guide To Attic Airflow For Homeowners", "roof ventilation")
    assert "roof ventilation" in out.lower()


def test_ensure_title_number_adds_a_digit():
    from jobs.article_job import _ensure_title_number
    out = _ensure_title_number("Wall Flashings: Your Essential Guide", "wall flashings")
    assert any(ch.isdigit() for ch in out)
    assert 30 <= len(out) <= 65


def test_ensure_title_number_leaves_titles_that_already_have_one():
    from jobs.article_job import _ensure_title_number
    t = "7 Essential Wall Flashing Tips for Florida Roofs"
    assert _ensure_title_number(t, "wall flashings") == t


def test_ensure_title_number_never_drops_the_keyword():
    from jobs.article_job import _ensure_title_number
    t = "A Really Quite Long Title About Wall Flashings Indeed Yes"
    out = _ensure_title_number(t, "wall flashings")
    assert "wall flashings" in out.lower(), "trimming for the year cut the keyword out"


def test_ensure_title_cuts_at_a_clause_boundary_not_mid_clause():
    # Regression: trimming at the last space <=65 produced the dangling fragment
    # "7 Essential Fire and Water Barrier Tips: Protect Your Florida" (observed in prod).
    # Dropping the whole trailing clause keeps a title that still reads like English.
    from jobs.article_job import _ensure_title
    out = _ensure_title(
        "7 Essential Fire and Water Barrier Tips: Protect Your Florida Home from Disaster",
        "fire and water barrier")
    assert out == "7 Essential Fire and Water Barrier Tips"
    assert len(out) <= 65


def test_ensure_title_leaves_a_long_title_alone_when_no_clause_boundary_helps():
    # No separator to cut at -> leave it long rather than butcher it. Failing one length
    # check beats shipping a fragment.
    from jobs.article_job import _ensure_title
    t = "Wall Flashings Are The Single Most Important Detail On Any Florida Roof Today"
    assert _ensure_title(t, "wall flashings") == t


def test_ensure_title_never_cuts_the_keyword_out_when_shortening():
    from jobs.article_job import _ensure_title
    out = _ensure_title(
        "A Homeowner's Complete Reference: Wall Flashings And Why They Fail So Often",
        "wall flashings")
    assert "wall flashings" in out.lower()


def test_ensure_title_number_never_truncates_a_title_to_fit_the_year():
    # Regression: trimming at a word boundary to make room for " (2026)" cut the final noun and
    # shipped "...Preventing Water (2026)" / "...to a Cooler (2026)" to the live site. Length and
    # keyword were both still satisfied — only the meaning was destroyed. Leave it alone instead.
    from jobs.article_job import _ensure_title_number
    for title, kw in [
        ("Wall Flashings: Your Essential Guide to Preventing Water Damage", "wall flashings"),
        ("Roof Ventilation: Your Essential Guide to a Cooler, Healthier Home", "roof ventilation"),
    ]:
        out = _ensure_title_number(title, kw)
        assert out == title, f"title was mangled to fit the year: {out!r}"


def test_ensure_article_image_uses_the_source_video_thumbnail():
    from jobs.article_job import _ensure_article_image
    body = "<p>intro</p>\nhttps://www.youtube.com/watch?v=BnsaVtCb0GU\n<p>rest</p>"
    out = _ensure_article_image(body, "wall flashings")
    assert "img.youtube.com/vi/BnsaVtCb0GU/hqdefault.jpg" in out
    assert 'alt="Wall Flashings — Perkins Roofing"' in out
    assert body in out, "original body must be preserved"


def test_ensure_article_image_is_not_fabricated_without_a_video():
    # No video to take a thumbnail from -> no image. Never invent one (the old repair script
    # injected the same generic perkins-roofing-seo-guide.jpg into every article).
    from jobs.article_job import _ensure_article_image
    body = "<p>no video here</p>"
    assert _ensure_article_image(body, "wall flashings") == body


def test_ensure_article_image_does_not_add_a_second_image():
    from jobs.article_job import _ensure_article_image
    body = '<img src="real.jpg" alt="a real photo">\nhttps://youtu.be/BnsaVtCb0GU'
    out = _ensure_article_image(body, "wall flashings")
    assert out.count("<img") == 1, "existing image must not be duplicated"


def test_article_image_then_alt_caption_satisfies_rank_math():
    # The two helpers compose: supply the real image, then caption it with the keyword.
    from core.seo import rank_math_checks
    from jobs.article_job import _ensure_article_image, _ensure_img_alt_keyword
    body = "<p>intro</p>\nhttps://youtu.be/BnsaVtCb0GU\n<p>rest</p>"
    out = _ensure_img_alt_keyword(_ensure_article_image(body, "wall flashings"), "wall flashings")
    checks = {c["key"]: c["pass"] for c in rank_math_checks(
        "Wall Flashings Guide 2026", "m", "wall-flashings", out, "wall flashings")}
    assert checks["rm_kw_in_img_alt"] is True


def test_img_alt_gets_the_keyword_when_an_image_exists():
    from jobs.article_job import _ensure_img_alt_keyword
    html = '<p>x</p><img src="a.jpg" alt="a roof">'
    out = _ensure_img_alt_keyword(html, "roof ventilation")
    assert 'alt="Roof Ventilation"' in out


def test_img_alt_is_not_fabricated_when_there_is_no_image():
    # Inventing an <img> would render as a broken image on Tim's site.
    from jobs.article_job import _ensure_img_alt_keyword
    html = "<h2>H</h2><p>no images here</p>"
    assert _ensure_img_alt_keyword(html, "roof ventilation") == html


def test_img_alt_left_alone_when_keyword_already_present():
    from jobs.article_job import _ensure_img_alt_keyword
    html = '<img src="a.jpg" alt="Roof Ventilation baffles">'
    assert _ensure_img_alt_keyword(html, "roof ventilation") == html


# ── the critique loop driver (3 lenses x 3 rounds) ───────────────────────────

def _critique(*findings):
    return json.dumps({"findings": list(findings)})


def _finding(sev="major", issue="an issue"):
    return {"severity": sev, "issue": issue, "fix": "a fix"}


_CLEAN = _critique()


def test_loop_stops_early_when_all_critics_are_clean():
    from jobs.article_job import critique_and_revise
    # 3 clean critics -> no revision, no further rounds
    llm = _ScriptedLLM(_CLEAN, _CLEAN, _CLEAN)
    fields = {"title": "T", "slug": "s", "meta": "m",
              "content_md": "<h2>H</h2><p>" + ("word " * 900) + "</p>", "faq_json": []}
    out = critique_and_revise(fields, "kw", llm=llm, target_words=1000)
    assert out is fields
    assert len(llm.prompts) == 3, "clean critics must not trigger a revision"


def test_minor_only_findings_do_not_trigger_a_revision():
    from jobs.article_job import critique_and_revise
    llm = _ScriptedLLM(_critique(_finding("minor")), _critique(_finding("minor")), _CLEAN)
    fields = {"title": "T", "slug": "s", "meta": "m",
              "content_md": "<h2>H</h2><p>" + ("word " * 900) + "</p>", "faq_json": []}
    critique_and_revise(fields, "kw", llm=llm, target_words=1000)
    assert len(llm.prompts) == 3, "minor findings must not spin the loop"


def test_blocking_finding_triggers_a_revision_round():
    from jobs.article_job import critique_and_revise
    body = "<h2>H</h2><p>" + ("word " * 900) + "</p>"
    longer = json.dumps({"title": "revised", "slug": "s", "metaDescription": "m",
                         "content": "<h2>H</h2><p>" + ("word " * 1000) + "</p>",
                         "faq": [{"q": "q", "a": "a"}]})
    llm = _ScriptedLLM(_critique(_finding("blocker")), _CLEAN, _CLEAN,  # round 1 critics
                       longer,                                          # revise
                       _CLEAN, _CLEAN, _CLEAN)                          # round 2 critics: clean
    out = critique_and_revise({"title": "old", "slug": "s", "meta": "m",
                               "content_md": body, "faq_json": []},
                              "kw", llm=llm, target_words=1000)
    assert out["title"] == "revised"
    assert len(llm.prompts) == 7  # 3 critics + 1 revise + 3 critics


def test_loop_is_bounded_at_three_rounds():
    from jobs.article_job import CRITIQUE_ROUNDS, critique_and_revise
    assert CRITIQUE_ROUNDS == 3
    body = "<h2>H</h2><p>" + ("word " * 900) + "</p>"
    def grow(n):
        return json.dumps({"title": f"r{n}", "slug": "s", "metaDescription": "m",
                           "content": "<h2>H</h2><p>" + ("word " * (900 + n * 50)) + "</p>",
                           "faq": [{"q": "q", "a": "a"}]})
    # a critic that ALWAYS finds a blocker must still terminate
    replies = []
    for n in range(1, CRITIQUE_ROUNDS + 1):
        replies += [_critique(_finding("blocker")), _CLEAN, _CLEAN, grow(n)]
    llm = _ScriptedLLM(*replies)
    critique_and_revise({"title": "old", "slug": "s", "meta": "m",
                         "content_md": body, "faq_json": []},
                        "kw", llm=llm, target_words=1000)
    assert len(llm.prompts) == CRITIQUE_ROUNDS * 4  # (3 critics + 1 revise) x 3


def test_revision_that_loses_content_is_rejected():
    from jobs.article_job import critique_and_revise
    body = "<h2>H</h2><p>" + ("word " * 900) + "</p>"
    shorter = json.dumps({"title": "shrunk", "slug": "s", "metaDescription": "m",
                          "content": "<h2>H</h2><p>" + ("word " * 100) + "</p>",
                          "faq": [{"q": "q", "a": "a"}]})
    llm = _ScriptedLLM(_critique(_finding("blocker")), _CLEAN, _CLEAN, shorter,
                       _CLEAN, _CLEAN, _CLEAN)
    out = critique_and_revise({"title": "keep", "slug": "s", "meta": "m",
                               "content_md": body, "faq_json": []},
                              "kw", llm=llm, target_words=1000)
    assert out["title"] == "keep", "a revision that drops 90% must not be accepted"


def test_one_broken_critic_does_not_kill_the_review():
    from jobs.article_job import critique_and_revise
    body = "<h2>H</h2><p>" + ("word " * 900) + "</p>"
    # first critic returns junk; the other two still run
    llm = _ScriptedLLM("not json at all", _CLEAN, _CLEAN)
    out = critique_and_revise({"title": "T", "slug": "s", "meta": "m",
                               "content_md": body, "faq_json": []},
                              "kw", llm=llm, target_words=1000)
    assert out["title"] == "T"
    assert len(llm.prompts) == 3


def test_expand_prompt_forbids_inventing_to_reach_length():
    # The old prompt said "Rewrite it LONGER ... add specific costs" with no requirement that
    # any of it came from Tim. That is an instruction to fabricate: 45,945 published words rested
    # on 4,564 words of source. Expansion must ask for more of Tim, and allow stopping.
    from jobs.article_job import _expand_prompt
    p = _expand_prompt("BASE", "draft text", 600, 1800, 1620)
    low = p.lower()
    assert "do not invent" in low
    assert "return the draft as-is" in low
    assert "source transcripts" in low
    assert "stopping short is correct" in low
    # must not order the model to simply write more
    assert "rewrite it longer" not in low


def test_topic_windows_end_where_the_next_topic_starts():
    from jobs.article_job import _topic_windows

    class _N:
        def __init__(self, s, label):
            self.start, self.label = s, label

    class _Q:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *a, **k):
            return self

        def order_by(self, *a, **k):
            return self

        def all(self):
            return self._rows

    class _DB:
        def query(self, *a, **k):
            return _Q([_N(0.0, "intro"), _N(30.0, "flashings"), _N(90.0, "outro")])

    assert _topic_windows("v1", _DB()) == [
        (0.0, 30.0, "intro"), (30.0, 90.0, "flashings"), (90.0, None, "outro"),
    ]


def test_video_grounding_block_states_the_hard_rules():
    from jobs.article_job import _append_video_grounding
    out = _append_video_grounding("PROMPT", [{
        "video_id": "v1", "title": "Wall Flashings 101", "url": "https://youtu.be/v1?t=10",
        "label": "poly flash details", "transcript": "you cut the poly flash six inches up",
    }])
    assert "you cut the poly flash six inches up" in out
    assert "https://youtu.be/v1?t=10" in out
    assert "poly flash details" in out
    assert "If Tim does not" in out and "DO NOT write it" in out
    assert "CUT THE SECTION" in out


def test_enforce_grounding_reports_but_never_edits_the_article():
    """Regression: this fed each flagged term to an LLM reviser as a blocker.

    On a real article it flagged 'Costs', 'Risk', 'Value', 'Durability' and 10 more — Title-Case
    headings make every heading word a candidate and "cost" vs "Costs" fails a plural-naive
    test — so the reviser was ordered to strip legitimate words, twice per article. Token
    presence is not claim support, so its precision cannot be tuned into a gate.
    """
    from jobs.article_job import _enforce_grounding

    class _LLM:
        def chat(self, *a, **k):
            raise AssertionError("the grounding report must never trigger a revision")

    body = "<p>Fit the SuperFlash 9000 to the deck.</p>"
    out = _enforce_grounding({"content_md": body, "title": "T"}, "wall flashings",
                             "you cut the stucco and set the wall flashing", llm=_LLM())
    assert out["content_md"] == body, "the article must be returned unmodified"
    assert "SuperFlash 9000" in out["unsourced_terms"], "it must still be reported"


def test_article_updated_at_stamps_on_every_write_path():
    """Provenance must not depend on each caller remembering.

    articles had only generated_at, set once at insert, so all 31 rows read "2026-07-09" no
    matter how often they were rewritten — there was no way to ask which pipeline produced an
    article. Hand-stamping it in the regen job covered 1 of the 7 modules that write
    content_md, and clobbered the creation date the column is named for. onupdate is
    SQLAlchemy's, so it fires for any UPDATE from any caller.
    """
    from app.models import Article

    updated = Article.__table__.columns["updated_at"]
    assert updated.onupdate is not None, "updated_at must stamp itself on every UPDATE"
    assert updated.default is not None, "and be set on insert"
    # generated_at means first generation and must NOT re-stamp on update
    assert Article.__table__.columns["generated_at"].onupdate is None


def test_refine_prompt_targets_the_density_band_from_both_sides():
    """Regression: the refine prompt warned only about the ceiling.

    It said "repetition past ~1% density is over-optimisation" with no floor, and the model
    obeyed into 0.16-0.48% against Rank Math's 0.5-1.5% band — 12 of 31 articles failed
    rm_kw_density. Generation (core/article_prompt) had it right; refine ran afterwards and
    pushed density back down. Both ends must be stated.
    """
    from jobs.article_job import refine_article_content

    class _LLM:
        def __init__(self):
            self.prompts = []

        def chat(self, prompt, want_json=False, **kw):
            self.prompts.append(prompt)
            return '{"title":"T","slug":"s","metaDescription":"m","content":"<p>x</p>","faq":[]}'

    llm = _LLM()
    refine_article_content({"title": "T", "slug": "s", "meta": "m",
                            "content_md": "<p>body</p>", "faq_json": []}, "wall flashings", llm=llm)
    p = llm.prompts[0].lower()
    assert "0.5%" in p and "1.5%" in p, "both ends of the band must be stated"
    assert "under-optimised" in p or "under 0.5%" in p, "the FLOOR must be explicit"
    assert "wall flashings" in p
    # A bare count anchors the model regardless of the length it actually writes: given
    # "~18-22 in a 2,000-word article" it wrote 23 into a 1,440-word piece -> 1.60%, over the
    # ceiling. The instruction must bind to the finished length.
    assert "ratio" in p and "finished article" in p
    assert "1,200-word" in p and "2,400-word" in p, "worked both ways, so length stays free"


def test_grounding_audit_escalates_terms_tim_has_never_said():
    """Two tiers, because they mean different things.

    Absent from THIS article's slices is weak (headings, plurals, or the model reaching onto
    something real like 'PB77', which Tim does say elsewhere). Absent from all 801 videos is
    strong: 'Solar Reflectance Index' has 0 hits in 14,592 chunks, so the article invented it.
    The corpus tier ESCALATES; it never replaces the slice check — "Tim said it somewhere" is
    not evidence for this article.
    """
    from jobs import article_job

    article_job._corpus_vocabulary.cache_clear()
    try:
        article_job._corpus_vocabulary.__wrapped__  # sanity: it is cached
        fields = {"content_md": "<p>Use the SuperFlash 9000 and the Polyblast primer.</p>"}
        tim = "you set the polyblast primer against the stucco"
        # vocabulary knows 'polyblast' but has never heard 'superflash'
        article_job._corpus_vocabulary.cache_clear()
        orig = article_job._corpus_vocabulary
        article_job._corpus_vocabulary = lambda _t=1: frozenset(
            {"polyblast", "primer", "stucco", "you", "set", "the", "against"})
        try:
            terms = article_job._audit_grounding(fields, "wall flashings", tim)
        finally:
            article_job._corpus_vocabulary = orig
        assert any("SuperFlash" in t for t in terms)
        never = fields.get("never_said_terms") or []
        assert any("SuperFlash" in t for t in never), "never-said term must escalate"
        assert not any("Polyblast" in t for t in never), "a word Tim says must NOT escalate"
    finally:
        article_job._corpus_vocabulary.cache_clear()


# ── per-post schema scoped to FAQ + Video only (Rank Math owns Org/Article/Breadcrumb) ──────

def test_jsonld_is_faq_and_video_only():
    from jobs.article_job import _build_article_jsonld

    fields = {
        "title": "Wall Flashings Guide",
        "meta": "m",
        "faq_json": [{"q": "q", "a": "a"}],
        "_video_jsonld": [{"@context": "https://schema.org", "@type": "VideoObject", "name": "v"}],
    }
    jsonld = _build_article_jsonld(fields, {"role": "pillar", "pillar_slug": None})
    types = [node["@type"] for node in jsonld]
    assert types == ["FAQPage", "VideoObject"]
    assert "Article" not in types
    assert "BreadcrumbList" not in types
    assert "Organization" not in types
    assert "Person" not in types


def test_jsonld_omits_video_when_ungrounded():
    from jobs.article_job import _build_article_jsonld

    fields = {"title": "T", "meta": "m", "faq_json": [{"q": "q", "a": "a"}]}
    jsonld = _build_article_jsonld(fields, {"role": "pillar", "pillar_slug": None})
    assert [node["@type"] for node in jsonld] == ["FAQPage"]


# ── internal linking: cluster -> pillar + contextual services links ────────────────────────

def test_internal_links_cluster_links_up_to_its_pillar():
    from jobs.article_job import _ensure_internal_links

    ctx = {"role": "cluster", "pillar_slug": "metal-roofing-guide", "pillar_title": "Metal Roofing Guide"}
    out = _ensure_internal_links("<p>some article body</p>", "metal roof cost", ctx)
    assert '<a href="https://perkinsroofing.net/metal-roofing-guide">Metal Roofing Guide</a>' in out
    assert "/blog/" not in out


def test_internal_links_pillar_article_gets_no_pillar_link():
    from jobs.article_job import _ensure_internal_links

    ctx = {"role": "pillar", "pillar_slug": None}
    out = _ensure_internal_links("<p>body</p>", "metal roofing", ctx)
    assert "/blog/" not in out


def test_internal_links_adds_contextual_services_link():
    from jobs.article_job import _ensure_internal_links

    ctx = {"role": "pillar", "pillar_slug": None}
    out = _ensure_internal_links("<p>Learn about roof repair costs.</p>", "roof repair", ctx)
    assert 'href="https://perkinsroofing.net/roof-repair-services/"' in out
    assert "roof repair services" in out


def test_internal_links_does_not_link_an_unrelated_service():
    from jobs.article_job import _ensure_internal_links

    ctx = {"role": "pillar", "pillar_slug": None}
    out = _ensure_internal_links("<p>Gutter cleaning schedules for South Florida homes.</p>",
                                 "gutter cleaning", ctx)
    assert "flat-roofing" not in out
    assert "tile-roofing" not in out


def test_internal_links_is_idempotent():
    from jobs.article_job import _ensure_internal_links

    ctx = {"role": "cluster", "pillar_slug": "metal-roofing-guide", "pillar_title": "Metal Roofing Guide"}
    once = _ensure_internal_links("<p>roof repair body</p>", "roof repair", ctx)
    twice = _ensure_internal_links(once, "roof repair", ctx)
    assert twice == once


def test_internal_links_never_contain_blog_path():
    # Site rule: no /blog/ in post URLs (pillar links AND services links are top-level).
    from jobs.article_job import _ensure_internal_links

    ctx = {"role": "cluster", "pillar_slug": "roof-repair-guide", "pillar_title": "Roof Repair Guide"}
    out = _ensure_internal_links(
        "<p>Roof repair costs and a professional roof inspection matter for every home.</p>",
        "roof repair", ctx)
    assert "/blog/" not in out


def test_matching_service_links_caps_at_three():
    from core.internal_links import matching_service_links

    text = "roof repair roof replacement roof inspection metal roof tile roof flat roof"
    assert len(matching_service_links(text)) == 3


# ── numeric-claim grounding (wiring around core.numeric_grounding) ──────────────────────────

_MPH_TRANSCRIPT = "Panels are rated for 190 to 220 mph in our testing."


def test_soften_removes_only_the_offending_sentence():
    from jobs.article_job import _soften_unsupported_numeric_claims

    html = ("<p>Standing seam panels are strong. This configuration rates at 999 mph in one "
            "test. Homeowners love the look.</p>")
    out = _soften_unsupported_numeric_claims(html, ["999 mph"])
    assert "999" not in out
    assert "Standing seam panels are strong." in out
    assert "Homeowners love the look." in out


def test_soften_drops_an_emptied_single_sentence_paragraph():
    from jobs.article_job import _soften_unsupported_numeric_claims

    html = "<p>This configuration rates at 999 mph.</p>"
    out = _soften_unsupported_numeric_claims(html, ["999 mph"])
    assert "999" not in out
    assert "<p></p>" not in out and "<p> </p>" not in out


def test_numeric_grounding_noop_without_transcript():
    from jobs.article_job import _enforce_numeric_grounding

    fields = {"content_md": "<p>Rated for 260 mph.</p>"}
    out = _enforce_numeric_grounding(fields, "kw", "", llm=_ScriptedLLM())
    assert out is fields
    assert "numeric_claims_stripped" not in out


def test_numeric_grounding_leaves_supported_claims_untouched():
    from jobs.article_job import _enforce_numeric_grounding

    fields = {"content_md": "<p>This roof is rated at 218 mph.</p>"}
    out = _enforce_numeric_grounding(fields, "kw", _MPH_TRANSCRIPT, llm=_ScriptedLLM())
    assert out["content_md"] == fields["content_md"]
    assert out["numeric_claims_stripped"] == []


def test_numeric_grounding_repairs_via_revise_when_the_llm_fixes_it():
    from jobs.article_job import _enforce_numeric_grounding

    fields = {"title": "T", "slug": "s", "meta": "m",
              "content_md": "<p>This roof rated at 260 mph in one test.</p>", "faq_json": []}
    fixed = json.dumps({
        "title": "T", "slug": "s", "metaDescription": "m",
        "content": "<p>This roof rated at 218 mph in one test.</p>", "faq": [],
    })
    llm = _ScriptedLLM(fixed)
    out = _enforce_numeric_grounding(fields, "kw", _MPH_TRANSCRIPT, llm=llm, rounds=2)
    assert "260 mph" not in out["content_md"]
    assert "218" in out["content_md"]
    assert out["numeric_claims_stripped"] == []
    assert len(llm.prompts) == 1  # grounded on the first round — no second attempt needed


def test_numeric_grounding_strips_the_sentence_when_repair_never_grounds_it():
    from jobs.article_job import _enforce_numeric_grounding

    content = ("<p>Great looks. This roof rated at 999 mph in one test. "
               "Long lasting.</p>")
    fields = {"title": "T", "slug": "s", "meta": "m", "content_md": content, "faq_json": []}
    # The reviser keeps returning the same ungrounded figure every round.
    same = json.dumps({
        "title": "T", "slug": "s", "metaDescription": "m", "content": content, "faq": [],
    })
    llm = _ScriptedLLM(same, same)
    out = _enforce_numeric_grounding(fields, "kw", _MPH_TRANSCRIPT, llm=llm, rounds=2)
    assert "999" not in out["content_md"]
    assert "Great looks." in out["content_md"]
    assert "Long lasting." in out["content_md"]
    assert out["numeric_claims_stripped"] == ["999 mph"]
    assert len(llm.prompts) == 2  # exhausted both repair rounds before falling back
