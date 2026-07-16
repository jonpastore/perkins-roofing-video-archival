"""Behavioral validation for typed claim comparison.

The first five tests are the exact cases GPT-5 and Grok independently produced to kill the v1
design ("model quotes its evidence, we verify the quote exists verbatim"). Every one of them
is a REAL span that a string match accepts and that supports nothing. If these ever pass as
SUPPORTED, the design has regressed to shipping verified hallucinations.
"""
from core.claims import (
    Claim,
    ClaimType,
    Verdict,
    compare,
    extract_candidates,
    force_of,
    normalise_unit,
    values_match,
)

# ── the four laundering cases the council found ──────────────────────────────

def test_attribution_inversion_is_not_support():
    """article: "Tim recommends X"   span: "Some contractors recommend X" """
    claim = Claim(type=ClaimType.ATTRIBUTION, sentence="Tim recommends peel and stick.",
                  speaker="Tim", proposition="recommends peel and stick underlayment")
    span = Claim(type=ClaimType.ATTRIBUTION, sentence="some contractors recommend peel and stick",
                 speaker="some contractors", stance="reports_others",
                 proposition="recommends peel and stick underlayment")
    assert compare(claim, span) is Verdict.UNSUPPORTED


def test_force_reversal_is_not_support():
    """article: "lasts 10-15 years"   span: "I've seen some fail in 10 to 15 years"

    Same number, same unit, opposite proposition. A string match sees "10 to 15 years" and
    passes it.
    """
    claim = Claim(type=ClaimType.NUMBER, sentence="Acrylic coating lasts 10-15 years.",
                  subject="acrylic coating", measure="lifespan", value=(10, 15), unit="years")
    span = Claim(type=ClaimType.NUMBER, sentence="I've seen some fail in 10 to 15 years",
                 subject="acrylic coating", measure="time_to_failure", value=(10, 15),
                 unit="years")
    assert compare(claim, span) is Verdict.UNSUPPORTED


def test_modality_inflation_is_caught():
    """article: "never use Y"   span: "I'd almost never use Y in this case"

    The hedge IS the claim. Dropping it is the single most common LLM distortion.
    """
    claim = Claim(type=ClaimType.MODAL, sentence="Never use organic felt.", force="never")
    span = Claim(type=ClaimType.MODAL, sentence="I'd almost never use organic felt here",
                 force=force_of("I'd almost never use organic felt here"))
    assert compare(claim, span) is Verdict.INFLATED


def test_stitched_code_support_is_not_support():
    """article: "ASTM D226 is required in HVHZ"   span: mentions the code, not the requirement."""
    claim = Claim(type=ClaimType.CODE, sentence="ASTM D226 is required in HVHZ zones.",
                  entity="ASTM D226", proposition="astm d226 is required in hvhz zones")
    span = Claim(type=ClaimType.CODE, sentence="that underlayment is an ASTM D226 felt",
                 entity="ASTM D226", proposition="that underlayment is an astm d226 felt")
    assert compare(claim, span) is Verdict.PARTIAL, "right code, different assertion"


def test_a_real_supporting_span_is_supported():
    # The control: the mechanism must still say yes when the source genuinely says it.
    claim = Claim(type=ClaimType.NUMBER, sentence="Caulk fails in 10 to 15 years.",
                  subject="caulk", measure="time_to_failure", value=(10, 15), unit="years")
    span = Claim(type=ClaimType.NUMBER, sentence="that will not happen until 15 10 15 years down the road",
                 subject="caulk", measure="time_to_failure", value=(10, 15), unit="yrs")
    assert compare(claim, span) is Verdict.SUPPORTED


# ── verdicts are not binary ──────────────────────────────────────────────────

def test_wrong_speaker_stance_rejects_rather_than_supports():
    claim = Claim(type=ClaimType.ATTRIBUTION, speaker="Tim", sentence="Tim uses foam.",
                  proposition="uses foam adhesive on tile")
    span = Claim(type=ClaimType.ATTRIBUTION, speaker="Tim", stance="rejects",
                 sentence="I would not use foam adhesive on tile",
                 proposition="uses foam adhesive on tile")
    assert compare(claim, span) is Verdict.CONTRADICTED


def test_a_different_number_contradicts_rather_than_merely_unsupported():
    claim = Claim(type=ClaimType.NUMBER, subject="roof", measure="lifespan",
                  value=(30, 30), unit="years", sentence="A tile roof lasts 30 years.")
    span = Claim(type=ClaimType.NUMBER, subject="roof", measure="lifespan",
                 value=(15, 20), unit="years", sentence="you get 15 to 20 out of it")
    assert compare(claim, span) is Verdict.CONTRADICTED


