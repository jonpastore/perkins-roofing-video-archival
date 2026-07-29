"""Curation rules + project-page scoring (pure, no I/O).

The rules here are the ones that keep a crew's internal clip off a public page and stop the
"four images, one alt string" defect the live site already has — so they get real tests, not
smoke tests.
"""
import pytest

from core.portfolio_media import (
    companycam_project_id,
    gallery_html,
    publishable_media,
    score_project,
    validate_selection,
)


def _photos(*ids):
    return [{"companycam_photo_id": i, "url": f"http://cdn/{i}.jpg"} for i in ids]


def _videos(*specs):
    return [{"companycam_video_id": i, "url": f"http://cdn/{i}.m3u8",
             "thumbnail_url": f"http://cdn/{i}.jpg", "internal": internal}
            for i, internal in specs]


# --- project id ------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://app.companycam.com/projects/60249175/photos", "60249175"),
    ("https://app.companycam.com/projects/79260538", "79260538"),
    ("", None),
    (None, None),
    ("https://app.companycam.com/dashboard", None),
])
def test_companycam_project_id_parses_the_recorded_url(url, expected):
    assert companycam_project_id(url) == expected


# --- permission + internal filtering ---------------------------------------

def test_internal_video_is_never_publishable_even_with_permission():
    out = publishable_media(_photos("p1"), _videos(("v_ok", False), ("v_internal", True)),
                            permission_photos=True, permission_video=True)
    assert [v["companycam_video_id"] for v in out["videos"]] == ["v_ok"]


def test_photo_permission_does_not_clear_video():
    out = publishable_media(_photos("p1"), _videos(("v1", False)),
                            permission_photos=True, permission_video=False)
    assert len(out["photos"]) == 1
    assert out["videos"] == [], "video permission is separate from photo permission"


def test_no_permission_means_no_media():
    out = publishable_media(_photos("p1"), _videos(("v1", False)),
                            permission_photos=False, permission_video=False)
    assert out == {"photos": [], "videos": []}


# --- selection validation --------------------------------------------------

def _available():
    return publishable_media(_photos("p1", "p2"), _videos(("v1", False)),
                             permission_photos=True, permission_video=True)


def test_valid_selection_has_no_problems():
    sel = [{"kind": "photo", "id": "p1", "alt": "New tile roof from the street"},
           {"kind": "photo", "id": "p2", "alt": "Ridge detail after install"},
           {"kind": "video", "id": "v1"}]
    assert validate_selection(sel, _available()) == []


def test_selecting_unavailable_media_is_rejected_not_dropped():
    """A silent drop is how an editor thinks they published media that never shipped."""
    problems = validate_selection([{"kind": "photo", "id": "nope", "alt": "x"}], _available())
    assert len(problems) == 1
    assert "not available" in problems[0]


def test_duplicate_alt_text_is_an_error():
    """The live site's nine project pages each have 4 images sharing ONE alt string."""
    sel = [{"kind": "photo", "id": "p1", "alt": "Perkins Roofing project"},
           {"kind": "photo", "id": "p2", "alt": "Perkins Roofing project"}]
    problems = validate_selection(sel, _available())
    assert any("reused across images" in p for p in problems)


def test_missing_alt_text_is_an_error():
    problems = validate_selection([{"kind": "photo", "id": "p1", "alt": "  "}], _available())
    assert any("no alt text" in p for p in problems)


def test_duplicate_selection_is_an_error():
    sel = [{"kind": "photo", "id": "p1", "alt": "a"}, {"kind": "photo", "id": "p1", "alt": "b"}]
    assert any("selected twice" in p for p in validate_selection(sel, _available()))


def test_bad_kind_is_rejected():
    assert any("kind must be" in p
               for p in validate_selection([{"kind": "gif", "id": "p1"}], _available()))


# --- gallery html ----------------------------------------------------------

def test_gallery_html_carries_per_image_alt_and_renders_video():
    media = {"photo:p1": {"url": "http://cdn/p1.jpg"},
             "video:v1": {"url": "http://cdn/v1.m3u8", "thumbnail_url": "http://cdn/v1.jpg"}}
    html = gallery_html([{"kind": "photo", "id": "p1", "alt": "Ridge detail"},
                         {"kind": "video", "id": "v1"}], media)
    assert 'alt="Ridge detail"' in html
    assert "<video" in html and 'poster="http://cdn/v1.jpg"' in html


