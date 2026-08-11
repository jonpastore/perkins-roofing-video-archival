"""Parse a Roofr measurement report into the fields `measurements` stores.

Pure text-in, dict-out — no PDF library, no file I/O, no DB. The caller extracts text (pypdf in
the upload route, the same in scripts/fit_days_from_roofr.py) and this decides what the numbers
mean. That split is what makes the interesting half testable without a PDF fixture.

These regexes were not written here: they come from scripts/fit_days_from_roofr.py, where they
had already been run against Tim's 29-home Roofr corpus. Moving them into core rather than
writing a second parser keeps one definition of "what a Roofr report says" — two would drift, and
the estimating side would be the one that drifted silently.

Everything absent comes back as None, never 0.0. A missing measurement and a measured zero are
different facts: 0 ft of valleys is a simple roof, an unparsed Valleys line is something a human
should look at. (The fitting script coerces its own Nones to 0.0 for the regression, where a
missing feature genuinely is a zero term.)
"""
from __future__ import annotations

import re
from typing import Any

#: Linear-feet features, keyed by the label Roofr prints, mapped to the Measurement column.
_LF_FIELDS = {
    "Hips": "hips_lf",
    "Ridges": "ridges_lf",
    "Valleys": "valleys_lf",
    "Rakes": "rakes_lf",
    "Eaves": "eaves_lf",
    "Wall flashing": "wall_flashings_lf",
}


#: Roofr prints thousands separators once a roof is big enough ("1,240ft", "1,250 sq ft"), and
#: EVERY numeric field here can carry one. Parsing them in one place is the point: the first cut
#: of this module stripped commas for the area but not for the others, so a two-storey report over
#: 1,000 sq ft raised ValueError straight out of an API handler (500 on upload), and a roof with
#: 1,000+ ft of eaves silently parsed as None.
def _to_float(raw: str | None) -> float | None:
    return None if raw is None else float(raw.replace(",", ""))


def parse_feet(text: str, label: str) -> float | None:
    """'Hips: 134ft 10in' -> 134.83. None when the label is absent."""
    m = re.search(
        rf"{label}:?\s*([\d,]+(?:\.\d+)?)\s*ft(?:\s*([\d,]+(?:\.\d+)?)\s*in)?", text, re.I)
    if not m:
        return None
    feet = _to_float(m.group(1))
    if m.group(2):
        feet += _to_float(m.group(2)) / 12
    return round(feet, 2)


def _num(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text, re.I)
    return _to_float(m.group(1)) if m else None


def parse_report(text: str) -> dict[str, Any]:
    """Return Measurement-shaped fields plus the extras the estimator finds useful.

    Squares, not square feet: `total_sq` is what the estimator prices on, and Roofr reports the
    area in sqft. Converting here means the one place that knows the report's units is the one
    place that reads the report.
    """
    m = re.search(r"Total roof area:?\s*([\d,]+(?:\.\d+)?)\s*sq\s*ft", text, re.I)
    area_sqft = _to_float(m.group(1)) if m else None

    def _sqft(label: str) -> float | None:
        m2 = re.search(rf"{label}:?\s*([\d,]+(?:\.\d+)?)\s*sq\s*ft", text, re.I)
        return _to_float(m2.group(1)) if m2 else None

    # Roofr states total = pitched + flat. Capturing only the total left the split ambiguous
    # (migration 0046), and the flat area is priced by a different calculator entirely — a flat
    # section read as pitched is a wrong quote, not a rounding difference.
    pitched_sqft = _sqft("Pitched roof area")
    flat_sqft = _sqft("Flat roof area")

    out: dict[str, Any] = {
        "total_sq": round(area_sqft / 100, 2) if area_sqft is not None else None,
        "pitched_sq": round(pitched_sqft / 100, 2) if pitched_sqft is not None else None,
        "flat_sq": round(flat_sqft / 100, 2) if flat_sqft is not None else None,
        "pitch_primary": _num(text, r"Predominant pitch:?\s*(\d+(?:\.\d+)?)\s*/\s*12"),
        "facets": _num(text, r"(\d+)\s*facets"),
        "area_sqft": area_sqft,
    }
    for label, field in _LF_FIELDS.items():
        out[field] = parse_feet(text, label)

    # Two-story area is a complexity signal Tim prices time on, not a Measurement column — it
    # rides along for the estimator to read rather than being dropped on the floor.
    two_story_sqft = _num(text, r"story area:?\s*([\d,]+)\s*sq\s*ft")
    out["two_story_sq"] = round(two_story_sqft / 100, 2) if two_story_sqft is not None else None
    return out


def is_roofr_report(text: str) -> bool:
    """Cheap sanity check before trusting a parse.

    An upload that is not a Roofr report parses to a dict of Nones, which would silently prefill
    an empty measurement form and look like the PDF simply had no data in it.
    """
    lowered = text.lower()
    return "roofr" in lowered or ("total roof area" in lowered and "predominant pitch" in lowered)
