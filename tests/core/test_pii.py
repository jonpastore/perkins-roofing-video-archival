"""PII detection.

Every positive case below is a REAL string from our own mirror (CompanyCam project names and
addresses, Knowify scope lines), not an invented example — the point is to catch what we
actually hold, and the measured exposure was: 3,684/3,684 projects with a street address,
1,611/3,653 names that are a person's name, 17 names embedding an address, and 1 scope line
reading "pitch pans 10350 W. Bay Harbor Dr.".

Negative cases guard the policy line: city and neighbourhood are ALLOWED, so flagging them
would block every legitimate page.
"""
import pytest

from core.pii import Finding, find_pii, has_pii, person_name_risk, scrub


# --- real strings that MUST be caught --------------------------------------

@pytest.mark.parametrize("text,kind", [
    ("pitch pans 10350 W. Bay Harbor Dr.  MIMIA00775B", "street_address"),
    ("Melissa Naman - 1424 Willow Rd", "street_address"),
    ("7255 Burgess Dr. (Guardian Joseph Bensmihen)", "street_address"),
    ("3400 Burns Rd - Jack", "street_address"),
    ("332 Pine Street", "street_address"),
    ("7792 Fisher Island Drive", "street_address"),
    ("13000 NW 21st Avenue", "street_address"),
    ("Miami Beach, FL 33109", "postal_code"),
    ("P.O. Box 1234", "po_box"),
    ("Unit 4B", "unit_number"),
    ("Suite 200", "unit_number"),
    ("call 561-555-0134", "phone"),
    ("tim@perkinsroofing.net", "email"),
    ("25.7617, -80.1918", "gps_coordinates"),
])
def test_real_identifiers_are_detected(text, kind):
    kinds = [f.kind for f in find_pii(text)]
    assert kind in kinds, f"{text!r} -> {kinds}"


def test_has_pii_is_the_boolean_form():
    assert has_pii("1424 Willow Rd") is True
    assert has_pii("Sunny Isles Beach, Florida") is False
    assert has_pii(None) is False


# --- what the policy ALLOWS ------------------------------------------------

@pytest.mark.parametrize("allowed", [
    "Sunny Isles Beach, Florida",
    "a commercial tile re-roof in Miami Beach",
    "Fisher Island",                      # neighbourhood / island name
    "Palm Beach County",
    "13\" Concrete Tile Re-Roof",         # a measurement, not an address
    "Polyglass 2-Ply Built-Up Roofing System (w/ 2\" Insulation)",
    "30000 sq ft of coverage",            # 5 digits, but a quantity
    "$33109 contract value",              # 5 digits, but money
    "7550 Squares",
    "Cooling Tower 4 - Stockmeier Polyurethane Coating System",
])
def test_city_neighbourhood_and_quantities_are_not_flagged(allowed):
    assert find_pii(allowed) == [], f"{allowed!r} -> {[str(f) for f in find_pii(allowed)]}"


# --- person names in a title ----------------------------------------------

@pytest.mark.parametrize("name", [
    "Jim Malooly Delray Beach Roof",   # our own candidate list
    "Melissa Butterworth",
    "Sally Brooks",
    "Craig Freedman",
    "Ryan Rodriguez",
])
def test_person_names_are_flagged(name):
    assert person_name_risk(name) is True


@pytest.mark.parametrize("name", [
    "Miami Beach Olsen Condo",                          # building
    "Sunny Isles Beach The Pinnacle Condo Association",  # association
    "Fisher Island 7900 Flat Roofs",
    "Miami D&L Office Park",
    "Jupiter River Place Condos",
    "Miami Warehouse Polyglass Silicone Restoration",
    "SL Construction Boca Raton Roof Replacement",       # company
])
def test_organisations_and_properties_are_not_flagged(name):
    assert person_name_risk(name) is False, name


def test_person_name_risk_handles_empty():
    assert person_name_risk("") is False
    assert person_name_risk(None) is False


# --- scrubbing -------------------------------------------------------------

