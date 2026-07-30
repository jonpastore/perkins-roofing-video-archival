"""Scope facts for a project write-up, from the Knowify contract record (pure — no I/O).

WHY THIS EXISTS
The deterministic write-up could only state name/city/dates/notes, so pages ran ~180 words.
The missing detail was already in the mirror: a project's contracts carry DELIVERABLES — the
scope lines Perkins actually sold ("Polyglass MTS Secondary Water Barrier", "Cooling Tower 3 —
Stockmeier Polyurethane Coating System"). Those are verifiable facts about the job, so they can
be published; they are also what makes a project page worth reading.

THREE RULES, each learned the hard way:

1. MATCH ON NAME FIELDS ONLY. The existing matcher ILIKEs the whole JSON payload, which is how
   searching "7900" returned a generic "Tile Re-Roof" project — the digits matched a dollar
   amount. A false-positive match would attach another customer's scope to this page.

2. DROP "(OPTIONAL)" LINES. Knowify prices upgrades as deliverables on the same contract
   ("(OPTIONAL) Upgrade to Clay Verea 'S' Tile"). They are quotes, not installed work — the
   same trap that made 1,395 contracts look like mixed roofs in mixed_roof_sold_analysis.
   Publishing one as if it were installed states something false about the property.

3. NO QUANTITIES. The unit labels are provably unreliable: Olsen's tile re-roof reads
   "7550 Squares" (that would be 755,000 sq ft), and Miramar's "142 Squares" sat against a
   RoofR report of 13,326 sq ft. Descriptions are trustworthy, numbers are not, so only the
   descriptions ship. Prices never ship at all.
"""
from __future__ import annotations

import re
from typing import Iterable

from core.pii import has_pii

# Knowify's placeholder line on every contract — carries no information.
_NOISE_RE = re.compile(r"^\s*default_deliverable\s*$", re.I)

# Priced-but-not-necessarily-sold lines. See rule 2.
_OPTIONAL_RE = re.compile(r"\(optional\)|^\s*optional\b|\bupgrade\b|\bdowngrade\b", re.I)

# COMMERCIAL lines, not scope. Knowify prices discounts, delay costs and change-order
# adjustments as deliverables on the same contract, so the raw list contains things like
# "Group Discount and Cash Discount" and "Material Changes and Additional Costs Due to Delays".
# Those describe the negotiation, not the roof, and a public project page must never carry a
# customer's pricing or dispute history.
_COMMERCIAL_RE = re.compile(
    r"discount|additional cost|\bdelays?\b|change order|\bcredit\b|\btax\b|deposit|"
    r"retainage|allowance|\bprice\b|invoice|escalation|performance bond|error correction|"
    r"since award",
    re.I,
)

# What actually describes the roof. Used to RANK, not to filter: the deliverable list is not
# ordered by importance, so a cap of MAX_SCOPE_LINES applied to raw order buried
# '13" Concrete Tile Re-Roof' behind "Permit Fees" and a fastener material escalation.
_ROOFING_RE = re.compile(
    r"tile|shingle|metal|membrane|coating|built[- ]?up|\bbur\b|tpo|pvc|modified|underlayment|"
    r"insulation|tapered|re[- ]?roof|reroof|waterproof|deck|soffit|fascia|gutter|scupper|drain|"
    r"flashing|parapet|skylight|vent|ridge|hip|valley|polyglass|sika|stockmeier|polyurethane|"
    r"silicone|restoration|repair|demo",
    re.I,
)

# Cosmetic prefixes Knowify carries from its own templates, including the pricing-sheet
# marker ("LINE ITEM PRICING: REPLACE STEEL DECKING PANEL") — the work is real, the prefix is
# an artifact of how it was quoted.
_PREFIX_RE = re.compile(r"^(?:fbc|hvhz)\s*[-–]\s*|^line item pricing\s*:\s*", re.I)

# Building / street numbers Knowify carries at the head of a deliverable — "1751 - Polyglass 70
# Acrylic Roofing System", "2401 Building Canopy ...". find_pii does not fire on a bare number
# (there is no street name to match), so without this the number reaches the page, and city +
# building number + four photos of the roof narrows to one property. Two shapes only, both
# checked against all 26,063 deliverables: 17 lines strip, and no year range or measurement is
# touched. Anything else that still opens with a number is REFUSED below rather than guessed at.
_BUILDING_PREFIX_RE = re.compile(
    r"^\d{2,6}\s*[-–—]\s+(?=\D)"      # "1751 - Polyglass ..."  (a digit after the dash = a year range)
    r"|^\d{2,6}\s+(?=Building\b)",    # "2401 Building Canopy ..." — drop the number, keep "Building"
    re.I,
)
_LEADING_NUMBER_RE = re.compile(r"^(\d{3,6})\b\s*(\S*)")
# A leading number followed by one of these is a measurement, not an address ("135 ft. Boom").
_MEASUREMENT_UNITS = frozenset(
    "ft feet foot sq square lf in inch inches mil mils yard yards yr year years gal lb lbs ply "
    "tab tabs pc pcs ea".split()
)

