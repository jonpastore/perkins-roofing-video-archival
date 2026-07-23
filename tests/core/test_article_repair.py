"""Tests for core/article_repair.py — 100% coverage target.

Pure module: no DB, no network. Fixtures reproduce the 2026-07-22 audit's rot
classes (corrupted YouTube ids, invented images, dead relative links, dead
staging hosts, stale VideoObject jsonld, missing service links) so a future
generation run can't silently reintroduce any of them.
"""
from __future__ import annotations

from core.article_repair import (
    RepairResult,
    _append_service_links,
    _embedded_known_ids,
    _fuzzy_match_id,
    _image_allowed,
    _iso_duration,
    _repair_dead_hosts,
    _repair_images,
    _repair_relative_links,
    _repair_toc_h2_only,
    _repair_video_ids,
    _strip_video_id_refs,
    _sync_video_jsonld,
    _thumb_img_tag,
    _tidy_related_links,
    _title_case,
    _wp_field_issues,
    repair_article,
)

KNOWN = {"gtbkLgg_G9o", "E_X65i3xQO0", "tpxdWz4Oqnw", "SxdHJZbyO78"}


# ---------------------------------------------------------------------------
# small pure helpers
# ---------------------------------------------------------------------------

def test_title_case():
    assert _title_case("roof estimate miami") == "Roof Estimate Miami"


def test_iso_duration_valid():
    assert _iso_duration(150) == "PT2M30S"


def test_iso_duration_invalid():
    assert _iso_duration(None) == "PT0S"
    assert _iso_duration("not-a-number") == "PT0S"


def test_fuzzy_match_id_found():
    # exact scenario from the 2026-07-22 audit: 1-char typo of a real id
    assert _fuzzy_match_id("gtbkLggG9o", KNOWN) == "gtbkLgg_G9o"


def test_fuzzy_match_id_not_found():
    assert _fuzzy_match_id("completely-different", KNOWN) is None


def test_thumb_img_tag_with_keyword():
    tag = _thumb_img_tag("gtbkLgg_G9o", "roof estimate")
    assert 'src="https://img.youtube.com/vi/gtbkLgg_G9o/hqdefault.jpg"' in tag
    assert 'alt="Roof Estimate — Perkins Roofing"' in tag


def test_thumb_img_tag_no_keyword():
    tag = _thumb_img_tag("gtbkLgg_G9o", "")
    assert 'alt="Perkins Roofing — Perkins Roofing"' in tag


# ---------------------------------------------------------------------------
# a. video ids
# ---------------------------------------------------------------------------

def test_repair_video_ids_known_id_unchanged():
    content = '<a href="https://youtu.be/gtbkLgg_G9o">watch</a>'
    out, fixes, issues = _repair_video_ids(content, KNOWN)
    assert out == content
    assert fixes == []
    assert issues == []


def test_repair_video_ids_fuzzy_corrects_everywhere():
    content = (
        '<a href="https://youtu.be/gtbkLggG9o">watch</a> '
        '<img src="https://img.youtube.com/vi/gtbkLggG9o/hqdefault.jpg">'
    )
    out, fixes, issues = _repair_video_ids(content, KNOWN)
    assert "gtbkLggG9o" not in out
    assert out.count("gtbkLgg_G9o") == 2
    assert len(fixes) == 1
    assert issues == []


def test_strip_video_id_refs_unwraps_link():
    content = '<p>See <a href="https://youtu.be/badbadbadid">this technique</a> here.</p>'
    out = _strip_video_id_refs(content, "badbadbadid")
    assert "<a " not in out
    assert "this technique" in out


def test_strip_video_id_refs_drops_wrapper_div():
    content = (
        '<div class="video-embed" style="x">'
        '<iframe src="https://www.youtube.com/embed/badbadbadid" title="t"></iframe>'
        "</div>"
    )
    out = _strip_video_id_refs(content, "badbadbadid")
    assert out == ""


def test_strip_video_id_refs_drops_bare_iframe():
    content = '<iframe src="https://www.youtube.com/embed/badbadbadid"></iframe>tail'
    out = _strip_video_id_refs(content, "badbadbadid")
    assert out == "tail"


