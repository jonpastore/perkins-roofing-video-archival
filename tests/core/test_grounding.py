"""Behavioral validation for the deterministic grounding guard (R1).

Every case here is drawn from a real false positive or real transcript line found while
piloting the grounding rework — this guard's own bugs looked exactly like hallucinations,
which is the failure mode it exists to prevent.
"""
from core.grounding import candidate_terms, unsourced_terms

# Tim's real words, from video WK6ufUjnicc.
TIM = ("Recourse polyflash 1C from Polyblast. So that's what that looks like, and that's what "
       "we're doing on all of our L flashings when we leave. You cut the stucco and put the "
       "wall flashing into the actual concrete block and on the roof deck.")


def test_flags_a_product_name_tim_never_says():
    art = "<p>We recommend the SuperFlash 9000 membrane for this detail.</p>"
    assert "SuperFlash 9000" in unsourced_terms(art, TIM)


def test_does_not_flag_a_product_tim_actually_names():
    art = "<p>Crews use polyflash 1C from Polyblast on these details.</p>"
    out = unsourced_terms(art, TIM)
    assert not any("polyblast" in t.lower() for t in out)


def test_hyphenation_is_not_a_hallucination():
    # Tim says "L flashings"; the writer types "L-flashing". Deleting the hyphen welded this
    # into "lflashing" and reported it as fabricated. Punctuation must fold to a space.
    art = "<p>Install the L-flashing against the wall.</p>"
    assert unsourced_terms(art, TIM) == []


def test_heading_does_not_bleed_into_the_next_paragraph():
    # Collapsing block tags to a space produced cross-boundary phrases like "Materials Proper"
    # and reported them as invented terms.
    art = "<h2>Key Materials Used</h2><p>Proper installation matters on every roof deck.</p>"
    assert not any("Materials Proper" in t for t in candidate_terms(art))


def test_focus_keyword_is_not_a_claim_about_the_world():
    art = "<p>This is our Hurricane Season Roofing Preparedness checklist.</p>"
    out = unsourced_terms(art, TIM, ignore="hurricane season roofing preparedness")
    assert not any("Preparedness" in t for t in out)


def test_sentence_initial_capitals_are_not_proper_nouns():
    art = "<p>Flashing protects the wall.</p><p>Stucco must be cut back.</p>"
    assert unsourced_terms(art, TIM) == []


def test_component_words_present_in_tim_are_accepted():
    # Tim says "wall flashing" and "roof deck"; a section titled "Wall Flashing Roof Deck
    # Detail" recombines his own words and is not an invention.
    art = "<p>See the Wall Flashing Roof Deck detail.</p>"
    assert unsourced_terms(art, TIM) == []


def test_no_transcript_means_no_claims_of_fabrication():
    # An empty evidence base cannot prove anything is invented; saying otherwise would flag a
    # whole article every time retrieval fails.
    art = "<p>We recommend the SuperFlash 9000 membrane.</p>"
    assert unsourced_terms(art, "") == []


def test_urls_are_not_scanned_for_brands():
    art = '<p>Watch <a href="https://youtu.be/AbcXyz123">the SuperFlash 9000 clip</a>.</p>'
    out = unsourced_terms(art, TIM)
    assert not any("AbcXyz" in t for t in out)
