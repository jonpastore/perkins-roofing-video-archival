"""Parse + gate the structured output of the social-caption prompt (docs/prompts/social-caption-v3.md).

The v3 prompt returns three blocks:

    FLAGS: NO_TECH_FACT, MISSING_LICENSE   (or NONE)
    CAPTION:
    <caption text, possibly multi-line>
    HASHTAGS: #a #b #c

`parse_caption_output` splits that into structured fields. `gate_caption_flags` turns the model's
self-reported flags into a publish decision. Pure, no I/O — the caller wires it to the publish path
alongside the Track E content-safety gate (adapters.safety.run_gate).
"""
from __future__ import annotations

from dataclasses import dataclass

# Decision the flag-gate returns.
OK = "OK"            # auto-publishable (subject to the separate Track E safety gate)
REVIEW = "REVIEW"    # publishable but route to a human first
BLOCKED = "BLOCKED"  # never publish


@dataclass
class CaptionParts:
    flags: list[str]
    caption: str
    hashtags: str


def parse_caption_output(raw: str) -> CaptionParts:
    """Split a v3 caption output into (flags, caption, hashtags). Fail-safe: missing blocks → empty."""
    flags: list[str] = []
    caption_lines: list[str] = []
    hashtags = ""
    section = None
    for line in (raw or "").splitlines():
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
    caption = "\n".join(caption_lines).strip()
    return CaptionParts(flags=flags, caption=caption, hashtags=hashtags)


def gate_caption_flags(flags: list[str], *, require_license: bool = False) -> tuple[str, str]:
    """Turn self-reported flags into a publish decision. Returns (decision, reason).

    Fail-closed on compliance: a required-but-missing license blocks the post outright.
    """
    if require_license and "MISSING_LICENSE" in flags:
        return BLOCKED, "license required in caption but the model could not add it"
    if "NO_TECH_FACT" in flags:
        return REVIEW, "no verifiable technical fact — human should review before publish"
    return OK, ""
