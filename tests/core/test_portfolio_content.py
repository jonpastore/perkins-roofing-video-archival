"""Project write-up + JSON-LD.

Two rules carry the weight here and both come from expensive mistakes:
  * schema must not duplicate what Rank Math already emits (the 2026-07-22 article fix), and
    VideoObject is only legal for an EMBEDDED player (Wendy, 2026-07-28);
  * nothing may be asserted that the project record does not contain — articles were ~90%
    invented when generation outran its grounding.
"""
from core.portfolio_content import (
    build_meta,
    build_project_jsonld,
    build_write_up,
    location_page_for,
    service_page_for,
)

RECORD = {
    "name": "Sunny Isles Condominium AC Towers Re-Roof",
    "city": "Sunny Isles Beach",
    "section": "commercial",
    "date_start": "20 Feb 2024",
    "date_end": "21 May 2025",
    "notes": "Two towers, occupied throughout.",
}

MEDIA = {
    "photo:p1": {"url": "http://cdn/p1.jpg", "captured_at": "2024-03-01T00:00:00"},
    "photo:p2": {"url": "http://cdn/p2.jpg"},
    "video:v1": {"url": "http://cdn/v1.m3u8", "thumbnail_url": "http://cdn/v1.jpg"},
}


# --- links -----------------------------------------------------------------

def test_service_page_is_derived_from_the_roof_type():
    url, label = service_page_for({"name": "Miami Isola Tile Roof"})
    assert url == "/services/tile-roofing/"
    assert label == "Tile"


def test_location_link_is_omitted_when_the_page_is_not_known_to_exist():
    """A dead internal link is worse than a missing one, so an unverified city gets none."""
    assert location_page_for(RECORD, known_location_slugs=None) is None
    assert location_page_for(RECORD, known_location_slugs=["south-florida-service-areas/miami-dade/aventura"]) is None


def test_location_link_is_emitted_when_the_page_exists():
    url = location_page_for(
        RECORD,
        known_location_slugs=["south-florida-service-areas/miami-dade/sunny-isles-beach"],
    )
    assert url == "/south-florida-service-areas/miami-dade/sunny-isles-beach/"


# --- write-up --------------------------------------------------------------

def test_write_up_opens_with_a_complete_answer_first_sentence():
    body = build_write_up(RECORD)
    first = body[body.index("<p>") + 3: body.index("</p>")]
    assert first.endswith(".")
    assert "Sunny Isles" in first and "Perkins Roofing" in first


def test_write_up_states_only_facts_from_the_record():
    """No invented scope, crew, warranty or outcome — the record has none of those."""
    body = build_write_up(RECORD)
    for invented in ("warranty", "crew of", "square feet", "completed on time", "satisfied"):
        assert invented not in body.lower()
    assert "Two towers, occupied throughout." in body


def test_write_up_omits_dates_it_does_not_have():
    body = build_write_up({"name": "X", "city": "Miami", "section": "commercial"})
    assert "On site" not in body and "Started" not in body


def test_write_up_carries_a_list_for_extraction_and_the_gallery():
    body = build_write_up(RECORD, gallery_html="<div class='project-gallery'>G</div>",
                          photo_count=4, video_count=1)
    assert "<ul>" in body, "AI engines extract lists far more reliably than prose"
    assert "4 site photographs and 1 videos" in body
    assert "project-gallery" in body


def test_meta_lands_in_the_usable_length_band():
    meta = build_meta(RECORD)
    assert 60 <= len(meta) <= 160


# --- schema ----------------------------------------------------------------

def test_jsonld_emits_only_image_and_video_objects():
    """schema_scoped, the article rule: never duplicate Rank Math's Article/Organization/WebPage."""
    sel = [{"kind": "photo", "id": "p1", "alt": "North tower after re-roof"},
           {"kind": "video", "id": "v1"}]
    nodes = build_project_jsonld(RECORD, sel, MEDIA)
    assert {n["@type"] for n in nodes} == {"ImageObject", "VideoObject"}


def test_no_videoobject_when_no_video_is_curated_in():
    """VideoObject is only legal for a video EMBEDDED on the page (Wendy, 2026-07-28)."""
    nodes = build_project_jsonld(RECORD, [{"kind": "photo", "id": "p1", "alt": "a"}], MEDIA)
    assert all(n["@type"] != "VideoObject" for n in nodes)


def test_image_caption_is_the_visible_alt_text():
    """Schema that disagrees with the visible page is a mismatch signal, not a bonus."""
    nodes = build_project_jsonld(RECORD, [{"kind": "photo", "id": "p1", "alt": "Ridge detail"}], MEDIA)
    assert nodes[0]["caption"] == "Ridge detail"
    assert nodes[0]["name"] == "Ridge detail"