def test_gallery_html_skips_media_that_is_no_longer_available():
    """Permission revoked after selection: the item is gone from media_by_id, so it must not render."""
    html = gallery_html([{"kind": "photo", "id": "gone", "alt": "x"}], {})
    assert html == ""


# --- scoring ---------------------------------------------------------------

_CLEARED = {"permission_property": True, "permission_photos": True, "permission_video": True}


def test_score_rewards_a_curated_gallery_with_unique_alts():
    sel = [{"kind": "photo", "id": f"p{i}", "alt": f"unique alt {i}"} for i in range(4)]
    result = score_project(title="Sunny Isles Condominium Re-Roof", meta="m" * 130,
                           content_html="<h2>Scope</h2><p>Full tile re-roof.</p>",
                           selections=sel, has_jsonld=True, permissions=_CLEARED)
    by_key = {c["key"]: c for c in result["checks"]}
    assert by_key["gallery_size"]["pass"] is True
    assert by_key["alt_unique"]["pass"] is True
    assert result["pct"] > 0


def test_score_flags_shared_alt_text():
    sel = [{"kind": "photo", "id": f"p{i}", "alt": "same alt"} for i in range(4)]
    result = score_project(title="t" * 40, meta="m" * 130, content_html="<p>x</p>",
                           selections=sel, has_jsonld=True, permissions=_CLEARED)
    by_key = {c["key"]: c for c in result["checks"]}
    assert by_key["gallery_size"]["pass"] is True
    assert by_key["alt_unique"]["pass"] is False, "4 images sharing one alt must not score"


def test_score_checks_service_and_location_links():
    html = ('<p>See our <a href="/services/tile-roofing/">tile roofing</a> and '
            '<a href="/south-florida-service-areas/miami-dade/sunny-isles-beach/">Sunny Isles</a>.</p>')
    result = score_project(title="t" * 40, meta="m" * 130, content_html=html,
                           selections=[], has_jsonld=True, permissions=_CLEARED)
    by_key = {c["key"]: c for c in result["checks"]}
    assert by_key["service_link"]["pass"] is True
    assert by_key["location_link"]["pass"] is True


def test_missing_permission_blocks_regardless_of_score():
    result = score_project(title="t" * 40, meta="m" * 130, content_html="<p>x</p>",
                           selections=[], has_jsonld=True,
                           permissions={"permission_property": False,
                                        "permission_photos": True,
                                        "permission_video": True})
    assert any("name the property" in b for b in result["blocking"])


def test_video_permission_only_blocks_when_a_video_is_selected():
    perms = {"permission_property": True, "permission_photos": True, "permission_video": False}
    photo_only = score_project(title="t" * 40, meta="m" * 130, content_html="<p>x</p>",
                               selections=[{"kind": "photo", "id": "p1", "alt": "a"}],
                               has_jsonld=True, permissions=perms)
    assert photo_only["blocking"] == [], "a photo-only page must not wait on video permission"

    with_video = score_project(title="t" * 40, meta="m" * 130, content_html="<p>x</p>",
                               selections=[{"kind": "video", "id": "v1"}],
                               has_jsonld=True, permissions=perms)
    assert any("use video" in b for b in with_video["blocking"])


def test_score_carries_the_advisory_aio_signals_without_gating():
    result = score_project(title="t" * 40, meta="m" * 130, content_html="<p>x</p>",
                           selections=[], has_jsonld=True, permissions=_CLEARED)
    assert result["aio"], "AIO signals are advisory but must be reported"
    assert all("key" in s and "pass" in s for s in result["aio"])
    # AIO failures never appear in blocking — that list is permissions only.
    assert all("aio" not in b for b in result["blocking"])


def test_selection_without_an_id_is_rejected():
    """A UI bug that drops the id must surface as an error, not a silent no-op item."""
    problems = validate_selection([{"kind": "photo", "alt": "x"}], _available())
    assert any("missing id" in p for p in problems)
