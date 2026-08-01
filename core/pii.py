"""PII detection for anything that becomes public (pure — no I/O).

POLICY (Jon, 2026-07-29): "we need to not disclose PII and I wouldn't make the posts specific
addresses. neighborhood or city in address is fine but we can't be too specific."

So: **city and neighbourhood are allowed; anything that narrows to a property or a person is
not.** That means no street address, no unit/suite, no ZIP, no phone, no email, no GPS pair,
and no customer name.

THIS IS NOT THEORETICAL. Measured against our own mirror on 2026-07-29:

  * 3,684 of 3,684 CompanyCam projects carry `street_address_1` + `postal_code`.
  * 1,611 of 3,653 CompanyCam project NAMES are a customer's name ("Melissa Butterworth").
  * 17 project names embed a street address ("Melissa Naman - 1424 Willow Rd").
  * 1 Knowify scope line reads "pitch pans 10350 W. Bay Harbor Dr." — and scope lines were
    being published verbatim, so that address was one curation away from a public page.

Two different jobs, deliberately separated:

  ``find_pii``  — detects precise, low-false-positive identifiers in free text. Used to BLOCK a
                  publish and to DROP an offending scope line.
  ``person_name_risk`` — a heuristic for "this title is somebody's name", applied only to the
                  short, controlled project title. It never auto-edits: a human renames the
                  project, because "Malooly" could be a family or a building and only a person
                  knows which.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_STREET_SUFFIX = (
    r"St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Blvd|Boulevard|Ct|Court|Way|Ter|Terrace|"
    r"Pl|Place|Cir|Circle|Hwy|Highway|Run|Trail|Trl|Pkwy|Parkway|Loop|Path|Row|Walk"
)

# "1424 Willow Rd", "10350 W. Bay Harbor Dr.", "332 Pine Street"
# A street-name token: a word, or an ordinal like "21st"/"5th" — "13000 NW 21st Avenue" is a
# real address in our data and a letter-anchored pattern silently missed it.
_NAME_TOKEN = r"(?:[A-Za-z][\w'-]*|\d{1,4}(?:st|nd|rd|th)?)"

_STREET_RE = re.compile(
    rf"\b\d{{1,6}}\s+(?:[NSEW]\.?\s+)?{_NAME_TOKEN}(?:\s+{_NAME_TOKEN}){{0,3}}\s+"
    rf"(?:{_STREET_SUFFIX})\b\.?",
    re.I,
)

# A ZIP narrows to a few streets, so it counts as too specific. Guarded against quantities:
# "30000 sq ft" and "$33109" must not read as a postcode.
_ZIP_RE = re.compile(
    r"\b(?:FL|Fla\.?|Florida)[.,\s]+\d{5}(?:-\d{4})?\b",
    re.I,
)

# Unit designators. TWO guards, both learned from running this over all 26,063 real scope
# lines: the keyword needs its own word boundary (without it "ste" matched inside "STEEL" and
# flagged 499 lines — every stainless-steel and standing-seam item in the catalogue), and the
# designator must carry a DIGIT ("Unit 4B", "Suite 200", "#12"), which is what distinguishes an
# address fragment from the word "unit" used as a noun.
_UNIT_RE = re.compile(
    r"\b(?:apt|apartment|unit|suite|ste)\b\.?\s*#?\s*(?=[\w-]*\d)[\w-]{1,6}",
    re.I,
)
_PO_BOX_RE = re.compile(r"\bp\.?\s*o\.?\s*box\s*\d+", re.I)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)")
# CompanyCam stores per-photo coordinates; publishing a pair pins a house to ~0.1 m.
#
# THREE renderings, because only the first was covered and it is the one CompanyCam does NOT use.
# core/photo_privacy.py quotes the real capture stamp verbatim as
# "Sep 1, 2023 at 12:12:36 PM / 25.858694° N 80.120019° W" — the hemisphere form. An editor
# pasting that caption into alt text, or a Knowify deliverable description carrying it, passed
# `no_pii` clean while the criterion advertised "or GPS".
#   1. "25.7617, -80.1918"           signed decimal pair
#   2. "25.858694° N 80.120019° W"   hemisphere-suffixed, degree symbol optional
#   3. "lat 25.7617 lon -80.1918"    labelled pair
_GEO_RE = re.compile(
    r"-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}"
    r"|\d{1,3}\.\d{4,}\s*°?\s*[NS]\s*[,/]?\s*\d{1,3}\.\d{4,}\s*°?\s*[EW]"
    r"|lat(?:itude)?\.?\s*:?\s*-?\d{1,3}\.\d{4,}\D{0,12}?lon(?:g|gitude)?\.?\s*:?\s*-?\d{1,3}\.\d{4,}",
    re.IGNORECASE,
)

# Words that make a name an ORGANISATION rather than a person. A condo/HOA/building name is
# fine to publish — it is the client entity, not an individual.
_ORG_RE = re.compile(
    r"condo|condominium|assoc|association|building|bldg|tower|hoa|club|plaza|center|centre|"
    r"llc|inc\b|corp|company|church|school|hotel|resort|apartments|villas|estates|park|"
    r"office|warehouse|storage|mall|market|restaurant|university|college|hospital|city of|"
    r"county|department|authority|properties|management|realty|residences|lofts|suites",
    re.I,
)

# "Melissa Butterworth", "Jim Malooly", "Sally Brooks", "J. Dasher"
_PERSON_RE = re.compile(r"^[A-Z][a-z]{1,20}(?:\s+[A-Z]\.?)?\s+[A-Z][a-z'’-]{1,20}$")

# Place-type nouns. "Fisher Island" has the exact shape of "First Last", so the second word
# decides: a place noun there means the pair names somewhere, not someone. This cannot be a
# blanket keyword check over the whole title, because "Jim Malooly Delray Beach Roof" contains
# "Beach" and IS a person.
_PLACE_NOUN_RE = re.compile(
    r"^(?:island|isle|beach|key|keys|harbor|harbour|shores?|park|point|springs?|gardens?|"
    r"heights|lakes?|ridge|bay|river|creek|cove|village|town|city|hills?|valley|meadows?|"
    r"pines?|palms?|acres|landing|crossing|square|court|plaza|club)$",
    re.I,
)

# Work nouns. A surname slot filled by one of these means the pair describes a JOB, not a
# person: "Isola Roof" and "Alhambra Coating" both have the shape of "First Last" and were
# false positives even after the city prefix was stripped.
_WORK_NOUN_RE = re.compile(
    r"^(?:roof|roofs|roofing|re-?roof|coating|coatings|work|works|restoration|replacement|"
    r"repair|repairs|install|installation|maintenance|project|sealing|waterproofing|soffit|"
    r"fascia|gutter|gutters|deck|decking|tile|shingle|shingles|metal|flat|silicone|tpo|bur|"
    r"inspection|cleaning|removal|demo|survey|report)$",
    re.I,
)


@dataclass(frozen=True)
class Finding:
    kind: str
    text: str

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return f"{self.kind}: {self.text}"


_DETECTORS = (
    ("street_address", _STREET_RE),
    ("po_box", _PO_BOX_RE),
    ("postal_code", _ZIP_RE),
    ("unit_number", _UNIT_RE),
    ("email", _EMAIL_RE),
    ("phone", _PHONE_RE),
    ("gps_coordinates", _GEO_RE),
)


def find_pii(text: str | None) -> list[Finding]:
    """Every precise identifier in *text*, in detector order.

    Deliberately conservative about what it CLAIMS: only patterns that pin a property or a
    person. City and neighbourhood names are not detected because they are allowed.
    """
    out: list[Finding] = []
    body = text or ""
    for kind, pattern in _DETECTORS:
        for match in pattern.finditer(body):
            out.append(Finding(kind, match.group(0).strip()))
    return out


def has_pii(text: str | None) -> bool:
    return bool(find_pii(text))


def person_name_risk(name: str | None, city: str | None = None) -> bool:
    """True when *name* looks like an individual rather than a property or organisation.

    Pass the project's ``city`` whenever it is known. Titles are conventionally
    "<city> <property> <work>", and a city is very often two capitalised words — "Fort
    Lauderdale Alhambra Coating" and "Miami Isola Roof" both read as "First Last" and were
    false positives until the city prefix was removed first. Using the record's OWN city beats
    guessing from a hardcoded list of place names.

    Applied to the project title only. 44% of CompanyCam project names are customer names, and
    a candidate like "Jim Malooly Delray Beach Roof" carries one into a page title. This is a
    heuristic, so it BLOCKS for a human to rename rather than editing anything itself: "Olsen
    Condo" is a building, "Jim Malooly" is a person, and only a person can tell reliably.
    """
    raw = (name or "").strip()
    place = (city or "").strip()
    if place and raw.lower().startswith(place.lower()):
        raw = raw[len(place):].strip()
    if not raw or _ORG_RE.search(raw):
        return False
    # A digit means the title names a property or a job, not a human — "Fisher Island 7900
    # Flat Roofs", "Building 77".
    if re.search(r"\d", raw):
        return False

    words = raw.split()
    # A leading "First Last" is the risky shape, whether or not descriptive words follow
    # ("Jim Malooly Delray Beach Roof"). The word in the SURNAME slot decides: a place noun
    # means somewhere ("Fisher Island"), a work noun means something ("Isola Roof").
    for span in (len(words), 3, 2):
        if span > len(words):
            continue
        pair = words[:span]
        if not _PERSON_RE.match(" ".join(pair)):
            continue
        surname = pair[-1]
        if _PLACE_NOUN_RE.match(surname) or _WORK_NOUN_RE.match(surname):
            return False
        return True
    return False


def scrub(text: str | None) -> str:
    """Redact every finding in *text*, preserving the surrounding words.

    For prose we would rather keep the sentence than lose it; for a scope LINE the caller drops
    the whole line instead (see core.portfolio_facts) because a half-redacted line reads worse
    than no line.
    """
    body = text or ""
    for _kind, pattern in _DETECTORS:
        body = pattern.sub("[redacted]", body)
    return re.sub(r"\s{2,}", " ", body).strip()
