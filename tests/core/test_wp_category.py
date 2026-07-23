"""core.wp_category — article → WP category, never the default bucket."""

from core.wp_category import DEFAULT_CATEGORY, pick_category_name


def test_intent_beats_material_when_both_present():
    # "metal roof repair" has repair intent — Repair wins over Materials (rule order).
    assert pick_category_name("metal roof repair") == "Roof Repair"


def test_material_topics_map_to_materials():
    assert pick_category_name("standing seam metal roofing") == "Roofing Materials"
    assert pick_category_name("concrete tile underlayment") == "Roofing Materials"


def test_specific_intents():
    assert pick_category_name("roof inspection before buying a house") == "Roof Inspections"
    assert pick_category_name("insurance claim denial for old roofs") == "Roof Insurance"
    assert pick_category_name("metal roof cost florida") == "Roofing Costs & Financing"
    assert pick_category_name("commercial tpo flat roof") == "Commercial Roofing"
    assert pick_category_name("hurricane wind mitigation") == "Roofing Solutions"


def test_unmatched_falls_back_to_a_real_category_never_default_bucket():
    got = pick_category_name("perkins roofing company news")
    assert got == DEFAULT_CATEGORY
    assert got and got.lower() not in ("uncategorized", "")
