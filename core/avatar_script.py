"""Avatar script assembly — pure logic (no I/O). 100%-coverable.

Flow (ownership boundaries):
  topic
    → (retrieval, external)
    → build_script_prompt(topic, grounding_snippets)
    → (LLM, external)
    → parse_script(raw)
    → script_gate_input(script)
    → safety gate
    → (render, external)

Only the pure pieces live here.  Retrieval, LLM calls, safety gate, and
render API calls all happen in the adapter/job layer.
"""

from __future__ import annotations

from typing import Any

from core.json_repair import parse_model_json

# Target reading speed for a talking-head video (words per minute).
# ElevenLabs professional voice clones speak at roughly 130–150 wpm; 140 is the midpoint.
_WPM = 140

# Minimum plausible script length in words (sanity guard on garbage parse output).
_MIN_WORDS = 20


def build_script_prompt(topic: str, grounding_snippets: list[dict[str, str]]) -> str:
    """Build the LLM prompt that drafts a Tim-voice roofing script.

    The prompt grounds the script in retrieved corpus snippets so the avatar
    stays accurate to what Tim has actually said on camera.  Each snippet is a
    dict with at least a ``text`` key; an optional ``link`` key (YouTube URL
    with timestamp) is appended when present so the LLM can credit the source.

    Args:
        topic:               The subject the avatar should cover (e.g. "roof-age
                             insurance nonrenewal in Florida").
        grounding_snippets:  Up to ~8 dicts from the retrieval layer, each with
                             ``text`` and optionally ``link``.

    Returns:
        A single prompt string ready to pass to an LLM chat call with
        ``want_json=True``.
    """
    snippets_block = ""
    if grounding_snippets:
        lines = []
        for i, s in enumerate(grounding_snippets, start=1):
            link_part = f"  ({s['link']})" if s.get("link") else ""
            lines.append(f"{i}. {s.get('text', '').strip()}{link_part}")
        snippets_block = (
            "\n\nSOURCE CLIPS from Tim's own YouTube videos — ground the script in these:\n"
            + "\n".join(lines)
        )

    return (
        "You are writing a short educational video script for Tim Perkins, owner of Perkins Roofing "
        "in South Florida. Tim speaks in a direct, friendly, professional tone — like a trusted "
        "neighbour who happens to be a licensed roofing expert. He avoids jargon without dumbing "
        "things down. No crude language, no hype, no filler phrases like 'Let me tell you…'.\n\n"
        f"Topic: {topic}\n"
        f"{snippets_block}\n\n"
        "Write a 60–90 second talking-head script. It should:\n"
        "  - Open with a direct, specific hook (what problem does this solve for the homeowner?)\n"
        "  - Cover the 2–3 most important points, grounded in Tim's actual expertise above\n"
        "  - Close with a clear, professional call-to-action (call/text Perkins Roofing)\n"
        "  - Sound natural when spoken aloud — short sentences, conversational rhythm\n\n"
        "Return ONLY a JSON object with exactly these keys:\n"
        '  {"title": "<short video title>", "script_text": "<full script, no stage directions>", '
        '"est_seconds": <integer — estimated runtime in seconds>}\n\n'
        "Do NOT include markdown fences, stage directions, or any text outside the JSON."
    )


def parse_script(raw: Any) -> dict[str, Any]:
    """Robustly parse an LLM response into a script dict.

    Accepts a str (JSON or fenced JSON) or a dict (already parsed).
    Guarantees the returned dict always has ``title``, ``script_text``, and
    ``est_seconds`` keys — never raises.  Falls back to sensible defaults on
    any parse failure so the caller can surface a human-readable error rather
    than an uncaught exception.

    ``est_seconds`` is either taken from the LLM's own estimate or computed
    from the word-count of ``script_text`` at _WPM words per minute.

    Args:
        raw: LLM response — dict or str.

    Returns:
        Dict with keys ``title`` (str), ``script_text`` (str),
        ``est_seconds`` (int), and ``parse_ok`` (bool — False when the
        input was unrecoverable garbage, so the caller can log a warning).
    """
    _FALLBACK: dict[str, Any] = {
        "title": "",
        "script_text": "",
        "est_seconds": 0,
        "parse_ok": False,
    }

    if raw is None:
        return _FALLBACK.copy()

    if isinstance(raw, dict):
        data: dict = raw
    elif isinstance(raw, str):
        data = parse_model_json(raw)
        if not data or not isinstance(data, dict):
            return _FALLBACK.copy()
    else:
        return _FALLBACK.copy()

    title = str(data.get("title") or "").strip()
    script_text = str(data.get("script_text") or "").strip()

    # est_seconds: prefer LLM's value when it's a positive integer; otherwise compute.
    raw_secs = data.get("est_seconds")
    try:
        est_seconds = int(raw_secs)
        if est_seconds <= 0:
            raise ValueError("non-positive")
    except (TypeError, ValueError):
        est_seconds = 0

    if not est_seconds and script_text:
        word_count = len(script_text.split())
        est_seconds = max(1, round(word_count / _WPM * 60))

    # A script with fewer than _MIN_WORDS is almost certainly a parse failure.
    parse_ok = len(script_text.split()) >= _MIN_WORDS

    return {
        "title": title,
        "script_text": script_text,
        "est_seconds": est_seconds,
        "parse_ok": parse_ok,
    }


def script_gate_input(script: dict[str, Any]) -> str:
    """Return the text string to hand to the content-safety gate.

    Concatenates title + script_text so the gate sees the full artifact.
    The safety gate (``adapters.safety.run_gate``) expects a plain string.

    Args:
        script: A dict as returned by ``parse_script`` (or any dict with
                optional ``title`` and ``script_text`` string keys).

    Returns:
        Plain string — "<title>\\n\\n<script_text>".strip().
    """
    parts = []
    title = str(script.get("title") or "").strip()
    body = str(script.get("script_text") or "").strip()
    if title:
        parts.append(title)
    if body:
        parts.append(body)
    return "\n\n".join(parts)
