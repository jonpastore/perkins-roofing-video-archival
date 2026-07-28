"""core.article_criteria — the authoritative Wendy compliance checklist."""

from core.article_criteria import check_compliance, failing, is_compliant

VID = "BnsaVtCb0GU"  # a real 11-char id we mark as known/grounded
KNOWN = {VID}

# A fully-compliant cluster article: 3 sections with <h2 id> anchors but NO in-content TOC block
# (Wendy 2026-07-28 — the theme sidebar builds it), curated (non-title-card) image, embedded
# known video, service link, subscribe CTA on the @handle, pillar link, FAQ handled below.
_GOOD = (
    '<p>Metal roof cost in South Florida runs $12,000–$30,000 installed.</p>'
    '<h2 id="a">Cost factors</h2><p>Metal roof cost depends on square footage.</p>'
    '<h2 id="b">Materials</h2><p>Aluminum and steel differ in metal roof cost.</p>'
    '<h2 id="c">What Does the Warranty Cover?</h2><p>Metal roof cost includes warranty coverage.</p>'
    f'<img src="https://i.ytimg.com/vi/{VID}/maxres2.jpg" alt="Metal Roof Cost — Perkins Roofing" />'
    f'<div class="video-embed"><iframe src="https://www.youtube.com/embed/{VID}"></iframe></div>'
    '<p class="related-links">Related: '
    '<a href="https://perkinsroofing.net/metal-roofing-guide">Metal Roofing Guide</a> | '
    '<a href="https://perkinsroofing.net/metal-roofing-company/">metal roofing services</a></p>'
    '<p>Subscribe to our YouTube channel for more! '
    '<a href="https://www.youtube.com/@perkinsroofingcorp">@perkinsroofingcorp</a></p>'
)
_META = ("Metal roof cost in South Florida: what homeowners pay, the factors that "
         "drive price, and how Perkins Roofing estimates your project accurately.")  # 120–160
_FAQ = [{"q": f"Q{i} about metal roof cost?", "a": "A."} for i in range(4)]
_JSONLD = [{"@type": "FAQPage"}, {"@type": "VideoObject"}]
_CTX = {"role": "cluster", "pillar_slug": "metal-roofing-guide",
        "title": "Metal Roof Cost Guide 2026", "slug": "metal-roof-cost"}


def _keys_failing(**overrides):
    args = dict(content=_GOOD, meta=_META, jsonld=_JSONLD, faq=_FAQ, ctx=_CTX,
                keyword="metal roof cost", known_video_ids=KNOWN)
    args.update(overrides)
    return {c.key for c in failing(check_compliance(**args))}


def test_all_structural_criteria_pass_on_a_good_article():
    # Every DETERMINISTIC/structural criterion passes on a well-formed article.
    # seo_ranking + answer_first need a full ~1500-word body (Rank Math density,
    # per-section direct answers) — the scored generation loop satisfies those;
    # a synthetic fixture legitimately can't, so they're proven by the batch run,
    # not here. Everything else must be green.
    fails = _keys_failing()
    assert fails <= {"seo_ranking", "answer_first"}, f"structural criteria failing: {fails}"


def test_statement_only_headings_are_caught():
    """≥1 question-phrased heading is GATED (not advisory) because _ensure_faq_headings can
    always satisfy it from the article's own FAQ. An article of statement headings fails."""
    statements = _GOOD.replace("What Does the Warranty Cover?", "Warranty Coverage")
    assert "question_heading" in _keys_failing(content=statements)


def test_blog_url_is_caught():
    bad = _GOOD.replace("/metal-roofing-guide", "/blog/metal-roofing-guide")
    assert "no_blog" in _keys_failing(content=bad)


def test_fewer_than_four_faq_is_caught():
    assert "faq_ge4" in _keys_failing(faq=_FAQ[:3])


def test_title_card_image_is_caught():
    bad = _GOOD.replace("maxres2.jpg", "hqdefault.jpg")
    assert "curated_image" in _keys_failing(content=bad)


def test_stray_schema_type_is_caught():
    assert "schema_scoped" in _keys_failing(jsonld=[*_JSONLD, {"@type": "Article"}])


def test_short_meta_is_caught():
    assert "meta_len" in _keys_failing(meta="too short")


def test_missing_subscribe_cta_is_caught():
    bad = _GOOD.replace("Subscribe to our YouTube channel for more! ", "").replace(
        '<a href="https://www.youtube.com/@perkinsroofingcorp">@perkinsroofingcorp</a>', "")
    assert "subscribe_cta" in _keys_failing(content=bad)


def test_unknown_video_id_is_caught():
    assert "valid_video_ids" in _keys_failing(known_video_ids=set())


def test_dead_staging_host_is_caught():
    bad = _GOOD + '<a href="https://1228404.us6.myftpupload.com/x">dead</a>'
    assert "no_dead_hosts" in _keys_failing(content=bad)


def test_cluster_missing_pillar_link_is_caught():
    bad = _GOOD.replace("https://perkinsroofing.net/metal-roofing-guide", "https://perkinsroofing.net/other")
    assert "pillar_link" in _keys_failing(content=bad)


