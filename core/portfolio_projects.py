"""Project-record rules: slugs, validation, and seeding from the old hardcoded list (pure).

Kept out of the route so the rules are testable without FastAPI or a database. The route owns
I/O; this owns "what is a valid project record and what is its slug".
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from core.pii import find_pii, person_name_risk

_MAX_NAME = 300
_SECTIONS = ("commercial", "residential", "construction")


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def unique_slug(name: str, taken: Iterable[str]) -> str:
    """A slug that is not already used.

    The slug is the join key for curation (migration 0048) and the WordPress lookup, so a
    collision would silently graft one project's media onto another. Suffixes rather than
    rejecting, because two "Tile Re-Roof" projects in different cities is a normal thing to want.
    """
    base = slugify(name) or "project"
    used = set(taken)
    if base not in used:
        return base
    for n in range(2, 100):
        candidate = f"{base}-{n}"
        if candidate not in used:
            return candidate
    raise ValueError(f"could not find a free slug for {name!r}")


def validate_record(record: dict, *, existing_slugs: Iterable[str] = ()) -> list[str]:
    """Problems with a project record; empty list means it may be saved.

    Validation is about STORING a record, not publishing it — the publish gate
    (core.portfolio_criteria) is stricter. But PII is refused at the door too: an address typed
    into the notes field is a disclosure waiting for someone to press publish, and the earlier
    it is caught the less likely it is to reach a page.
    """
    problems: list[str] = []
    name = (record.get("name") or "").strip()
    if not name:
        problems.append("name is required")
    elif len(name) > _MAX_NAME:
        problems.append(f"name is longer than {_MAX_NAME} characters")

    section = (record.get("section") or "").strip().lower()
    if section and section not in _SECTIONS:
        problems.append(f"section must be one of {', '.join(_SECTIONS)}")

    for field in ("companycam_url", "youtube_url"):
        value = (record.get(field) or "").strip()
        if value and not value.startswith(("http://", "https://")):
            problems.append(f"{field} must be a URL")

    # PII in any stored free-text field. City is allowed and deliberately not checked.
    for field in ("name", "notes", "date_start", "date_end"):
        for finding in find_pii(record.get(field)):
            problems.append(f"{field} contains {finding.kind}: {finding.text!r}")

    if name and person_name_risk(name, record.get("city")):
        problems.append(
            f"name {name!r} reads as an individual — use the property or association name"
        )

    terms = record.get("search_terms")
    if terms is not None and not isinstance(terms, list):
        problems.append("search_terms must be a list")

    return problems


def seed_records() -> list[dict[str, Any]]:
    """The 13 records previously hardcoded in scripts/portfolio_prefill.CANDIDATES.

    Imported lazily so the pure module has no import-time dependency on a script, and returned
    as plain dicts with a slug so the caller can insert them idempotently.
    """
    from scripts.portfolio_prefill import CANDIDATES  # noqa: PLC0415

    out: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        out.append({
            "slug": slugify(candidate["name"]),
            "name": candidate["name"],
            "city": candidate.get("city") or "",
            "section": (candidate.get("section") or "commercial").lower(),
            "companycam_url": candidate.get("companycam_url") or "",
            "youtube_url": candidate.get("youtube_url") or "",
            "date_start": candidate.get("date_start") or "",
            "date_end": candidate.get("date_end") or "",
            "notes": candidate.get("notes") or "",
            "search_terms": list(candidate.get("search_terms") or []),
        })
    return out
