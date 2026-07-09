from core.seo import failing_keys, rank_math_checks, rank_math_failures, score_article


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
            _clamp_meta,
            _ensure_answer_first,
            _ensure_heading,
            _ensure_title,
            _ensure_video_link,
            _fallback_faq,
            markdownish_to_html,
        )

        # Mirror the exact sequence in generate_scored_article's guarantee block
        fields["content_md"] = markdownish_to_html(
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
        assert af_check["pass"] is True, "answer_first still failing after guarantee"

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


# ---------------------------------------------------------------------------
# Rank Math SEO checks — rank_math_checks() / rank_math_failures()
# ---------------------------------------------------------------------------

def _rm_good_body(kw: str = "roof repair miami") -> str:
    """Build a well-formed HTML body satisfying all 15 Rank Math checks."""
    kw_slug_word = kw.replace(" ", "-")
    # keyword ~1% density: repeat it ~10 times in ~900 words of filler
    kw_block = f"<p>{kw} {kw} {kw} {kw} {kw}</p>"  # 5 occurrences
    filler = "<p>" + ("word " * 85) + "</p>"  # ~85 words each
    return (
        f"<p>The best {kw} service saves you thousands. "
        f"Homeowners trust our proven {kw} experts.</p>"
        + kw_block
        + f"<h2>Why {kw} Matters for Your Home</h2>"
        + filler * 8
        + f'<img src="roof.jpg" alt="{kw} inspection photo" />'
        + f'<a href="/blog/{kw_slug_word}-guide">Learn more about {kw}</a>'
        + '<a href="https://nrca.net/roofing-resources">NRCA resources</a>'
    )


def _rm_good_title(kw: str = "roof repair miami") -> str:
    return f"5 Proven {kw.title()} Tips: The Complete Guide"


def _rm_good_meta(kw: str = "roof repair miami") -> str:
    return (
        f"Discover the best {kw} solutions for your home. "
        f"Our proven experts deliver fast, guaranteed results you can trust."
    )


def _rm_good_slug(kw: str = "roof repair miami") -> str:
    return kw.replace(" ", "-")


class TestRankMathChecksAllPass:
    """A well-formed article should pass all 15 Rank Math checks."""

    def test_all_15_checks_pass(self):
        kw = "roof repair miami"
        checks = rank_math_checks(
            title=_rm_good_title(kw),
            meta=_rm_good_meta(kw),
            slug=_rm_good_slug(kw),
            content_md=_rm_good_body(kw),
            focus_keyword=kw,
        )
        assert len(checks) == 15
        failures = [c["key"] for c in checks if not c["pass"]]
        assert failures == [], f"Unexpected failures: {failures}"

    def test_returns_15_check_dicts(self):
        checks = rank_math_checks(
            _rm_good_title(), _rm_good_meta(), _rm_good_slug(),
            _rm_good_body(), "roof repair miami",
        )
        assert len(checks) == 15
        for c in checks:
            assert "key" in c
            assert "label" in c
            assert "pass" in c

    def test_rank_math_failures_empty_on_good_article(self):
        kw = "roof repair miami"
        failures = rank_math_failures(
            _rm_good_title(kw), _rm_good_meta(kw), _rm_good_slug(kw),
            _rm_good_body(kw), kw,
        )
        assert failures == []


class TestRankMathBasicSeo:
    """Tests for checks 1–5: keyword placement in title/meta/slug/intro/body."""

    def test_kw_in_title_pass(self):
        checks = rank_math_checks(
            "5 Proven Roof Repair Miami Tips", "meta", "roof-repair-miami",
            _rm_good_body(), "roof repair miami",
        )
        c = next(x for x in checks if x["key"] == "rm_kw_in_title")
        assert c["pass"] is True

    def test_kw_in_title_fail(self):
        checks = rank_math_checks(
            "General Roofing Guide", "meta", "roof-repair-miami",
            _rm_good_body(), "roof repair miami",
        )
        c = next(x for x in checks if x["key"] == "rm_kw_in_title")
        assert c["pass"] is False

    def test_kw_in_meta_pass(self):
        checks = rank_math_checks(
            _rm_good_title(), "Best roof repair miami service available.", "slug",
            _rm_good_body(), "roof repair miami",
        )
        c = next(x for x in checks if x["key"] == "rm_kw_in_meta")
        assert c["pass"] is True

    def test_kw_in_meta_fail(self):
        checks = rank_math_checks(
            _rm_good_title(), "General roofing services for homeowners.", "slug",
            _rm_good_body(), "roof repair miami",
        )
        c = next(x for x in checks if x["key"] == "rm_kw_in_meta")
        assert c["pass"] is False

    def test_kw_in_slug_pass(self):
        checks = rank_math_checks(
            _rm_good_title(), _rm_good_meta(), "roof-repair-miami",
            _rm_good_body(), "roof repair miami",
        )
        c = next(x for x in checks if x["key"] == "rm_kw_in_slug")
        assert c["pass"] is True

    def test_kw_in_slug_fail(self):
        checks = rank_math_checks(
            _rm_good_title(), _rm_good_meta(), "general-roofing-guide",
            _rm_good_body(), "roof repair miami",
        )
        c = next(x for x in checks if x["key"] == "rm_kw_in_slug")
        assert c["pass"] is False

    def test_kw_in_intro_pass(self):
        kw = "roof repair miami"
        body = f"<p>{kw} is essential for homeowners.</p>" + "<p>word </p>" * 100
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, kw)
        c = next(x for x in checks if x["key"] == "rm_kw_in_intro")
        assert c["pass"] is True

    def test_kw_in_intro_fail(self):
        kw = "roof repair miami"
        # keyword only appears very late (after the first 10%)
        body = "<p>word </p>" * 200 + f"<p>{kw}</p>"
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, kw)
        c = next(x for x in checks if x["key"] == "rm_kw_in_intro")
        assert c["pass"] is False

    def test_kw_in_body_pass(self):
        kw = "roof repair miami"
        body = "<p>word </p>" * 50 + f"<p>{kw}</p>"
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, kw)
        c = next(x for x in checks if x["key"] == "rm_kw_in_body")
        assert c["pass"] is True

    def test_kw_in_body_fail(self):
        kw = "roof repair miami"
        body = "<p>general roofing content</p>" * 10
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, kw)
        c = next(x for x in checks if x["key"] == "rm_kw_in_body")
        assert c["pass"] is False