def test_scrub_redacts_and_keeps_the_sentence():
    out = scrub("Re-roof at 1424 Willow Rd, Miami Beach, FL 33109")
    assert "1424 Willow Rd" not in out
    assert "33109" not in out
    assert "Miami Beach" in out, "the allowed city must survive"
    assert "[redacted]" in out


def test_scrub_of_clean_text_is_a_no_op():
    assert scrub("Tile re-roof in Sunny Isles Beach") == "Tile re-roof in Sunny Isles Beach"


def test_finding_is_hashable_and_comparable():
    """Findings get deduped and compared in the criteria layer."""
    assert Finding("email", "a@b.co") == Finding("email", "a@b.co")
    assert len({Finding("email", "a@b.co"), Finding("email", "a@b.co")}) == 1


# --- title heuristic, calibrated against our own 13 titles -----------------
# Each case below is a REAL project title. The first three were false positives until the
# discriminators were added, and they are the reason the rules exist.

@pytest.mark.parametrize("title,city", [
    ("Miami Isola Roof", "Miami"),                       # "Isola Roof" ~ "First Last"
    ("Fort Lauderdale Alhambra Coating", "Fort Lauderdale"),  # city is itself two words
    ("Fisher Island 7900 Flat Roofs", "Fisher Island"),
    ("Fisher Island Building 77 Soffit Work", "Fisher Island"),
    ("Miami Warehouse Polyglass Silicone Restoration", "Miami"),
    ("Miami Beach Florida Tower", "Miami Beach"),
    ("Jupiter River Place Condos", "Jupiter"),
    ("Sunny Isles Beach The Pinnacle Condo Association", "Sunny Isles Beach"),
    ("Miami D&L Office Park", "Miami"),
    ("Miami Beach Olsen Condo", "Miami Beach"),
    ("Abacoa Jupiter Tile Tower Roof", "Jupiter"),
    ("SL Construction Boca Raton Roof Replacement", "Boca Raton"),
])
def test_our_real_titles_are_not_flagged(title, city):
    assert person_name_risk(title, city) is False, title


def test_the_one_real_person_title_is_flagged():
    """Of our 13 candidates exactly one is a customer's name, and it must not publish as-is."""
    assert person_name_risk("Jim Malooly Delray Beach Roof", "Delray Beach") is True


def test_a_work_noun_in_the_surname_slot_is_not_a_person():
    assert person_name_risk("Isola Roof") is False
    assert person_name_risk("Alhambra Coating") is False
    assert person_name_risk("Meridian Inspection") is False


def test_a_place_noun_in_the_surname_slot_is_not_a_person():
    assert person_name_risk("Fisher Island") is False
    assert person_name_risk("Hallandale Beach") is False


def test_a_title_with_a_number_is_a_property_not_a_person():
    assert person_name_risk("Building 77") is False
    assert person_name_risk("Yacht Club TH3") is False


def test_without_a_city_the_check_stays_conservative():
    """No city to strip means "Miami Isola" reads as "First Last" and blocks for human review.

    That is the intended failure direction: a false block costs an editor one glance, a false
    pass publishes a customer's name.
    """
    assert person_name_risk("Miami Isola Roof") is True
    assert person_name_risk("Miami Isola Roof", "Miami") is False, "the city resolves it"


def test_a_title_that_is_only_the_city_is_not_a_person():
    assert person_name_risk("Fort Lauderdale", "Fort Lauderdale") is False


def test_a_two_word_title_skips_the_three_word_span():
    """Guards the span loop: a 2-word name must not index past the end of the list."""
    assert person_name_risk("Craig Freedman") is True
    assert person_name_risk("Olsen Condo") is False


def test_a_middle_initial_is_still_a_person():
    assert person_name_risk("Joseph R Dasher") is True


def test_a_lowercase_two_word_title_is_not_a_person():
    """Reaches the span guard: 2 words, no match at span 2, so span 3 is skipped."""
    assert person_name_risk("tile reroof") is False
