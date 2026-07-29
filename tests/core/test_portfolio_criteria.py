"""The project publish gate.

The privacy criteria are the reason this module exists, so they are tested from the angle that
actually bites: PII hiding somewhere OTHER than the prose — an image alt, a schema caption, a
scope line — because a check that only reads the body would pass all of those.
"""
from core.portfolio_criteria import (
    blockers,
    check_project,
    failing,
    publishable,
    summary,
)

CLEARED = {"permission_property": True, "permission_photos": True, "permission_video": True}


def _good(**over):
    """A page that passes everything, so each test can break exactly one thing."""
    sel = [{"kind": "photo", "id": f"p{i}", "alt": f"Olsen Condo roof view {i}"} for i in range(4)]
    body = (
        "<p>Perkins Roofing completed a commercial tile re-roof at Olsen Condo in Miami Beach, "
        "Florida.</p><h2>Scope of work</h2><ul><li>13\" Concrete Tile Re-Roof</li></ul>"
        + " ".join(f"<p>Detail sentence number {i} about the roofing work performed.</p>"
                   for i in range(20))
        + "".join(f'<img src="http://cdn/p{i}.jpg" alt="Olsen Condo roof view {i}" />'
                  for i in range(4))
    )
    kwargs = dict(
        title="Miami Beach Olsen Condo", city="Miami Beach",
        meta="Olsen Condo — a commercial roofing project in Miami Beach, Florida.",
        content_html=body, selections=sel, scope_lines=['13" Concrete Tile Re-Roof'],
        jsonld=[{"@type": "FAQPage"}, {"@type": "ImageObject", "caption": "roof view"}],
        permissions=CLEARED,
    )
    kwargs.update(over)
    return check_project(**kwargs)


def _keys(criteria):
    return {c.key for c in criteria}


def test_a_clean_page_is_publishable():
    assert publishable(_good()), [c.key for c in failing(_good())]


# --- privacy: the surfaces a body-only check would miss --------------------

def test_an_address_in_the_body_blocks():
    c = _good(content_html='<p>Re-roof at 1424 Willow Rd, Miami Beach.</p>')
    assert "no_pii" in _keys(blockers(c))


def test_an_address_hidden_in_IMAGE_ALT_blocks():
    """The prose can be clean while the alt text names the street."""
    body = '<p>A tile re-roof in Miami Beach.</p><img src="x" alt="Roof at 1424 Willow Rd" />'
    c = _good(content_html=body)
    assert "no_pii" in _keys(blockers(c))
    assert any("alt text" in e for e in next(x for x in c if x.key == "no_pii").evidence)


def test_a_postcode_hidden_in_SCHEMA_blocks():
    c = _good(jsonld=[{"@type": "ImageObject", "caption": "Roof in Miami Beach, FL 33139"}])
    assert "no_pii" in _keys(blockers(c))
    assert any("schema" in e for e in next(x for x in c if x.key == "no_pii").evidence)


def test_a_unit_number_in_a_SCOPE_LINE_blocks():
    c = _good(scope_lines=["Fascia Board Replacement - UNIT 114"])
    assert "no_pii" in _keys(blockers(c))


def test_a_phone_number_in_the_META_blocks():
    c = _good(meta="Call 561-555-0134 about this Miami Beach re-roof project today.")
    assert "no_pii" in _keys(blockers(c))


def test_a_customer_name_as_the_title_blocks():
    c = _good(title="Jim Malooly Delray Beach Roof", city="Delray Beach")
    assert "title_not_a_person" in _keys(blockers(c))


def test_the_city_in_the_title_is_allowed():
    """Policy: city and neighbourhood are fine — only precision beyond that is not."""
    c = _good(title="Miami Beach Olsen Condo", city="Miami Beach")
    assert "no_pii" not in _keys(failing(c))
    assert "title_not_a_person" not in _keys(failing(c))


# --- permissions ----------------------------------------------------------

def test_missing_property_permission_blocks():
    c = _good(permissions={**CLEARED, "permission_property": False})
    assert "permission_property" in _keys(blockers(c))


def test_video_permission_only_matters_when_a_video_is_selected():
    photos_only = _good(permissions={**CLEARED, "permission_video": False})
    assert "permission_video" not in _keys(failing(photos_only))

    with_video = _good(
        permissions={**CLEARED, "permission_video": False},
        selections=[{"kind": "photo", "id": f"p{i}", "alt": f"view {i}"} for i in range(4)]
                   + [{"kind": "video", "id": "v1"}],
    )
    assert "permission_video" in _keys(blockers(with_video))


# --- quality --------------------------------------------------------------

def test_duplicate_alt_text_fails():
    """The live site's nine project pages each carry four images sharing one alt string."""
    body = "".join('<img src="x" alt="Perkins Roofing project" />' for _ in range(4))
    c = _good(content_html=body)
    assert "alt_unique" in _keys(failing(c))


def test_too_few_images_fails_but_does_not_block_on_privacy():
    c = _good(selections=[{"kind": "photo", "id": "p1", "alt": "one"}])
    assert "gallery_size" in _keys(failing(c))
    assert not blockers(c), "a thin gallery is a quality problem, not a privacy one"


def test_a_thin_body_fails():
    c = _good(content_html="<p>Short.</p>")
    assert "body_length" in _keys(failing(c))


def test_no_scope_fails():
    c = _good(scope_lines=[])
    assert "has_scope" in _keys(failing(c))


def test_missing_schema_is_advisory_only():
    c = _good(jsonld=[])
    assert "schema_present" not in _keys(failing(c))
    assert publishable(c), "schema is a minor — it must not block a correct page"


def test_stray_schema_type_is_advisory():
    c = _good(jsonld=[{"@type": "Article"}])
    assert "schema_scoped" not in _keys(failing(c))


# --- shape ----------------------------------------------------------------

def test_summary_is_serialisable_and_agrees_with_itself():
    s = summary(_good(permissions={**CLEARED, "permission_property": False}))
    assert s["publishable"] is False
    assert any(b["key"] == "permission_property" for b in s["blockers"])
    assert all({"key", "label", "ok", "severity", "detail", "evidence"} <= set(c)
               for c in s["criteria"])