class TestRankMathHeadingAndImage:
    """Tests for checks 6–7: keyword in subheading and image alt."""

    def test_kw_in_heading_pass(self):
        kw = "roof repair miami"
        body = f"<h2>Why {kw} Experts Matter</h2>" + "<p>word </p>" * 50
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, kw)
        c = next(x for x in checks if x["key"] == "rm_kw_in_heading")
        assert c["pass"] is True

    def test_kw_in_heading_h3_pass(self):
        kw = "roof repair miami"
        body = f"<h3>Top {kw} services</h3>" + "<p>word </p>" * 50
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, kw)
        c = next(x for x in checks if x["key"] == "rm_kw_in_heading")
        assert c["pass"] is True

    def test_kw_in_heading_fail(self):
        kw = "roof repair miami"
        body = "<h2>General Roofing Tips</h2>" + "<p>word </p>" * 50
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, kw)
        c = next(x for x in checks if x["key"] == "rm_kw_in_heading")
        assert c["pass"] is False

    def test_kw_in_img_alt_pass(self):
        kw = "roof repair miami"
        body = f'<img src="x.jpg" alt="{kw} photo" />' + "<p>word </p>" * 50
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, kw)
        c = next(x for x in checks if x["key"] == "rm_kw_in_img_alt")
        assert c["pass"] is True

    def test_kw_in_img_alt_fail_no_img(self):
        kw = "roof repair miami"
        body = "<p>word </p>" * 50
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, kw)
        c = next(x for x in checks if x["key"] == "rm_kw_in_img_alt")
        assert c["pass"] is False

    def test_kw_in_img_alt_fail_wrong_alt(self):
        kw = "roof repair miami"
        body = '<img src="x.jpg" alt="generic photo" />' + "<p>word </p>" * 50
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, kw)
        c = next(x for x in checks if x["key"] == "rm_kw_in_img_alt")
        assert c["pass"] is False


