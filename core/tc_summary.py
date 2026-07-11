"""T&C bullet summary — pure functions, no I/O.

Mirrors the approach of core.contract_faq: build a grounded prompt and
robustly parse the model's response (JSON-first, list fallback).
"""
import re

from core.json_repair import parse_model_json


def build_tc_summary_prompt(tc_text: str, max_bullets: int = 8) -> str:
    """Return a prompt asking the LLM for a JSON array of plain-English summary bullets.

    max_bullets is clamped to [1, 15]. Each bullet must reference a real clause
    and use wording from the contract text.
    """
    max_bullets = max(1, min(max_bullets, 15))
    return (
        f"Summarize the following contract Terms & Conditions into exactly {max_bullets} "
        "plain-English bullet points for a homeowner.\n\n"
        f"{tc_text}\n\n"
        f"Return a JSON array of exactly {max_bullets} strings. "
        "Each bullet must be grounded in the contract: use wording and clause references "
        "from the contract text — do not invent or paraphrase beyond what the contract says.\n"
        'Example: ["30% deposit is due before work begins.", "Warranty is void if work is modified by others."]'
    )


def _parse_list_fallback(raw: str) -> list[str]:
    """Parse a numbered or bulleted list into strings when JSON parsing fails."""
    lines = raw.strip().splitlines()
    results = []
    for line in lines:
        # Strip leading list markers: "1. ", "- ", "• ", "* "
        cleaned = re.sub(r"^\s*(?:\d+\.|[-•*])\s+", "", line).strip()
        if cleaned:
            results.append(cleaned)
    return results


_LIST_LINE_RE = re.compile(r"^\s*(?:\d+\.|[-•*])\s+\S")


def _looks_like_list(raw: str) -> bool:
    """Return True if at least one line looks like a numbered/bulleted list item."""
    return any(_LIST_LINE_RE.match(line) for line in raw.splitlines())


def parse_tc_summary(raw: str) -> list[str]:
    """Robustly parse a model's T&C summary response.

    Accepts:
      - JSON array of strings (primary path, via json_repair)
      - Numbered list fallback  (e.g. "1. Bullet one\\n2. Bullet two")
      - Bulleted list fallback  (e.g. "- Bullet one\\n• Bullet two")

    Returns list[str] of stripped bullet strings; returns [] on failure.
    Non-string items in a JSON array are silently skipped.
    """
    if not raw:
        return []

    parsed = parse_model_json(raw)
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if isinstance(item, str)]

    # parse_model_json returned {} (failure sentinel) or a dict — not a list.
    # Only fall through to list parsing when the raw text actually looks like one.
    if _looks_like_list(raw):
        return _parse_list_fallback(raw)

    return []
