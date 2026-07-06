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