class TestRankMathDensityAndSlug:
    """Tests for checks 8–9: keyword density and slug length."""

    def test_density_in_range_pass(self):
        kw = "roof repair miami"
        # ~900 words, keyword 9 times → ~1% density
        body = f"<p>{kw} </p>" * 9 + "<p>word </p>" * 873
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, kw)
        c = next(x for x in checks if x["key"] == "rm_kw_density")
        assert c["pass"] is True

    def test_density_too_low_fail(self):
        kw = "roof repair miami"
        # keyword once in 1000 words → 0.1% density
        body = f"<p>{kw}</p>" + "<p>word </p>" * 997
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, kw)
        c = next(x for x in checks if x["key"] == "rm_kw_density")
        assert c["pass"] is False

    def test_density_too_high_fail(self):
        kw = "roof repair miami"
        # keyword 30 times in ~100 words → ~9% density
        body = f"<p>{kw} </p>" * 30 + "<p>word </p>" * 10
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, kw)
        c = next(x for x in checks if x["key"] == "rm_kw_density")
        assert c["pass"] is False

    def test_slug_under_75_pass(self):
        checks = rank_math_checks(
            _rm_good_title(), _rm_good_meta(), "roof-repair-miami",
            _rm_good_body(), "roof repair miami",
        )
        c = next(x for x in checks if x["key"] == "rm_slug_length")
        assert c["pass"] is True

    def test_slug_exactly_74_pass(self):
        slug = "a" * 74
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), slug, _rm_good_body(), "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_slug_length")
        assert c["pass"] is True

    def test_slug_75_chars_fail(self):
        slug = "a" * 75
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), slug, _rm_good_body(), "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_slug_length")
        assert c["pass"] is False


class TestRankMathLinks:
    """Tests for checks 10–11: internal and external DoFollow links."""

    def test_internal_link_pass(self):
        body = '<a href="/blog/other-article">More info</a>' + "<p>word </p>" * 50
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_internal_link")
        assert c["pass"] is True

    def test_internal_link_fail_no_links(self):
        body = "<p>word </p>" * 50
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_internal_link")
        assert c["pass"] is False

    def test_internal_link_fail_only_external(self):
        body = '<a href="https://example.com">external</a>' + "<p>word </p>" * 50
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_internal_link")
        assert c["pass"] is False

    def test_external_dofollow_pass(self):
        body = '<a href="https://nrca.net/resources">NRCA</a>' + "<p>word </p>" * 50
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_external_link")
        assert c["pass"] is True

    def test_external_nofollow_fail(self):
        body = (
            '<a href="https://nrca.net/resources" rel="nofollow">NRCA</a>'
            + "<p>word </p>" * 50
        )
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_external_link")
        assert c["pass"] is False

    def test_external_link_fail_no_links(self):
        body = "<p>word </p>" * 50
        checks = rank_math_checks(_rm_good_title(), _rm_good_meta(), _rm_good_slug(), body, "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_external_link")
        assert c["pass"] is False


class TestRankMathTitleReadability:
    """Tests for checks 12–15: keyword position, sentiment, power word, number."""

    def test_kw_near_start_pass(self):
        # keyword at position 0 → in first half
        title = "roof repair miami: 5 Proven Tips for Homeowners"
        checks = rank_math_checks(title, _rm_good_meta(), _rm_good_slug(), _rm_good_body(), "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_title_kw_position")
        assert c["pass"] is True

    def test_kw_near_start_fail(self):
        # keyword at end of long title
        title = "The Complete Homeowners Guide to Getting: roof repair miami"
        checks = rank_math_checks(title, _rm_good_meta(), _rm_good_slug(), _rm_good_body(), "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_title_kw_position")
        assert c["pass"] is False

    def test_positive_sentiment_pass(self):
        title = "5 Best Roof Repair Miami Tips for Homeowners"
        checks = rank_math_checks(title, _rm_good_meta(), _rm_good_slug(), _rm_good_body(), "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_title_sentiment")
        assert c["pass"] is True

    def test_negative_sentiment_pass(self):
        title = "7 Roof Repair Miami Mistakes to Avoid This Year"
        checks = rank_math_checks(title, _rm_good_meta(), _rm_good_slug(), _rm_good_body(), "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_title_sentiment")
        assert c["pass"] is True

    def test_no_sentiment_fail(self):
        title = "Roof Repair Miami: A 5-Step Process"
        checks = rank_math_checks(title, _rm_good_meta(), _rm_good_slug(), _rm_good_body(), "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_title_sentiment")
        assert c["pass"] is False

    def test_power_word_pass(self):
        title = "5 Proven Roof Repair Miami Secrets"
        checks = rank_math_checks(title, _rm_good_meta(), _rm_good_slug(), _rm_good_body(), "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_title_power_word")
        assert c["pass"] is True

    def test_no_power_word_fail(self):
        title = "Roof Repair Miami: A 5-Step Process for Your Home"
        checks = rank_math_checks(title, _rm_good_meta(), _rm_good_slug(), _rm_good_body(), "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_title_power_word")
        assert c["pass"] is False

    def test_number_in_title_pass(self):
        title = "5 Proven Roof Repair Miami Tips"
        checks = rank_math_checks(title, _rm_good_meta(), _rm_good_slug(), _rm_good_body(), "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_title_number")
        assert c["pass"] is True

    def test_no_number_in_title_fail(self):
        title = "Proven Roof Repair Miami Tips for Homeowners"
        checks = rank_math_checks(title, _rm_good_meta(), _rm_good_slug(), _rm_good_body(), "roof repair miami")
        c = next(x for x in checks if x["key"] == "rm_title_number")
        assert c["pass"] is False