def test_article_adding_an_unstated_condition_is_partial():
    claim = Claim(type=ClaimType.NUMBER, subject="coating", measure="lifespan",
                  value=(10, 10), unit="years", condition="in south florida",
                  sentence="In South Florida the coating lasts 10 years.")
    span = Claim(type=ClaimType.NUMBER, subject="coating", measure="lifespan",
                 value=(10, 10), unit="years", sentence="the coating gives you ten years")
    assert compare(claim, span) is Verdict.PARTIAL


def test_units_must_match():
    claim = Claim(type=ClaimType.NUMBER, subject="x", measure="thickness",
                  value=(40, 40), unit="mils", sentence="40 mils thick.")
    span = Claim(type=ClaimType.NUMBER, subject="x", measure="thickness",
                 value=(40, 40), unit="inches", sentence="forty inches")
    assert compare(claim, span) is Verdict.UNSUPPORTED


def test_unit_aliases_do_not_cause_false_inventions():
    assert normalise_unit("yrs") == normalise_unit("years") == "years"
    assert normalise_unit("SQ") == "squares"
    assert normalise_unit("$") == "usd"


def test_ranges_match_by_overlap_and_points_land_inside():
    assert values_match((10, 15), (12, 20))
    assert values_match((12, 12), (10, 15))
    assert not values_match((10, 15), (20, 30))
    assert not values_match((10, 15), None)


def test_hedges_are_not_absolutes():
    # "almost never" must NOT read as "never" — that hedge is the whole claim.
    assert force_of("I'd almost never do that") == "sometimes"
    assert force_of("you must always do that") == "always"
    assert force_of("sometimes it works") == "sometimes"


# ── extraction finds candidates, not propositions ────────────────────────────

def test_extraction_finds_the_checkable_things():
    art = ("<h2>Costs</h2><p>A tile roof lasts 10 to 15 years in this climate.</p>"
           "<p>Tim recommends peel and stick underlayment.</p>"
           "<p>ASTM D226 felt is the older standard.</p>"
           "<p>You must always cut the stucco back.</p>")
    got = extract_candidates(art)
    types = {c.type for c in got}
    assert ClaimType.NUMBER in types and ClaimType.ATTRIBUTION in types
    assert ClaimType.CODE in types and ClaimType.MODAL in types
    num = next(c for c in got if c.type is ClaimType.NUMBER)
    assert num.value == (10.0, 15.0) and num.unit == "years"


def test_extraction_does_not_weld_a_heading_onto_the_next_paragraph():
    # The welding bug that produced phantom terms in the predecessor.
    art = "<h2>Key Materials Used</h2><p>Proper installation matters.</p>"
    assert all("Materials Proper" not in c.sentence for c in extract_candidates(art))


def test_prices_are_extracted_as_usd():
    got = extract_candidates("<p>It runs $450 a square.</p>")
    num = next(c for c in got if c.type is ClaimType.NUMBER)
    assert num.value == (450.0, 450.0) and num.unit == "usd"


def test_extraction_is_quiet_on_prose_with_nothing_checkable():
    art = "<p>Roofing protects your home and gives you confidence in a storm.</p>"
    assert extract_candidates(art) == []


def test_attribution_and_modal_claims_have_search_terms():
    """Regression: key_terms() only returned entity/subject/measure.

    Attribution and modal claims carry neither — they have speaker/force + proposition — so
    retrieval got no terms, found nothing, and every claim of those two types came back
    UNVERIFIABLE forever. A verifier that silently cannot check a whole claim class is exactly
    the failure this design exists to avoid.
    """
    attrib = Claim(type=ClaimType.ATTRIBUTION, sentence="Tim recommends foam adhesive.",
                   speaker="Tim", proposition="recommends foam adhesive on tile")
    terms = attrib.key_terms()
    assert terms, "an attribution claim must give retrieval something to look for"
    assert any("adhesive" in t.lower() or "foam" in t.lower() or "tile" in t.lower()
               for t in terms)
    assert not any(t.lower() in ("tim", "recommends") for t in terms), "not the boilerplate"

    modal = Claim(type=ClaimType.MODAL, sentence="You must always cut the stucco back.",
                  force="always", proposition="cut the stucco back")
    assert modal.key_terms(), "a modal claim must give retrieval something to look for"


def test_key_terms_prefers_the_typed_slots_when_present():
    c = Claim(type=ClaimType.CODE, sentence="ASTM D226 is the older standard.",
              entity="ASTM D226", proposition="astm d226 is the older standard")
    assert c.key_terms() == ["ASTM D226"]
