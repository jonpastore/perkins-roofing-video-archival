"""Generate a video description from the transcript we already hold.

Pure functions only — no DB, no network. The route supplies the transcript rows, the prompt
template and an LLM; this module decides what the model is asked and what comes back. That split
is what makes the interesting parts testable without Vertex.

The prompt itself is operator-editable (VIDEO_DESCRIPTION_PROMPT in platform_config, Admin Config ->
Platform Settings), because what a good description says is a marketing judgement that changes
without a deploy.
"""
from __future__ import annotations

from dataclasses import dataclass

#: Transcripts run to tens of thousands of words on a long video and the description only needs the
#: substance. Gemini would accept far more, but every token is billed on a button a reviewer may
#: press repeatedly, so the transcript is trimmed to a generous but bounded window.
MAX_TRANSCRIPT_CHARS = 24_000

#: Used when the operator has not set VIDEO_DESCRIPTION_PROMPT. Deliberately plain: a placeholder
#: default that still produces something usable beats an empty box that produces an error, and it
#: shows the available placeholders by example.
DEFAULT_PROMPT = (
    "Write a YouTube video description for a roofing company's video.\n\n"
    "Title: {title}\n"
    "Duration: {duration}\n\n"
    "Transcript:\n{transcript}\n\n"
    "Write 2-3 short paragraphs in plain language for a homeowner. Describe what the video "
    "actually covers — do not invent services, prices, guarantees or locations that are not in "
    "the transcript. No hashtags, no emoji, no calls to action."
)


class DescriptionError(RuntimeError):
    """Raised when a description cannot be produced. Message is shown to the operator."""


@dataclass(frozen=True)
class Rendered:
    prompt: str
    transcript_chars: int
    truncated: bool


def transcript_text(segments) -> str:
    """Join transcript segments in time order.

    Accepts anything with `.text` and `.start`; segments arrive from the DB unordered often enough
    that sorting here rather than relying on the query is the safer default.
    """
    rows = [s for s in segments if (getattr(s, "text", "") or "").strip()]
    rows.sort(key=lambda s: (getattr(s, "start", 0) or 0))
    return " ".join((s.text or "").strip() for s in rows).strip()


def fmt_duration(seconds) -> str:
    """'1h 04m' / '4m 12s' / 'unknown' — a duration a model can read, not raw float seconds."""
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "unknown"
    if total <= 0:
        return "unknown"
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


def render_prompt(template: str | None, *, title: str | None, duration, transcript: str) -> Rendered:
    """Fill the operator's template.

    ⚠️ `str.format` is NOT used. The template is operator-authored free text and will contain
    literal braces sooner or later — a JSON example, a `{"a": 1}` snippet — and `format` raises
    KeyError on every one of them, turning a formatting quirk into a 500 on a button. Placeholders
    are substituted literally instead, so unknown braces pass through untouched.
    """
    if not (transcript or "").strip():
        raise DescriptionError(
            "This video has no transcript yet, so there is nothing to describe. "
            "It needs to finish ingestion first.")
    tpl = (template or "").strip() or DEFAULT_PROMPT
    trimmed = transcript[:MAX_TRANSCRIPT_CHARS]
    out = tpl
    for token, value in (
        ("{title}", title or "Untitled"),
        ("{duration}", fmt_duration(duration)),
        ("{transcript}", trimmed),
    ):
        out = out.replace(token, value)
    # A template that mentions none of the placeholders would send the model the transcript-free
    # instruction and quietly produce a generic description for every video. Append rather than
    # fail: the operator's words are still honoured, and the model still gets the material.
    if "{transcript}" not in tpl:
        out = f"{out}\n\nTranscript:\n{trimmed}"
    return Rendered(prompt=out, transcript_chars=len(trimmed),
                    truncated=len(transcript) > MAX_TRANSCRIPT_CHARS)


def clean(text: str | None) -> str:
    """Strip the wrapper models add — code fences, a leading 'Description:' label."""
    out = (text or "").strip()
    if out.startswith("```"):
        lines = out.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        out = "\n".join(lines).strip()
    for label in ("Description:", "DESCRIPTION:", "Video description:"):
        if out.startswith(label):
            out = out[len(label):].strip()
    if not out:
        raise DescriptionError("The model returned an empty description. Try again.")
    return out
