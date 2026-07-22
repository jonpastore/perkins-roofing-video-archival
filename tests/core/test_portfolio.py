"""Unit tests for the pure Avada Portfolio mapping (no I/O)."""
from core.portfolio import (
    QUESTIONNAIRE_FIELDS,
    infer_property_type,
    infer_roof_type,
    map_to_post,
    map_to_questionnaire,
    needs_human,
)


def test_infer_property_type_from_knowify_contract_type_and_keywords():
    assert infer_property_type("ResidentialJob") == "Residential"
    assert infer_property_type("CommercialJob") == "Commercial"
    assert infer_property_type("IN PROGRESS: 50,000 SF Warehouse Polyglass Restoration") == "Warehouse"
    assert infer_property_type(None, "unrelated text") is None


def test_infer_roof_type_prefers_specific_over_generic():
    assert infer_roof_type("Fisher Island High-Rise Barrel Tile Re-Roof") == "Clay Barrel Tile"
    assert infer_roof_type("Standing Seam Roof Installation Pt 4") == "Standing Seam Metal"
    assert infer_roof_type("Polyglass Silicone Restoration") == "Polyglass Silicone Restoration"


def test_infer_roof_type_checks_multiple_texts_and_falls_back_none():
    assert infer_roof_type(None, "TPO Roof in Fort Lauderdale") == "TPO"
    assert infer_roof_type("no roofing keywords here") is None


def test_map_to_questionnaire_prefills_data_fields_only():
    record = {
        "name": "7900 Flat Roofs",
        "city": "Fisher Island",
        "companycam_url": "https://app.companycam.com/projects/60249175/photos",
        "youtube_url": "https://www.youtube.com/watch?v=bPyTl6vIjvk",
        "new_roof_type": "TPO",
    }
    q = map_to_questionnaire(record)
    assert set(q) == set(QUESTIONNAIRE_FIELDS)
    assert q["Project name"] == "7900 Flat Roofs"
    assert q["Project city"] == "Fisher Island"
    assert q["New roof type"] == "TPO"
    assert q["Link to Video on YouTube"] == "https://www.youtube.com/watch?v=bPyTl6vIjvk"
    # human-only fields stay blank
    assert q["Project Manager"] == ""
    assert q["Client feedback"] == ""
    assert q["Warranty provided"] == ""


def test_needs_human_lists_blank_fields():
    record = {"name": "X", "city": "Miami"}
    missing = needs_human(map_to_questionnaire(record))
    assert "Project Manager" in missing
    assert "Project name" not in missing
    assert "Project city" not in missing


def test_map_to_post_category_by_section():
    residential = map_to_post({"name": "SL Construction", "section": "residential", "city": "Boca Raton"},
                              content_html="<p>write-up</p>")
    assert residential["category"] == "Residential"
    assert residential["status"] == "draft"
    assert residential["tags"] == ["Boca Raton"]

    commercial = map_to_post({"name": "Isola Roof", "section": "commercial", "city": "Miami"},
                              content_html="<p>write-up</p>")
    assert commercial["category"] == "Commercial"


def test_map_to_post_skills_from_explicit_or_inferred_roof_type():
    explicit = map_to_post({"name": "X", "new_roof_type": "TPO"}, content_html="")
    assert explicit["skills"] == ["TPO"]

    inferred = map_to_post({"name": "Barrel Tile Re-Roof"}, content_html="")
    assert inferred["skills"] == ["Clay Barrel Tile"]

    none_found = map_to_post({"name": "Misc Items"}, content_html="")
    assert none_found["skills"] == []
