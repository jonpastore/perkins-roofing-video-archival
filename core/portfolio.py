"""Avada Portfolio prefill — pure mapping from an assembled project record to (a) Wendy's
30-field questionnaire dict and (b) an Avada `avada_portfolio` post payload.

A "record" is a plain dict assembled by scripts/portfolio_prefill.py from Knowify + the
videos/chunks tables + the project doc (name, city, section, links, dates, ...). This module
does no I/O — it only maps data that already exists onto the two output shapes, and reports
which questionnaire fields still need a human.
"""
from __future__ import annotations

# Order matches details_sheet.csv column 1 (the 30-field questionnaire). Fields NOT in
# DATA_FIELDS below are human-only (project manager judgment, warranty terms, permissions,
# client feedback, ...) and are always left "" for a person to fill in.
QUESTIONNAIRE_FIELDS = [
    "Project name",
    "Project city",
    "Property type",
    "Project completion date",
    "Project Manager",
    "Project Duration or start date",
    "Roof size",
    "Number of buildings",
    "Original roof type",
    "New roof type",
    "Roof Manufacturer",
    "Product or system",
    "Reason for project",
    "Additional Services included",
    "Whether building remained occupied",
    "Safety or access requirements",
    "Project Outcome",
    "Warranty provided",
    "Client on maintenance program",
    "Project challenges",
    "Other contractors involved",
    "HVHZ and / or permit requirements / inpections required during  / after completion",
    "Final result",
    "Client feedback",
    "Link to Photos on CompanyCam ",
    "Link to Video on YouTube",
    "Any other comments that are relevant and can be used in the write up of the project",
    "Permission to name property",
    "Permission to use photos",
    "Permission to use video",
]

# roof-type keyword -> canonical label. Order matters: more specific phrases first so e.g.
# "silicone coating" wins over the bare "coating" fallback.
_ROOF_TYPE_KEYWORDS = [
    ("clay barrel tile", "Clay Barrel Tile"),
    ("barrel tile", "Clay Barrel Tile"),
    ("standing seam", "Standing Seam Metal"),
    ("polyglass", "Polyglass Silicone Restoration"),
    ("silicone", "Silicone Coating"),
    ("tpo", "TPO"),
    ("soffit", "Soffit"),
    ("concrete", "Concrete Repair"),
    ("shingle", "Asphalt Shingle"),
    ("coating", "Roof Coating"),
    ("flat roof", "Flat/Built-Up"),
    ("metal", "Metal"),
    ("tile", "Tile"),
]


_PROPERTY_TYPE_KEYWORDS = [
    ("warehouse", "Warehouse"),
    ("office", "Office"),
    ("retail", "Retail"),
    ("hoa", "HOA"),
    ("condo", "Condo"),
    ("industrial", "Industrial"),
    ("tower", "Condo"),
]


def infer_property_type(*texts: str | None) -> str | None:
    """Best-effort property type from Knowify ContractType / project name text."""
    for text in texts:
        if not text:
            continue
        low = text.lower()
        if "residentialjob" in low:
            return "Residential"
        if "commercialjob" in low:
            return "Commercial"
        for kw, label in _PROPERTY_TYPE_KEYWORDS:
            if kw in low:
                return label
    return None


def infer_roof_type(*texts: str | None) -> str | None:
    """Best-effort roof type from titles/transcripts. Checks each text in order and returns
    the first keyword match; None if nothing recognizable is present (leave for a human)."""
    for text in texts:
        if not text:
            continue
        low = text.lower()
        for kw, label in _ROOF_TYPE_KEYWORDS:
            if kw in low:
                return label
    return None


def map_to_questionnaire(record: dict) -> dict[str, str]:
    """Prefill only the questionnaire fields the assembled record supports; everything else
    is "" for a human to fill in."""
    values = {
        "Project name": record.get("name", ""),
        "Project city": record.get("city", ""),
        "Property type": record.get("property_type", ""),
        "Project completion date": record.get("completion_date", ""),
        "Project Duration or start date": record.get("start_date", ""),
        "Original roof type": record.get("original_roof_type", ""),
        "New roof type": record.get("new_roof_type", ""),
        "Reason for project": record.get("reason", ""),
        "Link to Photos on CompanyCam ": record.get("companycam_url", ""),
        "Link to Video on YouTube": record.get("youtube_url", ""),
    }
    return {field: values.get(field, "") for field in QUESTIONNAIRE_FIELDS}


def needs_human(questionnaire: dict[str, str]) -> list[str]:
    """Fields still blank after prefill — the punch list for a human to complete."""
    return [field for field, value in questionnaire.items() if not value]


def map_to_post(record: dict, *, content_html: str) -> dict:
    """Avada `avada_portfolio` post payload. Category is the doc section the project came
    from (Commercial/Residential) — none of the current candidates need the third
    "Construction" taxonomy term, but callers may pass section="construction" for one that does.
    Tags = city, Skills = inferred roof type(s)."""
    section = (record.get("section") or "commercial").lower()
    category = {"residential": "Residential", "construction": "Construction"}.get(section, "Commercial")
    roof_type = record.get("new_roof_type") or infer_roof_type(record.get("name"), content_html)
    return {
        "title": record.get("name", ""),
        "content": content_html,
        "status": "draft",
        "category": category,
        "tags": [record["city"]] if record.get("city") else [],
        "skills": [roof_type] if roof_type else [],
    }
