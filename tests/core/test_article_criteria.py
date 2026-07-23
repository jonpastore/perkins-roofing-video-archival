"""core.article_criteria — the authoritative Wendy compliance checklist."""

from core.article_criteria import check_compliance, failing, is_compliant

VID = "BnsaVtCb0GU"  # a real 11-char id we mark as known/grounded
KNOWN = {VID}

# A fully-compliant cluster article: 3 sections + anchor TOC, curated (non-title-card)
# image, embedded known video, service link, subscribe CTA, pillar link, FAQ handled below.
_GOOD = (
    '<p>Metal roof cost in South Florida runs $12,000–$30,000 installed.</p>'
    '<div class="toc"><p><strong>In This Article</strong></p><ul>'
    '<li><a href="#a">A</a></li><li><a href="#b">B</a></li><li><a href="#c">C</a></li></ul></div>'
    '<h2 id="a">Cost factors</h2><p>Metal roof cost depends on square footage.</p>'
    '<h2 id="b">Materials</h2><p>Aluminum and steel differ in metal roof cost.</p>'
    '<h2 id="c">Warranty</h2><p>Metal roof cost includes warranty coverage.</p>'
    f'<img src="https://i.ytimg.com/vi/{VID}/maxres2.jpg" alt="Metal Roof Cost — Perkins Roofing" />'
    f'<div class="video-embed"><iframe src="https://www.youtube.com/embed/{VID}"></iframe></div>'
    '<p class="related-links">Related: '
    '<a href="https://perkinsroofing.net/metal-roofing-guide">Metal Roofing Guide</a> | '
    '<a href="https://perkinsroofing.net/metal-roofing-company/">metal roofing services</a></p>'
    '<p>Subscribe to our YouTube channel for more! '
    '<a href="https://youtube.com/@perkinsroofingcorp">@perkinsroofingcorp</a></p>'
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
        '<a href="https://youtube.com/@perkinsroofingcorp">@perkinsroofingcorp</a>', "")
    assert "subscribe_cta" in _keys_failing(content=bad)


def test_unknown_video_id_is_caught():
    assert "valid_video_ids" in _keys_failing(known_video_ids=set())


def test_dead_staging_host_is_caught():
    bad = _GOOD + '<a href="https://1228404.us6.myftpupload.com/x">dead</a>'
    assert "no_dead_hosts" in _keys_failing(content=bad)


def test_cluster_missing_pillar_link_is_caught():
    bad = _GOOD.replace("https://perkinsroofing.net/metal-roofing-guide", "https://perkinsroofing.net/other")
    assert "pillar_link" in _keys_failing(content=bad)