def test_strip_video_id_refs_drops_img():
    content = '<img src="https://img.youtube.com/vi/badbadbadid/hqdefault.jpg" alt="x">'
    out = _strip_video_id_refs(content, "badbadbadid")
    assert out == ""


def test_strip_video_id_refs_drops_bare_url_line():
    content = "intro\nhttps://www.youtube.com/watch?v=badbadbadid\noutro"
    out = _strip_video_id_refs(content, "badbadbadid")
    assert "badbadbadid" not in out
    assert "intro" in out and "outro" in out


def test_repair_video_ids_strip_when_no_fuzzy_match():
    content = '<a href="https://youtu.be/example">watch this</a>'
    out, fixes, issues = _repair_video_ids(content, KNOWN)
    assert "example" not in out
    assert "watch this" in out
    assert len(fixes) == 1
    assert issues[0]["severity"] == "warn"
    assert issues[0]["name"] == "unknown_video_id"


def test_embedded_known_ids_dedup_order():
    content = (
        '<a href="https://youtu.be/gtbkLgg_G9o">a</a>'
        '<a href="https://youtu.be/E_X65i3xQO0">b</a>'
        '<a href="https://youtu.be/gtbkLgg_G9o">c</a>'
    )
    assert _embedded_known_ids(content, KNOWN) == ["gtbkLgg_G9o", "E_X65i3xQO0"]


# ---------------------------------------------------------------------------
# b. images
# ---------------------------------------------------------------------------

def test_image_allowed_known_youtube_thumb():
    assert _image_allowed("https://img.youtube.com/vi/gtbkLgg_G9o/hqdefault.jpg", KNOWN)


def test_image_allowed_unknown_youtube_thumb():
    assert not _image_allowed("https://i.ytimg.com/vi/unknownid12/hqdefault.jpg", KNOWN)


def test_image_allowed_wp_content():
    assert _image_allowed("/wp-content/uploads/2026/07/roof.jpg", KNOWN)


def test_image_allowed_other_disallowed():
    assert not _image_allowed("https://example.com/fake.jpg", KNOWN)
    assert not _image_allowed("/images/invented.jpg", KNOWN)


def test_repair_images_strips_and_reinserts_real_thumb():
    content = (
        '<img src="/images/invented.jpg" alt="fake">'
        '<p>Body with <a href="https://youtu.be/gtbkLgg_G9o">the video</a>.</p>'
    )
    out, fixes = _repair_images(content, KNOWN, "roof estimate")
    assert "/images/invented.jpg" not in out
    assert "img.youtube.com/vi/gtbkLgg_G9o" in out
    assert len(fixes) == 2  # strip + reinsert


def test_repair_images_strips_leaves_imageless_when_no_known_video():
    content = '<img src="https://example.com/fake.jpg" alt="fake"><p>no video here</p>'
    out, fixes = _repair_images(content, KNOWN, "roof estimate")
    assert "<img" not in out
    assert len(fixes) == 1


def test_repair_images_noop_when_clean():
    content = '<p>clean body, no images</p>'
    out, fixes = _repair_images(content, KNOWN, "roof estimate")
    assert out == content
    assert fixes == []


def test_repair_images_keeps_a_valid_image_no_reinsert():
    content = (
        '<img src="/images/invented.jpg" alt="fake">'
        '<img src="/wp-content/uploads/real.jpg" alt="real">'
    )
    out, fixes = _repair_images(content, KNOWN, "roof estimate")
    assert "/images/invented.jpg" not in out
    assert "/wp-content/uploads/real.jpg" in out
    assert len(fixes) == 1  # strip only, no reinsert (an image already remains)


# ---------------------------------------------------------------------------
# c. dead relative links
# ---------------------------------------------------------------------------

def test_tidy_related_links_collapses_orphaned_separators():
    content = (
        '<p class="related-links">Related: <a href="/x">X</a> | dropped text | '
        '<a href="/y">Y</a></p>'
    )
    out = _tidy_related_links(content)
    assert "dropped text" not in out
    assert '<a href="/x">X</a>' in out and '<a href="/y">Y</a>' in out


