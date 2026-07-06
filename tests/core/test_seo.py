from core.seo import failing_keys, score_article


def _full_body():
    # 4 FAQ items, answer-first lede, heading, word count, video
    return (
        "<h2>Section</h2>"
        "<p>South Florida homeowners should prioritize roof maintenance annually.</p>"
        + ("<p>roofing miami word here </p>" * 90)
        + ' <a href="https://youtu.be/abc?t=5">watch</a>'
    )


def _four_faq():
    return [
        {"q": "Q1?", "a": "A1"},
        {"q": "Q2?", "a": "A2"},
        {"q": "Q3?", "a": "A3"},
        {"q": "Q4?", "a": "A4"},
    ]


def test_perfect_article_scores_100():
    r = score_article(
        "A" * 40, "m" * 140, _full_body(), _four_faq(),
        has_jsonld=True, keyword="a" * 40,
    )
    assert r["score"] == 100, failing_keys(r)
    assert failing_keys(r) == []


def test_perfect_article_scores_100_no_keyword():
    # When keyword is omitted keyword_in_title auto-passes
    r = score_article("A" * 40, "m" * 140, _full_body(), _four_faq(), has_jsonld=True)
    assert r["score"] == 100, failing_keys(r)


def test_headings_check_is_html_aware():
    # HTML <h2> must count (regression: old check only matched markdown ##)
    r = score_article("A" * 40, "m" * 140, "<h2>x</h2>" + ("word " * 400) +
                      "youtu.be/x", _four_faq(), True)
    assert next(c["pass"] for c in r["checks"] if c["key"] == "headings") is True


def test_word_count_strips_html_tags():
    # 5 real words wrapped in many tags must not be inflated by tag names
    body = "<div><p><strong>one two three four five</strong></p></div>"
    r = score_article("t", "m", body, [], False)
    wc = next(c for c in r["checks"] if c["key"] == "wordcount")
    assert wc["detail"] == "5 words"
    assert wc["pass"] is False


def test_meta_and_title_bands():
    r = score_article("short", "x" * 200, "body", [], False)
    fails = failing_keys(r)
    assert "title_len" in fails      # 5 chars < 30
    assert "meta_len" in fails       # 200 chars > 160
    assert "meta_present" not in fails


def test_keyword_in_title_pass_and_fail():
    title = "Roof Repair Miami Guide"
    # keyword present → pass
    r_pass = score_article(title, "m" * 140, _full_body(), _four_faq(), True, keyword="roof repair miami")
    kw_check = next(c for c in r_pass["checks"] if c["key"] == "keyword_in_title")
    assert kw_check["pass"] is True

    # keyword absent → fail
    r_fail = score_article(title, "m" * 140, _full_body(), _four_faq(), True, keyword="tile roofing florida")
    kw_check_f = next(c for c in r_fail["checks"] if c["key"] == "keyword_in_title")
    assert kw_check_f["pass"] is False


def test_keyword_in_title_no_keyword_autopasses():
    r = score_article("A" * 40, "m" * 140, _full_body(), _four_faq(), True, keyword="")
    kw_check = next(c for c in r["checks"] if c["key"] == "keyword_in_title")
    assert kw_check["pass"] is True


def test_answer_first_lede_pass_and_fail():
    # Body with an early sentence → passes
    body_pass = "<p>South Florida homeowners need annual roof inspections.</p>" + ("word " * 400)
    r_pass = score_article("A" * 40, "m" * 140, body_pass, _four_faq(), True)
    af = next(c for c in r_pass["checks"] if c["key"] == "answer_first")
    assert af["pass"] is True

    # Body starting with only a heading (no sentence in first 200 chars) → fails
    body_fail = "<h2>" + ("x" * 180) + "</h2>" + ("word " * 400)
    r_fail = score_article("A" * 40, "m" * 140, body_fail, _four_faq(), True)
    af_f = next(c for c in r_fail["checks"] if c["key"] == "answer_first")
    assert af_f["pass"] is False


def test_faq_count_check():
    # 3 items → faq passes, faq_count fails
    three_faq = [{"q": f"Q{i}?", "a": "A"} for i in range(3)]
    r = score_article("A" * 40, "m" * 140, _full_body(), three_faq, True)
    assert next(c["pass"] for c in r["checks"] if c["key"] == "faq") is True
    assert next(c["pass"] for c in r["checks"] if c["key"] == "faq_count") is False

    # 4 items → both pass
    r4 = score_article("A" * 40, "m" * 140, _full_body(), _four_faq(), True)
    assert next(c["pass"] for c in r4["checks"] if c["key"] == "faq_count") is True


def test_max_is_100():
    r = score_article("t", "m", "body", [], False)
    assert r["max"] == 100


# ---------------------------------------------------------------------------
# Deterministic guarantee helpers (_ensure_title, _ensure_heading,
# _ensure_answer_first) and the guarantee that they collectively produce
# score == 100 on a deliberately deficient article.
# ---------------------------------------------------------------------------

