from core.seo import failing_keys, score_article


def _full_body():
    return "<h1>T</h1><h2>Section</h2>" + ("<p>roofing miami word here </p>" * 90) + \
        ' <a href="https://youtu.be/abc?t=5">watch</a>'


def test_perfect_article_scores_100():
    r = score_article("A" * 40, "m" * 140, _full_body(), [{"q": "Q?", "a": "A"}], has_jsonld=True)
    assert r["score"] == 100
    assert failing_keys(r) == []


def test_headings_check_is_html_aware():
    # HTML <h2> must count (regression: old check only matched markdown ##)
    r = score_article("A" * 40, "m" * 140, "<h2>x</h2>" + ("word " * 400) +
                      "youtu.be/x", [{"q": "Q?", "a": "A"}], True)
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
