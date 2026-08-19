"""Sanitize sidebar prefs stored on the user profile.

Pins, folded section labels, and the icon-rail flag belong on user_settings so
they follow the signed-in account across browsers. Unknown keys and junk ids
are dropped; the SPA always gets a complete {pins, sections, collapsed} dict.
"""
from __future__ import annotations

import re
from typing import Any

_PIN = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
_SECTION = re.compile(r"^[A-Za-z][A-Za-z0-9 /-]{0,39}$")
MAX_PINS = 40
MAX_SECTIONS = 8


def empty_nav() -> dict[str, Any]:
    return {"pins": [], "sections": [], "collapsed": False}


def nav_saved(raw: Any) -> bool:
    """True after a PUT — the JSON has nav keys, even if every list is empty."""
    return isinstance(raw, dict) and any(k in raw for k in ("pins", "sections", "collapsed"))


def _clean_ids(raw: Any, pattern: re.Pattern[str], limit: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if not pattern.fullmatch(value) or value in seen:
            continue
        seen.add(value)
        out.append(value)
        if len(out) >= limit:
            break
    return out


def collapsed_flag(value: Any) -> bool:
    if value is True or value == 1:
        return True
    return isinstance(value, str) and value.strip().lower() in {"1", "true"}


def sanitize_nav(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return empty_nav()
    return {
        "pins": _clean_ids(raw.get("pins"), _PIN, MAX_PINS),
        "sections": _clean_ids(raw.get("sections"), _SECTION, MAX_SECTIONS),
        "collapsed": collapsed_flag(raw.get("collapsed")),
    }