def test_answer_first_lede_passes_on_a_long_opening_sentence():
    # A normal declarative opening can exceed 200 chars; its terminating period must still be
    # detected (the 200-char window missed it and made answer_first flake).
    long_lede = ("<p>In Florida's hot and humid coastal climate, proper roof ventilation "
                 "prevents excessive heat buildup in the attic, which over time can lead to "
                 "thermal expansion damage like nail pops, a measurably reduced roof lifespan, "
                 "and noticeably higher monthly energy bills for homeowners.</p>")
    assert len(long_lede) > 220
    ok = _keys_failing(content=long_lede + _GOOD, keyword="roof ventilation")
    assert "answer_first" not in ok


def test_answer_first_caught_when_lede_is_only_fragments():
    bad = "<h2>Heading</h2><ul><li>a</li><li>b</li></ul>" + ("<p>word word word</p>" * 20)
    assert "answer_first" in _keys_failing(content=bad)


# ---------------------------------------------------------------------------
# Wendy's 2026-07-28 review. Each of these reproduces a defect she found on the LIVE
# 26-gauge-metal-panels post, so the gate now fails what she had to point out by hand.
# Validated against the published page before writing: every claim was correct.
# ---------------------------------------------------------------------------

def test_in_content_toc_block_is_rejected():
    """"The Table of Contents should not be added to the content area, as we have it automated
    in the side bar." This REVERSES the old `toc` criterion, which required one."""
    with_toc = _GOOD.replace(
        '<h2 id="a">',
        '<div class="toc"><p><strong>In This Article</strong></p>'
        '<ul><li><a href="#a">A</a></li></ul></div><h2 id="a">', 1)
    assert "no_toc_block" in _keys_failing(content=with_toc)
    assert "no_toc_block" not in _keys_failing()      # the good article has none

    # SECOND shape: the old pillar prompt asked for a "Table of Contents" H2 + list rather than
    # core.seo.ensure_toc's <div class="toc">. 59 pillar articles carry it, and matching only the
    # div form left every one of them live.
    h2_toc = _GOOD.replace(
        '<h2 id="a">',
        '<h2>Table of Contents</h2><ul><li><a href="#a">Cost factors</a></li></ul><h2 id="a">', 1)
    assert "no_toc_block" in _keys_failing(content=h2_toc)

    # THIRD shape: a descriptive <p> between the heading and the list. Two passes went out
    # before this one was found still live on /perkins-roofing/.
    h2_p_toc = _GOOD.replace(
        '<h2 id="a">',
        '<h2>Table of Contents</h2><p>A navigable list of topics.</p>'
        '<ul><li><a href="#a">Cost factors</a></li></ul><h2 id="a">', 1)
    assert "no_toc_block" in _keys_failing(content=h2_p_toc)


def test_unlinked_learn_more_is_rejected_but_a_real_link_passes():
    """"The Learn More content at the bottom of each section is not linking anywhere."
    The live post shipped `<p>Learn more: Understanding Metal Roof Gauge and ...</p>` as prose."""
    unlinked = _GOOD + "<p>Learn more: Understanding Metal Roof Gauge and go deeper.</p>"
    assert "learn_more_linked" in _keys_failing(content=unlinked)
    linked = _GOOD + '<p>Learn more: <a href="/metal-roof-gauge/">Metal Roof Gauge</a></p>'
    assert "learn_more_linked" not in _keys_failing(content=linked)

    # BARE MARKDOWN form — the common one, and the one that reached the live site. content_md
    # stores it unwrapped; _markdown_to_html adds the <p> only at publish, so gating on the <p>
    # form alone passed the stored row while readers saw dead pointers.
    bare = _GOOD + "\n\nLearn more: Understanding Roofing Metal Corrosion Prevention\n"
    assert "learn_more_linked" in _keys_failing(content=bare)
    bare_linked = _GOOD + "\n\nLearn more: [Metal Roof Gauge](/metal-roof-gauge/)\n"
    assert "learn_more_linked" not in _keys_failing(content=bare_linked)


def test_videoobject_may_not_outnumber_embedded_players():
    """"Google says we can only have video object schema for embedded videos, not links to
    videos." The live post had 6 VideoObject nodes against 1 iframe."""
    six = [{"@type": "FAQPage"}] + [{"@type": "VideoObject"}] * 6
    assert "videoobject_only_embedded" in _keys_failing(jsonld=six)
    assert "videoobject_only_embedded" not in _keys_failing()   # 1 VideoObject, 1 iframe


def test_duplicate_related_links_are_rejected():
    """"There is duplication on the related inks" — /metal-roofing-company/ shipped twice."""
    dupe = _GOOD.replace(
        '<a href="https://perkinsroofing.net/metal-roofing-company/">metal roofing services</a>',
        '<a href="https://perkinsroofing.net/metal-roofing-company/">metal roofing services</a> | '
        '<a href="https://perkinsroofing.net/metal-roofing-company/">metal roofers</a>', 1)
    assert "related_links_unique" in _keys_failing(content=dupe)
    assert "related_links_unique" not in _keys_failing()


