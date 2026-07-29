"""Adversarial critique for a project page — pure prompt/parse logic, no I/O.

Same contract as core.article_critique (``critique_prompt`` / ``parse_findings`` /
``blocking``) so the wiring, the severity vocabulary and the fail-closed parsing are shared
rather than reimplemented.

WHY IT EXISTS ALONGSIDE THE DETERMINISTIC GATE. core.portfolio_criteria is the enforcing gate:
fast, exact, and it refuses a publish. It can only check what a regex can see. These critics
read the page the way a person would and catch the classes a checklist structurally cannot:

  PRIVACY   — the deterministic check finds "1424 Willow Rd". It cannot notice that
              "the corner unit above the tennis courts" identifies a home just as precisely,
              or that a photo caption names the owner's business. Given how much PII our
              sources hold (every project has a street address; half the project names ARE
              customer names), this lens is first and is allowed to be paranoid.
  GROUNDING — every sentence must trace to the project record or the contract scope. Nothing
              here may be inferred: the articles were ~90% invented when generation outran its
              grounding, and a project page invents even more easily because the record is thin.
  READER    — would a South Florida property manager get anything from this page, or is it a
              gallery with filler around it?

Three DIFFERENT lenses, not three skeptics: a privacy critic will never notice the page is
boring, and a reader critic will never notice a unit number in an alt attribute.

The critics ADVISE. Only core.portfolio_criteria refuses a publish, because an LLM's opinion is
not a gate we can reproduce — but a blocker here should stop a human from pressing publish, and
the UI shows it that way.
"""
from __future__ import annotations

from core.article_critique import BLOCKING, CRITIQUE_SCHEMA, parse_findings  # noqa: F401

_COMMON = (
    "You are reviewing a PROJECT PAGE for a South Florida roofing contractor's public website.\n"
    "It describes work done at a client's property. Be specific and actionable. Do NOT rewrite\n"
    "the page — report findings only.\n"
    "Severity: 'blocker' = must not publish, 'major' = clearly wrong or missing, 'minor' = polish.\n"
    "If the page is genuinely fine in your area, return an EMPTY findings list. Do not invent\n"
    "problems to look thorough.\n"
)

CRITICS: dict[str, str] = {
    "privacy": _COMMON + (
        "\nYOUR LENS: CLIENT PRIVACY. This is the highest-stakes review — treat anything that\n"
        "narrows the page to a specific home or person as a BLOCKER.\n"
        "The rule: the city or neighbourhood is allowed. Anything more precise is not.\n"
        "Flag as 'blocker':\n"
        "- a street address, house number, unit/apartment/suite number, postcode, or cross-street\n"
        "- a resident's or owner's name, a phone number, an email, a licence plate\n"
        "- an INDIRECT identifier that still pins one property: 'the corner unit above the tennis\n"
        "  courts', 'the only house on the street with a barrel-tile turret', a described\n"
        "  landmark that is unique to one address\n"
        "- anything implying who lives there, their schedule, their insurance claim, or a dispute\n"
        "Flag as 'major': naming the client at all when the page does not need to.\n"
        "Do NOT flag: the city, the neighbourhood, the county, a condo/association/building name,\n"
        "roof systems, materials, brands, or the contractor's own licence number.\n"
    ),
    "grounding": _COMMON + (
        "\nYOUR LENS: GROUNDING. Every specific claim must trace to the PROJECT RECORD or the\n"
        "CONTRACT SCOPE given below. Nothing may be inferred or filled in.\n"
        "Flag as 'blocker' any claim not supported by those inputs, especially:\n"
        "- a square footage, roof size, price, crew size, or duration that is not in the record\n"
        "- a product, manufacturer or warranty not named in the contract scope\n"
        "- an outcome ('completed on time', 'the client was delighted', 'no leaks since')\n"
        "- a code or permit claim not in the scope\n"
        "Flag as 'major' any scope line described as INSTALLED when it reads as optional or\n"
        "quoted. Flag as 'minor' vague filler that says nothing ('quality workmanship').\n"
        "An empty findings list is the right answer for a page that only restates its record.\n"
    ),
    "reader": _COMMON + (
        "\nYOUR LENS: THE READER — a property manager or homeowner choosing a roofer.\n"
        "Ignore SEO and privacy; other reviewers own those.\n"
        "Flag as 'major': the page says nothing a reader can use; the scope list is jargon with\n"
        "no explanation of what was actually done; the opening sentence does not say what the\n"
        "project WAS.\n"
        "Flag as 'minor': repetition, filler, or a gallery with no context.\n"
        "Do NOT ask for detail the contractor may not be allowed to publish, and do NOT ask for\n"
        "invented specifics — a short honest page beats a padded one.\n"
    ),
}


def critique_prompt(lens: str, page: dict) -> str:
    """Build one critic's prompt.

    ``page``: {title, city, meta, content_html, scope_lines, alt_texts}. The record and scope
    are passed EXPLICITLY so the grounding critic can check claims against their only legitimate
    source, and the alt texts separately because that is where PII hides from a reader.
    """
    if lens not in CRITICS:
        raise ValueError(f"unknown critic lens {lens!r}; expected one of {sorted(CRITICS)}")
    scope = page.get("scope_lines") or []
    alts = page.get("alt_texts") or []
    return "".join([
        CRITICS[lens],
        '\nReturn JSON: {"findings": [{"severity": ..., "issue": ..., "fix": ...}]}\n',
        f"\nPROJECT TITLE: {page.get('title', '')}",
        f"\nCITY (allowed to appear): {page.get('city', '')}",
        f"\nMETA DESCRIPTION: {page.get('meta', '')}",
        "\n\nCONTRACT SCOPE (the only source for specific work claims):\n"
        + ("\n".join(f"- {line}" for line in scope) if scope else "- (none matched)"),
        "\n\nIMAGE ALT TEXT (published, and a common hiding place for identifiers):\n"
        + ("\n".join(f"- {a}" for a in alts) if alts else "- (none)"),
        f"\n\nPAGE HTML:\n{page.get('content_html', '')}",
    ])


def blocking(findings: list[dict]) -> list[dict]:
    """Findings serious enough that a human should not publish."""
    return [f for f in findings if f.get("severity") in BLOCKING]


def merge(by_lens: dict[str, list[dict]]) -> list[dict]:
    """Flatten per-lens findings, tagging each with its lens and severity-sorted.

    Blockers first so the UI cannot bury a privacy finding under polish notes.
    """
    order = {"blocker": 0, "major": 1, "minor": 2}
    out = [{**f, "lens": lens} for lens, findings in by_lens.items() for f in findings]
    return sorted(out, key=lambda f: (order.get(f.get("severity"), 9), f.get("lens", "")))