MAX_SCOPE_LINES = 8


def _address_number_risk(desc: str) -> bool:
    """True when a line still opens with a bare number that could be a building or street number.

    Refusing beats guess-stripping: on this corpus the ambiguous cases include "4952 and 4944
    Front Cupola Repair" and "409 Valley Metal Roof Repair and 401 Gutter Repair", where removing
    the first number leaves the second one on the page and mangles the sentence. Dropping the
    line loses some scope detail; publishing it loses the client's address.
    """
    match = _LEADING_NUMBER_RE.match(desc)
    if not match:
        return False
    unit = match.group(2).strip(".,:;").lower()
    return unit not in _MEASUREMENT_UNITS


def _detitle(desc: str) -> str:
    """Title-case a SHOUTING contract line, leaving mixed-case spellings alone.

    Applied to the part before any parenthetical, because the common shape is a caps
    description with a lowercase pricing note: "EXTERIOR CHIMNEY RESTORATION (per structure)".
    Only converts when that part has no lowercase at all, so brand spellings ("Polyglass MTS",
    "Sika RoofPro", "TPO") survive intact.
    """
    head, sep, tail = desc.partition("(")
    if head.strip() and head.strip().isupper():
        head = head.title()
    return (head + sep + tail).strip()


def scope_for_dominant_client(rows: Iterable[dict]) -> list[str]:
    """Scope lines belonging to ONE customer, from rows spanning possibly several.

    ``rows``: dicts of {client_id, project_name, description}.

    A search term can legitimately match several projects for the same property (Olsen Condo
    has a tile re-roof, a terrace-deck restoration and a BUR contract) or several projects for
    DIFFERENT customers ("warehouse" matches 9 projects across 7 clients). Merging the second
    kind would publish another client's job on this page.

    So: group by client, take the client owning the most matched projects, and require them to
    own MORE THAN HALF. No clear owner means the term is too generic to attribute, and the page
    ships without scope — the honest outcome, since the alternative is a confident lie about
    someone's property.
    """
    grouped: dict[str, set] = {}
    by_client: dict[str, list[dict]] = {}
    for row in rows:
        client = str(row.get("client_id") or "")
        grouped.setdefault(client, set()).add(row.get("project_name"))
        by_client.setdefault(client, []).append(row)

    if not grouped:
        return []
    total_projects = sum(len(names) for names in grouped.values())
    dominant, names = max(grouped.items(), key=lambda kv: len(kv[1]))
    if total_projects and len(names) * 2 <= total_projects:
        return []
    return clean_scope_lines(by_client[dominant])


def clean_scope_lines(rows: Iterable[dict]) -> list[str]:
    """Deliverable rows -> publishable scope descriptions, in order, deduped.

    ``rows`` are dicts with at least ``description``. Quantity/unit are deliberately ignored
    (rule 3). Returns [] when nothing survives, which is a legitimate outcome — a repair-only
    contract has nothing worth publishing as project scope.
    """
    kept: list[str] = []
    seen: set[str] = set()
    for row in rows:
        desc = (row.get("description") or "").strip()
        if (not desc or _NOISE_RE.match(desc) or _OPTIONAL_RE.search(desc)
                or _COMMERCIAL_RE.search(desc) or has_pii(desc)):
            continue
        desc = _BUILDING_PREFIX_RE.sub("", desc).strip()
        desc = _PREFIX_RE.sub("", desc).strip()
        if _address_number_risk(desc):
            continue
        desc = _detitle(desc)
        key = desc.lower()
        if key in seen:
            continue
        seen.add(key)
        kept.append(desc)

    # Roof work first, administrative lines (permits, bonds) after — then cap. Stable within
    # each group, so the contract's own ordering still shows through.
    ranked = sorted(kept, key=lambda d: 0 if _ROOFING_RE.search(d) else 1)
    return ranked[:MAX_SCOPE_LINES]


def scope_sentence(lines: Iterable[str]) -> str:
    """One plain sentence naming the work, for the FAQ answer and the meta description."""
    items = list(lines)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" and {items[-1]}"