def test_tidy_related_links_drops_empty_block():
    content = '<p class="related-links">Related: only text, no links</p>\nafter'
    out = _tidy_related_links(content)
    assert "related-links" not in out
    assert "after" in out


def test_repair_relative_links_valid_slug_untouched():
    content = '<a href="/roof-repair-services/">repair</a>'
    out, fixes = _repair_relative_links(content, {"roof-repair-services"}, {})
    assert out == content
    assert fixes == []


def test_repair_relative_links_pillar_rewrite():
    content = '<a href="/old-pillar-slug/">the guide</a>'
    out, fixes = _repair_relative_links(
        content, {"real-pillar-slug"}, {"old-pillar-slug": "real-pillar-slug"})
    assert 'href="/real-pillar-slug/"' in out
    assert len(fixes) == 1


def test_repair_relative_links_pillar_rewrite_no_trailing_slash():
    content = '<a href="/old-pillar-slug">the guide</a>'
    out, fixes = _repair_relative_links(
        content, {"real-pillar-slug"}, {"old-pillar-slug": "real-pillar-slug"})
    assert 'href="/real-pillar-slug"' in out
    assert len(fixes) == 1


def test_repair_relative_links_unwraps_dead_link():
    content = '<p>See <a href="/placeholder-x">this cluster article</a> for more.</p>'
    out, fixes = _repair_relative_links(content, {"other-slug"}, {})
    assert "<a " not in out
    assert "this cluster article" in out
    assert len(fixes) == 1


# ---------------------------------------------------------------------------
# d. dead hosts
# ---------------------------------------------------------------------------

def test_repair_dead_hosts_rewrites_path():
    content = '<a href="https://jhk.14f.myftpupload.com/some-real-page/">link</a>'
    out, fixes = _repair_dead_hosts(content)
    assert out == '<a href="/some-real-page/">link</a>'
    assert len(fixes) == 1


def test_repair_dead_hosts_bare_host_defaults_to_root():
    content = '<img src="https://foo.myftpupload.com">'
    out, fixes = _repair_dead_hosts(content)
    assert out == '<img src="/">'
    assert len(fixes) == 1


def test_repair_dead_hosts_noop_when_clean():
    content = '<a href="/some-real-page/">link</a>'
    out, fixes = _repair_dead_hosts(content)
    assert out == content
    assert fixes == []


# ---------------------------------------------------------------------------
# e. VideoObject sync
# ---------------------------------------------------------------------------

VIDEO_META = {
    "gtbkLgg_G9o": {"title": "Roof Estimate Basics", "upload_date": "2026-01-15", "duration": 605},
}


def test_sync_video_jsonld_keeps_faq_builds_video():
    content = '<a href="https://youtu.be/gtbkLgg_G9o">watch</a>'
    faq_node = {"@type": "FAQPage", "mainEntity": []}
    jsonld, fixes, issues = _sync_video_jsonld(content, [faq_node], KNOWN, VIDEO_META, "meta desc")
    assert faq_node in jsonld
    video_nodes = [n for n in jsonld if n["@type"] == "VideoObject"]
    assert len(video_nodes) == 1
    assert video_nodes[0]["contentUrl"] == "https://www.youtube.com/watch?v=gtbkLgg_G9o"
    assert video_nodes[0]["duration"] == "PT10M5S"
    assert len(fixes) == 1
    assert issues == []


def test_sync_video_jsonld_drops_stale_video_not_in_content():
    stale = {
        "@type": "VideoObject",
        "contentUrl": "https://www.youtube.com/watch?v=E_X65i3xQO0",
    }
    jsonld, fixes, issues = _sync_video_jsonld("<p>no video here</p>", [stale], KNOWN, VIDEO_META, "d")
    assert jsonld == []
    assert len(fixes) == 1
    assert issues == []


def test_sync_video_jsonld_unchanged_when_ids_match():
    existing = {
        "@type": "VideoObject",
        "contentUrl": "https://www.youtube.com/watch?v=gtbkLgg_G9o",
    }
    content = '<a href="https://youtu.be/gtbkLgg_G9o">watch</a>'
    jsonld, fixes, issues = _sync_video_jsonld(content, [existing], KNOWN, VIDEO_META, "d")
    assert fixes == []  # old id set == new id set
    assert len(jsonld) == 1