def test_retired_youtube_channel_url_is_rejected():
    """"We've updated on live the URL for their YouTube channel. It is now
    .../@perkinsroofingcorp". The live post carried BOTH that and the old channel/UC... URL,
    and the old regex also accepted the bare word "subscribe" with no link at all."""
    legacy = _GOOD.replace(
        "https://www.youtube.com/@perkinsroofingcorp",
        "https://www.youtube.com/channel/UChJZpBYXOuR0j1EHJugv5hg")
    assert "subscribe_cta" in _keys_failing(content=legacy)
    assert "subscribe_cta" in _keys_failing(content="<p>subscribe</p>")
    assert "subscribe_cta" not in _keys_failing()


def test_dead_anchors_are_rejected_but_aside_callouts_are_not():
    """WordPress STRIPS a slashless relative href, so <a href="some-slug"> reaches the reader as
    a bare <a> with nothing to click — literally what Wendy saw as "not linking anywhere".
    The <aside> guard is load-bearing: "<a" also prefixes "<aside", and without it this flagged
    333 of 375 articles and the repair would have eaten the callout bodies."""
    assert "no_dead_anchors" in _keys_failing(
        content=_GOOD + '<p>See <a href="metal-roof-gauge">this</a>.</p>')
    assert "no_dead_anchors" in _keys_failing(content=_GOOD + "<p>See <a>this</a>.</p>")
    assert "no_dead_anchors" not in _keys_failing(
        content=_GOOD + '<aside class="note"><p>A callout, not a link.</p></aside>')
    # <a id="..."></a> is an anchor TARGET, not a broken link. Older articles put the id there
    # instead of on the <h2>; deleting them breaks every deep link into the page.
    assert "no_dead_anchors" not in _keys_failing(
        content=_GOOD + '<h2><a id="section-one"></a>Section One</h2>')
    assert "no_dead_anchors" not in _keys_failing()


def test_tel_links_must_be_bare_digits():
    """WordPress keeps tel: (the theme's own render fine) but STRIPS the "+" E.164 form, so
    <a href="tel:+15615597663"> reached readers as a dead <a> around a phone number. A lettered
    "tel:305-MIA-ROOF" is not dialable at all."""
    from core.article_repair import _repair_tel_hrefs
    assert "no_dead_anchors" in _keys_failing(
        content=_GOOD + '<p>Call <a href="tel:+15615597663">561-559-ROOF</a>.</p>')
    assert "no_dead_anchors" in _keys_failing(
        content=_GOOD + '<p>Call <a href="tel:305-MIA-ROOF">305-MIA-ROOF</a>.</p>')
    assert "no_dead_anchors" not in _keys_failing(
        content=_GOOD + '<p>Call <a href="tel:5615597663">561-559-ROOF</a>.</p>')
    # and the repair produces exactly the form the gate accepts
    fixed, _ = _repair_tel_hrefs('<a href="tel:+15615597663">x</a><a href="tel:305-MIA-ROOF">y</a>')
    assert 'tel:5615597663' in fixed and 'tel:3056427663' in fixed
    assert "no_dead_anchors" not in _keys_failing(content=_GOOD + fixed)


def test_sanitizer_keeps_tel_but_still_blocks_script_schemes():
    """The sanitizer runs inside _markdown_to_html, and tel: was missing from its allow-list — so
    every click-to-call link was PUBLISHED as a bare <a>. That was ours, not WordPress's.
    tel: is safe for the same reason mailto: is: it hands off to an external handler."""
    from jobs.article_job import _markdown_to_html, sanitize_html
    assert 'href="tel:5615597663"' in _markdown_to_html(
        '<p><a href="tel:5615597663">561-559-ROOF</a></p>')
    assert "javascript:" not in sanitize_html('<a href="javascript:alert(1)">x</a>')
    assert "data:" not in sanitize_html('<a href="data:text/html,x">x</a>')


def test_bare_table_without_a_border_is_rejected():
    """"Suggest putting a border around the tables that are in posts." """
    assert "table_bordered" in _keys_failing(content=_GOOD + "<table><tr><td>x</td></tr></table>")
    ok = _GOOD + '<table class="perkins-table" style="border:1px solid #2A3C73"><tr><td>x</td></tr></table>'
    assert "table_bordered" not in _keys_failing(content=ok)


def test_featured_image_is_split_out_of_the_published_body():
    """Wendy, 2026-07-28: "Now that we are using the featured image, there is no need to add the
    image in the content area. That's why it shows twice." The WP featured image is uploaded FROM
    the first content <img>, so the published body must not also carry it."""
    from jobs.article_job import split_featured_image
    body, src = split_featured_image(
        '<img src="https://i.ytimg.com/vi/BnsaVtCb0GU/maxres2.jpg" alt="x" />\n<p>Body.</p>')
    assert src == "https://i.ytimg.com/vi/BnsaVtCb0GU/maxres2.jpg"
    assert "<img" not in body and body == "<p>Body.</p>"
    # No image -> unchanged content and no featured image set (never publish a mutated body).
    same, none_src = split_featured_image("<p>No image here.</p>")
    assert none_src is None and same == "<p>No image here.</p>"