class TestRankMathEmptyKeyword:
    """When focus_keyword is empty/None, all keyword-dependent checks must fail cleanly."""

    def test_empty_keyword_all_kw_checks_fail(self):
        checks = rank_math_checks(
            _rm_good_title(), _rm_good_meta(), _rm_good_slug(), _rm_good_body(), "",
        )
        kw_keys = {
            "rm_kw_in_title", "rm_kw_in_meta", "rm_kw_in_slug",
            "rm_kw_in_intro", "rm_kw_in_body", "rm_kw_in_heading",
            "rm_kw_in_img_alt", "rm_kw_density",
            "rm_title_kw_position",
        }
        for c in checks:
            if c["key"] in kw_keys:
                assert c["pass"] is False, f"{c['key']} should fail with empty keyword"

    def test_none_keyword_no_crash(self):
        checks = rank_math_checks(
            _rm_good_title(), _rm_good_meta(), _rm_good_slug(), _rm_good_body(), None,
        )
        assert len(checks) == 15


class TestRankMathHardFailuresQaGate:
    """Tests for core.qa_gate.seo_hard_failures() integration."""

    def test_no_hard_failures_on_good_article(self):
        from core.qa_gate import seo_hard_failures
        kw = "roof repair miami"
        failures = seo_hard_failures(
            _rm_good_title(kw), _rm_good_meta(kw), _rm_good_slug(kw),
            _rm_good_body(kw), kw,
        )
        assert failures == []

    def test_hard_failure_kw_missing_from_title(self):
        from core.qa_gate import seo_hard_failures
        kw = "roof repair miami"
        failures = seo_hard_failures(
            "Generic Roofing Guide for Homeowners Today",
            _rm_good_meta(kw), _rm_good_slug(kw), _rm_good_body(kw), kw,
        )
        assert "rm_kw_in_title" in failures

    def test_hard_failure_no_internal_link(self):
        from core.qa_gate import seo_hard_failures
        kw = "roof repair miami"
        body = _rm_good_body(kw).replace(
            '<a href="/blog/roof-repair-miami-guide">Learn more about roof repair miami</a>', ""
        )
        failures = seo_hard_failures(
            _rm_good_title(kw), _rm_good_meta(kw), _rm_good_slug(kw), body, kw,
        )
        assert "rm_internal_link" in failures

    def test_soft_checks_not_in_hard_failures(self):
        from core.qa_gate import seo_hard_failures
        kw = "roof repair miami"
        # Title with no number, no power word, no sentiment — soft checks only
        title = "Roof Repair Miami: A Complete Overview for Homeowners Here"
        failures = seo_hard_failures(
            title, _rm_good_meta(kw), _rm_good_slug(kw), _rm_good_body(kw), kw,
        )
        soft_keys = {"rm_kw_in_img_alt", "rm_title_sentiment", "rm_title_power_word", "rm_title_number"}
        assert not any(k in failures for k in soft_keys)