from jobs.article_job import (  # noqa: E402
    _ensure_answer_first,
    _ensure_heading,
    _ensure_title,
    _word_count_str,
)


class TestEnsureTitle:
    """_ensure_title must guarantee: keyword present AND 30 ≤ len ≤ 65."""

    def test_keyword_inserted_when_missing(self):
        title = _ensure_title("Roofing Tips", "metal roofing florida")
        assert "metal roofing florida" in title.lower()
        assert 30 <= len(title) <= 65

    def test_already_good_title_unchanged(self):
        title = "Metal Roofing Florida: Complete Homeowner Guide"
        assert _ensure_title(title, "metal roofing florida") == title

    def test_short_title_padded_to_30(self):
        title = _ensure_title("Fix", "fix roof")
        assert len(title) >= 30

    def test_long_title_trimmed_to_65(self):
        long = "Fix Roof: The Absolutely Most Complete and Thorough Guide Ever Written for Homeowners in South Florida"
        result = _ensure_title(long, "fix roof")
        assert len(result) <= 65
        assert "fix roof" in result.lower()

    def test_keyword_still_present_after_trim(self):
        # Keyword is 30 chars — trim must not cut it away
        kw = "emergency roof leak repair now"
        result = _ensure_title("A" * 5, kw)
        assert kw in result.lower()
        assert 30 <= len(result) <= 65

    def test_empty_title_synthesized(self):
        result = _ensure_title("", "roof inspection")
        assert "roof inspection" in result.lower()
        assert 30 <= len(result) <= 65

    def test_no_keyword_enforces_length_only(self):
        # Empty keyword → only length enforcement
        result = _ensure_title("x" * 80, "")
        assert len(result) <= 65


class TestEnsureHeading:
    """_ensure_heading must guarantee ≥1 <h2> in content."""

    def test_injects_h2_when_absent(self):
        content = "<p>Some roofing text without any headings here.</p>"
        result = _ensure_heading(content, "flat roof repair")
        assert "<h2>" in result

    def test_existing_h2_not_duplicated(self):
        content = "<h2>Already Here</h2><p>text</p>"
        result = _ensure_heading(content, "flat roof repair")
        assert result == content
        assert result.count("<h2>") == 1

    def test_existing_h3_satisfies_check(self):
        content = "<h3>Sub Section</h3><p>text</p>"
        result = _ensure_heading(content, "flat roof repair")
        assert result == content

    def test_injected_heading_contains_keyword(self):
        content = "<p>plain text</p>"
        result = _ensure_heading(content, "tile roofing cost")
        assert "tile roofing cost" in result.lower()


class TestEnsureAnswerFirst:
    """_ensure_answer_first must guarantee a sentence in the first 200 plain-text chars."""

    def test_prepends_lede_when_no_sentence(self):
        content = "<h2>Section</h2>" + "<p>word</p>" * 10
        result = _ensure_answer_first(content, "roof inspection", [])
        # plain-text head must now contain a sentence
        import re
        plain = re.sub(r"<[^>]+>", " ", result)
        plain = re.sub(r"[#*>`_~\[\]]", " ", plain)
        head = re.sub(r"\s+", " ", plain).strip()[:200]
        assert re.search(r"\w{4,}.*\.", head, re.DOTALL)

    def test_uses_first_faq_answer_as_lede(self):
        faq = [{"q": "What is roof inspection?", "a": "A roof inspection checks for damage."}]
        content = "<h2>Section</h2>" + "<p>word</p>" * 5
        result = _ensure_answer_first(content, "roof inspection", faq)
        assert "roof inspection checks for damage" in result.lower()

    def test_existing_sentence_leaves_content_unchanged(self):
        content = "<p>South Florida homeowners need annual roof inspections.</p>" + "<p>word</p>" * 5
        result = _ensure_answer_first(content, "roof inspection", [])
        assert result == content

    def test_empty_content_gets_lede(self):
        result = _ensure_answer_first("", "roof repair", [])
        import re
        plain = re.sub(r"<[^>]+>", " ", result)
        head = re.sub(r"\s+", " ", plain).strip()[:200]
        assert re.search(r"\w{4,}.*\.", head, re.DOTALL)