def test_sync_video_jsonld_missing_meta_reports_issue():
    content = '<a href="https://youtu.be/E_X65i3xQO0">watch</a>'
    jsonld, fixes, issues = _sync_video_jsonld(content, [], KNOWN, VIDEO_META, "d")
    assert jsonld == []
    assert len(issues) == 1
    assert issues[0]["name"] == "video_metadata_missing"
    assert issues[0]["severity"] == "warn"


# ---------------------------------------------------------------------------
# f. service links
# ---------------------------------------------------------------------------

def test_append_service_links_appends_match():
    content = "<p>Talk to us about a roof repair for your leaking roof.</p>"
    out, fixes, issues = _append_service_links(content, "roof repair")
    assert "perkinsroofing.net/roof-repair-services/" in out
    assert len(fixes) == 1
    assert issues == []


def test_append_service_links_noop_when_already_present():
    content = '<p>See our <a href="https://perkinsroofing.net/roof-repair-services/">services</a>.</p>'
    out, fixes, issues = _append_service_links(content, "roof repair")
    assert out == content
    assert fixes == []
    assert issues == []


def test_append_service_links_reports_no_match():
    content = "<p>General content with no service keywords at all.</p>"
    out, fixes, issues = _append_service_links(content, "")
    assert out == content
    assert fixes == []
    assert len(issues) == 1
    assert issues[0]["name"] == "service_links_no_match"
    assert issues[0]["severity"] == "info"


# ---------------------------------------------------------------------------
# g. TOC must stay H2-only
# ---------------------------------------------------------------------------

def test_repair_toc_h2_only_noop_when_no_h3_ids():
    content = '<div class="toc"><ul><li><a href="#slug">Slug</a></li></ul></div><h2 id="slug">Slug</h2>'
    out, fixes = _repair_toc_h2_only(content)
    assert out == content
    assert fixes == []


def test_repair_toc_h2_only_drops_h3_entry():
    content = (
        '<div class="toc"><p><strong>In This Article</strong></p><ul>'
        '<li><a href="#good">Good</a></li>'
        '<li><a href="#sub">Sub</a></li>'
        "</ul></div>"
        '<h2 id="good">Good</h2><h3 id="sub">Sub</h3>'
    )
    out, fixes = _repair_toc_h2_only(content)
    assert '<a href="#sub">' not in out
    assert '<a href="#good">' in out
    assert len(fixes) == 1


def test_repair_toc_h2_only_drops_emptied_toc_block():
    content = (
        '<div class="toc"><p><strong>In This Article</strong></p><ul>'
        '<li><a href="#sub">Sub</a></li>'
        "</ul></div>"
        '<h3 id="sub">Sub</h3>'
    )
    out, fixes = _repair_toc_h2_only(content)
    assert "toc" not in out
    assert len(fixes) == 1


# ---------------------------------------------------------------------------
# WP-side (publisher) fields — reporting only, never a fix
# ---------------------------------------------------------------------------

def test_wp_field_issues_unknown_emits_nothing():
    assert _wp_field_issues(None, None) == []


def test_wp_field_issues_default_category_warns():
    issues = _wp_field_issues(1, None)
    assert len(issues) == 1
    assert issues[0]["name"] == "wp_default_category"
    assert issues[0]["severity"] == "warn"


def test_wp_field_issues_real_category_ok():
    assert _wp_field_issues(42, None) == []


def test_wp_field_issues_missing_featured_image_warns():
    issues = _wp_field_issues(None, False)
    assert len(issues) == 1
    assert issues[0]["name"] == "wp_missing_featured_image"


def test_wp_field_issues_has_featured_image_ok():
    assert _wp_field_issues(None, True) == []


def test_repair_article_passes_through_wp_field_issues():
    result = _repair("<p>clean</p>", category_id=1, has_featured_image=False)
    names = {i["name"] for i in result.issues}
    assert {"wp_default_category", "wp_missing_featured_image"} <= names


