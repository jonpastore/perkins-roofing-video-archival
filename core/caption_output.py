"""Parse + gate the output of the social-caption prompt.

Primary contract is v5 (docs/prompts/social-caption-v5.md): a strict JSON object —
    {prompt_version, status, flags[], platform_used, hook_structure, tone, caption, hashtags[], word_count}
Legacy fallback is the v3 line format (FLAGS: / CAPTION: / HASHTAGS:).

`parse_caption_output` returns a CaptionParts for either shape (JSON first, then lines, then a
parse-error marker). `gate_caption` / `gate_caption_flags` turn status + flags into a publish
decision per the v5 gating rules. Pure, no I/O — the caller wires it to the publish path alongside
the Track E content-safety gate (adapters.safety.run_gate).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

# Publish decisions.
OK = "OK"            # auto-publishable (still subject to the separate Track E safety gate)
REVIEW = "REVIEW"    # publishable but route to a human first
BLOCKED = "BLOCKED"  # never publish

# v5 flag severity (see FLAG ENUM in the prompt).
BLOCK_FLAGS = frozenset({"SUSPECT_TRANSCRIPT", "UNUSABLE_TRANSCRIPT", "MISSING_LICENSE"})
REVIEW_FLAGS = frozenset({"NO_TECH_FACT", "INSURANCE_TRIM"})
# NO_VOICE_SAMPLES + info flags (NO_BRIDGE, *_COLLISION, ASSUMED_PLATFORM_INSTAGRAM) → log only.


@dataclass
class CaptionParts:
    flags: list[str]
    caption: str
    hashtags: list[str] | str
    status: str = "ok"               # "ok" | "withheld" | "parse_error"
    prompt_version: str = ""
    platform_used: str = ""
    hook_structure: str | None = None
    tone: str | None = None
    word_count: int | None = None
    raw_ok: bool = True              # False when a JSON-looking payload failed to parse (caller may retry)
    extra: dict = field(default_factory=dict)


def _from_json(obj: dict) -> CaptionParts:
    return CaptionParts(
        flags=[str(f) for f in (obj.get("flags") or [])],
        caption=obj.get("caption") or "",
        hashtags=obj.get("hashtags") or [],
        status=obj.get("status", "ok"),
        prompt_version=obj.get("prompt_version", ""),
        platform_used=obj.get("platform_used", ""),
        hook_structure=obj.get("hook_structure"),
        tone=obj.get("tone"),
        word_count=obj.get("word_count"),
    )


def _from_lines(raw: str) -> CaptionParts:
    """Legacy v3 parser: FLAGS: / CAPTION: / HASHTAGS: blocks."""
    flags: list[str] = []
    caption_lines: list[str] = []
    hashtags = ""
    section = None
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("FLAGS:"):
            codes = stripped[len("FLAGS:"):].strip().strip("[]")
            if codes and codes.upper() != "NONE":
                flags = [c.strip() for c in codes.split(",") if c.strip()]
            section = None
        elif stripped.upper().startswith("CAPTION:"):
            section = "caption"
        elif stripped.upper().startswith("HASHTAGS:"):
            hashtags = stripped[len("HASHTAGS:"):].strip()
            section = None
        elif section == "caption":
            caption_lines.append(line)
    return CaptionParts(flags=flags, caption="\n".join(caption_lines).strip(), hashtags=hashtags)


def parse_caption_output(raw: str | None) -> CaptionParts:
    """Parse a caption output. Tries v5 JSON first, then the v3 line format.

    A payload that looks like JSON (starts with '{') but fails to parse returns
    status='parse_error', raw_ok=False so the caller can trigger the one-retry the v5
    pipeline notes prescribe before dead-lettering.
    """
    if not raw or not raw.strip():
        return CaptionParts(flags=[], caption="", hashtags="")
    text = raw.strip()
    if text.startswith("{"):
        # A payload that opens with '{' is a v5 JSON attempt: it either parses to an object or is
        # malformed (json.loads on a '{'-prefixed string never yields a non-dict).
        try:
            return _from_json(json.loads(text))
        except ValueError:
            return CaptionParts(flags=[], caption="", hashtags="", status="parse_error", raw_ok=False)
    return _from_lines(text)


def gate_caption_flags(flags: list[str], *, status: str = "ok", require_license: bool = False) -> tuple[str, str]:
    """Turn status + self-reported flags into a publish decision. Returns (decision, reason).

    Fail-closed: withheld / unparseable output and block-class flags never publish.
    """
    if status == "withheld":
        return BLOCKED, "model withheld output"
    if status == "parse_error":
        return BLOCKED, "caption output did not parse"
    fl = set(flags)
    hard = fl & {"SUSPECT_TRANSCRIPT", "UNUSABLE_TRANSCRIPT"}
    if hard:
        return BLOCKED, f"block-class flag: {', '.join(sorted(hard))}"
    # MISSING_LICENSE: v5 emits it with status='withheld' (caught above); the v3 line path gates it
    # here only when the caller requires a license in the caption.
    if "MISSING_LICENSE" in fl and require_license:
        return BLOCKED, "license required in caption but the model could not add it"
    review = fl & REVIEW_FLAGS
    if review:
        return REVIEW, f"{', '.join(sorted(review))} — human should review before publish"
    return OK, ""


def gate_caption(parts: CaptionParts, *, require_license: bool = False) -> tuple[str, str]:
    """Gate a parsed CaptionParts (passes its status through). Convenience for callers."""
    return gate_caption_flags(parts.flags, status=parts.status, require_license=require_license)
