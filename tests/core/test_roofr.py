"""core.roofr — reading a Roofr measurement report.

The text fixtures below are the real extracted layout from Tim's corpus
(~/perkins-corpus/roofr-attachments), trimmed to the lines the parser reads. Keeping them as
TEXT rather than PDFs means these run anywhere; the PDF half is pypdf's job, not ours.
"""
import pytest

from core.roofr import is_roofr_report, parse_feet, parse_report

# 10456 159th Court North, Jupiter — verified field-by-field against the seeded `measurements`
# row for the same home: 7 of 8 values match exactly. (The 8th is total_sq, where the stored row
# carries a human's 48.0 against the report's own 47.3 — the parser reports what the PDF says.)
REPORT = """
Area measurement report
Prepared by Perkins Roofing Corp.
Total roof area: 4730 sqft Predominant pitch: 6/12
Pitched roof area: 4715 sqft Predominant pitch area: 4691 sqft
Flat roof area: 15 sqft Unspecified pitch area: 24 sqft
Two story area: 0 sqft
Hips: 134ft 10in
Ridges: 112ft 6in
Valleys: 153ft 9in
Rakes: 130ft 2in
Eaves: 231ft 11in
Wall flashing: 59ft 6in
25 facets
"""


def test_reads_every_field_the_measurement_table_holds():
    r = parse_report(REPORT)
    assert r["total_sq"] == 47.3
    assert r["pitched_sq"] == 47.15
    assert r["flat_sq"] == 0.15
    assert r["pitch_primary"] == 6.0
    assert r["hips_lf"] == 134.83
    assert r["ridges_lf"] == 112.5
    assert r["valleys_lf"] == 153.75
    assert r["rakes_lf"] == 130.17
    assert r["eaves_lf"] == 231.92
    assert r["wall_flashings_lf"] == 59.5
    assert r["facets"] == 25.0


def test_pitched_plus_flat_reconciles_to_the_total():
    """The split is priced by two different calculators, so it has to add up."""
    r = parse_report(REPORT)
    assert round(r["pitched_sq"] + r["flat_sq"], 2) == r["total_sq"]


def test_a_flat_section_is_not_swallowed_into_the_pitched_area():
    """A real 4.22-square flat section (12905 175th Rd) priced as pitched is a wrong quote."""
    r = parse_report(REPORT.replace("Pitched roof area: 4715 sqft", "Pitched roof area: 2774 sqft")
                           .replace("Flat roof area: 15 sqft", "Flat roof area: 422 sqft"))
    assert r["pitched_sq"] == 27.74
    assert r["flat_sq"] == 4.22


def test_thousands_separators_parse():
    r = parse_report("Total roof area: 12,480 sqft")
    assert r["total_sq"] == 124.8


def test_missing_fields_are_none_not_zero():
    """A missing measurement and a measured zero are different facts. 0 ft of valleys is a simple
    roof; an unparsed Valleys line is something a human should look at."""
    r = parse_report("Total roof area: 3000 sqft")
    assert r["total_sq"] == 30.0
    for field in ("hips_lf", "ridges_lf", "valleys_lf", "pitch_primary", "flat_sq"):
        assert r[field] is None, field


def test_a_measured_zero_stays_zero():
    r = parse_report("Total roof area: 3000 sqft\nHips: 0ft 0in\n")
    assert r["hips_lf"] == 0.0


@pytest.mark.parametrize("text,want", [
    ("Hips: 134ft 10in", 134.83),
    ("Hips: 134ft", 134.0),
    ("Hips:134 ft 6 in", 134.5),
    ("Ridges: 0ft 0in", 0.0),
])
def test_feet_and_inches(text, want):
    assert parse_feet(text, text.split(":")[0]) == want


def test_a_pdf_that_is_not_a_roofr_report_is_rejected():
    """Otherwise it parses to a dict of nulls, prefills an empty form, and reads as 'this report
    had no measurements in it'."""
    assert is_roofr_report(REPORT)
    assert not is_roofr_report("INVOICE\nAmount due: $4,730\nThank you for your business")


def test_thousands_separators_parse_in_every_numeric_field():
    """A separator crashed the upload endpoint, not just degraded it.

    "Two story area: 1,250 sq ft" raised ValueError out of an unguarded API handler (500 on any
    two-storey report over 1,000 sq ft), and "Eaves: 1,240ft" silently parsed as None on any roof
    with 1,000+ ft of a run. Roofr prints separators on every numeric field once a roof is big
    enough, so they are handled in one place now.
    """
    r = parse_report(
        "Total roof area: 3,450 sq ft\n"
        "Pitched roof area: 2,200 sq ft\n"
        "Flat roof area: 1,250 sq ft\n"
        "Two story area: 1,250 sq ft\n"
        "Predominant pitch: 5/12\n"
        "Eaves: 1,240ft 6in\n"
    )
    assert r["total_sq"] == 34.5
    assert r["pitched_sq"] == 22.0
    assert r["flat_sq"] == 12.5
    assert r["two_story_sq"] == 12.5
    assert r["eaves_lf"] == 1240.5