def test_first_image_is_the_representative_one():
    sel = [{"kind": "photo", "id": "p1", "alt": "one"}, {"kind": "photo", "id": "p2", "alt": "two"}]
    nodes = build_project_jsonld(RECORD, sel, MEDIA)
    assert nodes[0]["representativeOfPage"] is True
    assert nodes[1]["representativeOfPage"] is False


def test_media_that_is_not_available_is_not_described_in_schema():
    """Permission revoked after selection: it is gone from the page, so it must leave the schema."""
    assert build_project_jsonld(RECORD, [{"kind": "photo", "id": "gone", "alt": "x"}], {}) == []


def test_organization_is_referenced_by_id_not_duplicated():
    nodes = build_project_jsonld(RECORD, [{"kind": "photo", "id": "p1", "alt": "a"}], MEDIA,
                                 organization_id="https://perkinsroofing.net/#organization")
    assert nodes[0]["creator"] == {"@id": "https://perkinsroofing.net/#organization"}
    assert all(n["@type"] != "Organization" for n in nodes)


def test_content_location_matches_the_project_city():
    nodes = build_project_jsonld(RECORD, [{"kind": "video", "id": "v1"}], MEDIA)
    assert nodes[0]["contentLocation"]["name"] == "Sunny Isles Beach, Florida"


# --- the article machinery, reused -----------------------------------------

def test_faq_is_built_only_from_fields_the_record_holds():
    from core.portfolio_content import build_faq

    thin = build_faq({"name": "X"})
    assert thin == [], "no city, no roof type, no dates, no notes => no questions"

    full = build_faq(RECORD, photo_count=4, video_count=1)
    answers = " ".join(p["a"] for p in full)
    assert "Sunny Isles Beach, Florida" in answers
    assert "20 Feb 2024 to 21 May 2025" in answers
    assert "Two towers, occupied throughout." in answers


def test_faq_is_visible_on_the_page_and_in_the_schema():
    """FAQPage schema without the matching visible Q&A is a mismatch, not a bonus."""
    from core.portfolio_content import build_faq

    faq = build_faq(RECORD, photo_count=4)
    body = build_write_up(RECORD, photo_count=4)
    nodes = build_project_jsonld(RECORD, [], MEDIA, faq=faq)

    assert faq[0]["q"] in body
    types = [n["@type"] for n in nodes]
    assert types == ["FAQPage"]
    assert len(nodes[0]["mainEntity"]) == len(faq)


def test_write_up_carries_the_in_content_toc_our_criteria_require():
    body = build_write_up(RECORD, photo_count=4)
    assert body.count('href="#') >= 3


def test_meta_reaches_the_length_band_without_inventing_project_detail():
    meta = build_meta({"name": "Isola Roof", "city": "Miami", "section": "commercial"})
    assert 120 <= len(meta) <= 160
    for invented in ("warranty", "on time", "satisfied", "square"):
        assert invented not in meta.lower()


def test_self_hosted_video_counts_as_an_embed():
    """CompanyCam video is a <video> element, not a YouTube iframe — it still PLAYS on the
    page, which is the distinction Google draws when granting VideoObject."""
    from core.seo import _has_video_embed

    assert _has_video_embed('<video controls src="http://cdn/v.m3u8"></video>') is True
    assert _has_video_embed('<a href="http://cdn/v.m3u8">watch</a>') is False, "a link is not an embed"


def test_a_start_date_with_no_end_date_reads_as_started():
    from core.portfolio_content import build_faq

    rec = {**RECORD, "date_end": ""}
    body = build_write_up(rec)
    assert "Started" in body and "On site" not in body
    assert any("When did work begin" in p["q"] for p in build_faq(rec))


def test_render_faq_of_nothing_is_empty():
    from core.portfolio_content import render_faq

    assert render_faq([]) == ""


def test_short_name_meta_is_padded_into_the_band():
    """Even a one-word project name clears the 120-char floor Google rewrites below."""
    meta = build_meta({"name": "Roof", "city": "Miami", "section": "residential"})
    assert 120 <= len(meta) <= 160


def test_location_link_is_rendered_in_the_body_when_the_page_exists():
    body = build_write_up(
        RECORD,
        known_location_slugs=["south-florida-service-areas/miami-dade/sunny-isles-beach"],
    )
    assert 'href="/south-florida-service-areas/miami-dade/sunny-isles-beach/"' in body
    assert "roofing in Sunny Isles Beach" in body


def test_video_upload_date_comes_from_the_capture_timestamp():
    media = {"video:v1": {"url": "http://cdn/v.m3u8", "thumbnail_url": "http://cdn/v.jpg",
                          "captured_at": "2024-05-02T10:00:00"}}
    node = build_project_jsonld(RECORD, [{"kind": "video", "id": "v1"}], media)[0]
    assert node["uploadDate"] == "2024-05-02T10:00:00"