class TestDeterministicGuaranteesScore100:
    """Feed a deliberately deficient fields dict through the guarantee block and
    assert that the resulting article scores 100/100 on core.seo.score_article."""

    def _apply_guarantees(self, fields: dict, keyword: str) -> dict:
        """Apply only the deterministic guarantee helpers (no LLM calls)."""
        from jobs.article_job import (
            _build_article_jsonld,
            _clamp_meta,
            _ensure_answer_first,
            _ensure_heading,
            _ensure_title,
            _ensure_video_link,
            _fallback_faq,
            sanitize_article_html,
        )

        # Mirror the exact sequence in generate_scored_article's guarantee block
        fields["content_md"] = sanitize_article_html(
            _ensure_video_link(fields.get("content_md", ""), keyword)
        )
        fields["meta"] = _clamp_meta(
            fields.get("meta", ""), fields.get("title", ""), fields.get("content_md", "")
        )
        if not fields.get("faq_json"):
            fields["faq_json"] = _fallback_faq(keyword, fields.get("content_md", ""))
        elif len(fields["faq_json"]) < 4:
            extra = _fallback_faq(keyword, fields.get("content_md", ""))
            existing_qs = {f["q"].lower() for f in fields["faq_json"]}
            for item in extra:
                if item["q"].lower() not in existing_qs and len(fields["faq_json"]) < 4:
                    fields["faq_json"].append(item)

        fields["title"] = _ensure_title(fields.get("title", ""), keyword)
        fields["content_md"] = _ensure_heading(fields.get("content_md", ""), keyword)
        fields["content_md"] = _ensure_answer_first(
            fields.get("content_md", ""), keyword, fields.get("faq_json") or []
        )
        return fields

    def test_deficient_fields_score_100(self):
        """Start with the worst possible fields and verify guarantees lift score to 100.

        The video check (_ensure_video_link) requires live retrieval, so we include
        a bare YouTube URL in the body — the guarantee still exercises every other fix.
        """
        keyword = "roof repair miami"

        # Deliberately deficient: wrong title, no meta, no heading, no answer-first,
        # no FAQ. Video link is pre-seeded so we don't need live retrieval.
        # word count: 310 "word" tokens + URL fragment → well over 300.
        body = "word " * 310 + ' <a href="https://youtu.be/abc123?t=5">watch</a>'
        fields = {
            "title": "R",             # too short, no keyword
            "slug": "roof-repair",
            "meta": "",               # missing
            "content_md": body,
            "faq_json": [],           # empty
        }

        fields = self._apply_guarantees(fields, keyword)

        jsonld = [{"@type": "Article"}]  # non-empty → has_jsonld=True
        result = score_article(
            fields["title"],
            fields["meta"],
            fields["content_md"],
            fields["faq_json"],
            has_jsonld=True,
            keyword=keyword,
        )
        fails = failing_keys(result)
        assert result["score"] == 100, f"Expected 100, got {result['score']}. Failing: {fails}"

    def test_keyword_in_title_guaranteed(self):
        keyword = "emergency roof tarping"
        fields = {
            "title": "Some Generic Title Without The Keyword In It",
            "slug": "t",
            "meta": "m" * 140,
            "content_md": (
                "<h2>Section</h2>"
                "<p>South Florida roofers handle emergency situations quickly.</p>"
                + ("word " * 310)
                + ' <a href="https://youtu.be/abc">video</a>'
            ),
            "faq_json": [{"q": f"Q{i}", "a": "A"} for i in range(4)],
        }
        from jobs.article_job import _ensure_title
        fields["title"] = _ensure_title(fields["title"], keyword)
        assert keyword in fields["title"].lower()
        assert 30 <= len(fields["title"]) <= 65

        result = score_article(
            fields["title"], fields["meta"], fields["content_md"],
            fields["faq_json"], has_jsonld=True, keyword=keyword,
        )
        kw_check = next(c for c in result["checks"] if c["key"] == "keyword_in_title")
        title_check = next(c for c in result["checks"] if c["key"] == "title_len")
        assert kw_check["pass"] is True
        assert title_check["pass"] is True

    def test_answer_first_guaranteed(self):
        keyword = "flat roof coating"
        content_no_sentence = "<h2>Overview</h2>" + "<p>word</p>" * 310
        from jobs.article_job import _ensure_answer_first
        result_content = _ensure_answer_first(content_no_sentence, keyword, [])

        result = score_article(
            "Flat Roof Coating: Guide for South Florida",
            "m" * 140,
            result_content,
            [{"q": f"Q{i}", "a": "A"} for i in range(4)],
            has_jsonld=True,
            keyword=keyword,
        )
        af_check = next(c for c in result["checks"] if c["key"] == "answer_first")
        assert af_check["pass"] is True, f"answer_first still failing after guarantee"

    def test_headings_guaranteed(self):
        keyword = "shingle replacement"
        content_no_heading = (
            "<p>South Florida homeowners choose shingle replacement for value.</p>"
            + "<p>word </p>" * 310
            + ' <a href="https://youtu.be/abc">video</a>'
        )
        from jobs.article_job import _ensure_heading
        result_content = _ensure_heading(content_no_heading, keyword)

        result = score_article(
            "Shingle Replacement: Complete Guide South Florida",
            "m" * 140,
            result_content,
            [{"q": f"Q{i}", "a": "A"} for i in range(4)],
            has_jsonld=True,
            keyword=keyword,
        )
        h_check = next(c for c in result["checks"] if c["key"] == "headings")
        assert h_check["pass"] is True
