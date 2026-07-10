"""Emoji / keyword highlight helpers for ASS caption generation.

Pure, no I/O.  Provides:
- KEYWORD_EMOJI_MAP  — roofing-domain keyword→emoji lookup (immutable).
- apply_emoji_highlights — annotate word dicts with an emoji suffix and a
  highlight flag, then used by to_ass_karaoke_with_emoji to inject the emoji
  after the matched word and wrap it in an ASS colour-override tag.

Design constraints:
- Toggled per clip via a spec field (emoji_highlights: bool); off by default.
- All matching is case-insensitive on the raw word token.
- The emoji is appended after the matched word in the caption text; it does
  not consume its own karaoke slot (it travels with the word's \\k segment).
- The highlight colour is a brand-red accent (&H002222CC in ASS BGR) applied
  via an inline \\c override tag within the karaoke word span.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Keyword → emoji map (roofing domain + generics)
# ---------------------------------------------------------------------------

KEYWORD_EMOJI_MAP: dict[str, str] = {
    "roof": "\U0001f3e0",        # house: roof
    "roofing": "\U0001f3e0",
    "rooftop": "\U0001f3e0",
    "leak": "\U0001f4a7",        # droplet: leak
    "leaking": "\U0001f4a7",
    "leaks": "\U0001f4a7",
    "hurricane": "\U0001f300",   # cyclone: hurricane
    "storm": "\U0001f329️", # cloud lightning: storm
    "warranty": "✅",        # check mark: warranty
    "warranties": "✅",
    "guaranteed": "✅",
    "cost": "\U0001f4b0",        # money bag: cost
    "price": "\U0001f4b0",
    "pricing": "\U0001f4b0",
    "quote": "\U0001f4b0",
    "estimate": "\U0001f4b0",
    "tile": "\U0001f9f1",        # bricks: tile
    "tiles": "\U0001f9f1",
    "shingle": "\U0001f9f1",
    "shingles": "\U0001f9f1",
    "insurance": "\U0001f4cb",   # clipboard: insurance
    "claim": "\U0001f4cb",
    "damage": "⚠️",   # warning: damage
    "damaged": "⚠️",
    "repair": "\U0001f527",      # wrench: repair
    "repairs": "\U0001f527",
    "replace": "\U0001f527",
    "replacement": "\U0001f527",
    "free": "\U0001f7e2",        # green circle: free
    "save": "\U0001f4b0",
    "discount": "\U0001f4b0",
    "inspector": "\U0001f50d",   # magnifier: inspector
    "inspection": "\U0001f50d",
    "solar": "☀️",     # sun: solar
    "panel": "☀️",
    "panels": "☀️",
    "gutter": "\U0001f4a6",      # sweat drop: gutter
    "gutters": "\U0001f4a6",
    "drainage": "\U0001f4a6",
}

# ASS inline colour override for highlighted keywords (brand red = &H002222CC BGR).
_HIGHLIGHT_COLOR_TAG = r"{\c&H002222CC&}"
_RESET_COLOR_TAG = r"{\c}"

# Regex to strip non-alphanumeric characters for token matching.
_STRIP_RE = re.compile(r"[^a-z0-9]")


def _token(word: str) -> str:
    """Normalise *word* to a bare lowercase alphanumeric token for map lookup."""
    return _STRIP_RE.sub("", word.lower())


def apply_emoji_highlights(
    words: list[dict],
    *,
    keyword_map: dict[str, str] | None = None,
) -> list[dict]:
    """Return a copy of *words* with emoji/highlight annotations.

    Each returned word dict gains two extra keys:
    - ``emoji``     : str — emoji to append after the word (empty string if none).
    - ``highlight`` : bool — True when the word matches a keyword.

    The original dicts are not mutated.  Input word dicts must carry at least
    ``word`` (str), ``start`` (float), ``end`` (float).

    Args:
        words:       Word list from caption_events / group_caption_lines.
        keyword_map: Override the default KEYWORD_EMOJI_MAP (mainly for tests).
    """
    km = keyword_map if keyword_map is not None else KEYWORD_EMOJI_MAP
    result: list[dict] = []
    for w in words:
        tok = _token(str(w.get("word") or ""))
        emoji = km.get(tok, "")
        annotated = dict(w)
        annotated["emoji"] = emoji
        annotated["highlight"] = bool(emoji)
        result.append(annotated)
    return result


def build_karaoke_word(
    word: str,
    dur_cs: int,
    *,
    emoji: str = "",
    highlight: bool = False,
) -> str:
    """Return an ASS karaoke word span for one word.

    Format: ``{\\k<dur>}<colour_open><word><emoji><colour_close>``

    When *highlight* is False the colour override tags are omitted.
    The emoji (if any) is appended immediately after the word, inside the
    karaoke duration span so it appears at the same moment as the word.

    Args:
        word:      The display word text (already stripped).
        dur_cs:    Karaoke duration for this word in centiseconds.
        emoji:     Optional emoji suffix (empty string for none).
        highlight: Whether to wrap with the brand-red colour override.
    """
    suffix = emoji if emoji else ""
    if highlight:
        return f"{{\\k{dur_cs}}}{_HIGHLIGHT_COLOR_TAG}{word}{suffix}{_RESET_COLOR_TAG}"
    return f"{{\\k{dur_cs}}}{word}{suffix}"