# ---------------------------------------------------------------------------
# orchestrator: idempotency + combined end-to-end
# ---------------------------------------------------------------------------

def _repair(content_md, jsonld=None, **overrides):
    kwargs = {
        "known_video_ids": KNOWN,
        "video_meta": VIDEO_META,
        "valid_slugs": {"roof-repair-services"},
        "pillar_map": {},
        "keyword": "roof estimate",
        "meta_description": "Perkins Roofing estimate guide.",
    }
    kwargs.update(overrides)
    return repair_article(content_md, jsonld or [], **kwargs)


def test_repair_article_is_idempotent():
    content = (
        '<img src="/images/foo.jpg" alt="bad">'
        '<p>Article about <a href="https://youtu.be/gtbkLggG9o">roof estimate example</a> '
        "with a link to example.com and a video id example embedded, plus a dead "
        '<a href="/placeholder-x">cluster link</a> and a staging host '
        '<a href="https://jhk.14f.myftpupload.com/roof-repair-services/">repair page</a>. '
        "This covers roof repair too.</p>"
    )
    once = _repair(content, valid_slugs={"real-pillar", "roof-repair-services"},
                    pillar_map={"placeholder-x": "real-pillar"})
    twice = repair_article(
        once.content_md, once.jsonld,
        known_video_ids=KNOWN, video_meta=VIDEO_META,
        valid_slugs={"real-pillar", "roof-repair-services"},
        pillar_map={"placeholder-x": "real-pillar"},
        keyword="roof estimate", meta_description="Perkins Roofing estimate guide.")
    assert once.content_md == twice.content_md
    assert once.jsonld == twice.jsonld


def test_repair_article_combined_end_to_end_fixture():
    """Reproduces the 2026-07-22 audit's rot classes in one article."""
    content = (
        '<img src="/images/foo.jpg" alt="invented">'
        '<img src="https://example.com/stock.jpg" alt="stock">'
        "<h2>Roof Estimate Basics</h2>"
        '<p>Watch <a href="https://youtu.be/gtbkLggG9o">this walkthrough</a> '
        '(a typo of a real id), and this one is unrecoverable: '
        '<a href="https://youtu.be/example">bad clip</a>.</p>'
        '<p>See also our <a href="/placeholder-x">deep dive</a> and this staging '
        'link: <a href="https://jhk.14f.myftpupload.com/roof-repair-services/">repair</a>.</p>'
        "<p>This article is about a roof estimate and roof repair costs.</p>"
    )
    result = _repair(
        content,
        jsonld=[{"@type": "FAQPage", "mainEntity": []}],
        valid_slugs={"real-pillar-guide", "roof-repair-services"},
        pillar_map={"placeholder-x": "real-pillar-guide"},
    )

    # video id: fuzzy-corrected, unrecoverable one stripped (text kept)
    assert "gtbkLgg_G9o" in result.content_md
    assert "gtbkLggG9o" not in result.content_md
    assert "bad clip" in result.content_md and "youtu.be/example" not in result.content_md

    # images: both invented ones gone, real thumbnail re-added
    assert "/images/foo.jpg" not in result.content_md
    assert "example.com/stock.jpg" not in result.content_md
    assert "img.youtube.com/vi/gtbkLgg_G9o" in result.content_md

    # dead link rewritten to the pillar's real slug
    assert 'href="/real-pillar-guide"' in result.content_md
    assert "/placeholder-x" not in result.content_md

    # staging host rewritten to a relative path
    assert "myftpupload.com" not in result.content_md
    assert 'href="/roof-repair-services/"' in result.content_md

    # VideoObject rebuilt for the corrected id; FAQPage untouched
    types = [n["@type"] for n in result.jsonld]
    assert types.count("FAQPage") == 1
    assert types.count("VideoObject") == 1
    video = next(n for n in result.jsonld if n["@type"] == "VideoObject")
    assert "gtbkLgg_G9o" in video["contentUrl"]

    # service link appended (article mentions "roof repair")
    assert "perkinsroofing.net/roof-repair-services/" in result.content_md

    assert isinstance(result, RepairResult)
    assert result.fixes  # something was recorded
