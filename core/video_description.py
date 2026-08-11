"""Generate a video description from the transcript we already hold.

Pure functions only — no DB, no network. The route supplies the transcript rows, the prompt
template and an LLM; this module decides what the model is asked and what comes back. That split
is what makes the interesting parts testable without Vertex.

The prompt itself is operator-editable (VIDEO_DESCRIPTION_PROMPT in platform_config, Admin Config ->
Platform Settings), because what a good description says is a marketing judgement that changes
without a deploy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: Hard ceiling on hashtags in a generated caption. Josh's prompt asks for "approximately 5";
#: "approximately" is not a thing a model obeys, so the number is also enforced after the fact.
MAX_HASHTAGS = 5

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


#: A hashtag: # at the START of a token, followed by word characters.
#:
#: The lookbehind must reject ANY non-space, not just word characters. `(?<![\w#])` let
#: "https://perkinsroofing.com/#contact" count as a hashtag — "/" is not a word char — so a
#: caption with five tags plus a booking link had the link counted toward the cap and then
#: TRUNCATED to "…perkinsroofing.com/" when the fragment was trimmed as the sixth tag. With the
#: URL earlier in the text it inverted and ate a genuine hashtag instead. Requiring whitespace or
#: start-of-string before the # covers "C#", "a#b" and every URL fragment in one rule.
_HASHTAG_RE = re.compile(r"(?:(?<=\s)|^)#\w+")

#: Structural labels the prompt's OUTPUT RULE forbids — the model emitting its own scaffolding
#: ("Hook:", "Hashtags:") instead of the finished caption.
_LABEL_RE = re.compile(r"^\s*(hashtags?|hook|caption|body|final caption)\s*:\s*", re.IGNORECASE)

#: Chat filler that must never reach a social post. Checked, not stripped: if the model is talking
#: to the reviewer mid-caption, the text needs a human's eye, not a regex.
_CHATTER = (
    "here is your caption", "here's your caption", "here is the caption",
    "let me know if", "would you like", "i hope this helps",
)


@dataclass(frozen=True)
class Checked:
    """A caption after the post-generation pass. `fixes` were applied; `problems` were not."""
    text: str
    fixes: tuple[str, ...]
    problems: tuple[str, ...]


def enforce(text: str, *, max_hashtags: int = MAX_HASHTAGS) -> Checked:
    """Hold generated output to the prompt's own rules.

    The prompt states the rules; nothing until now checked that a given generation followed them.
    Two of them are mechanical, so they are enforced rather than hoped for:

      * **at most `max_hashtags` hashtags** — extras are dropped, earliest kept. The model treats
        "approximately 5" as a suggestion and regularly returns eight.
      * **no structural labels** ("Hook:", "Hashtags:") — the OUTPUT RULE forbids them and they
        are unambiguous scaffolding, so they are stripped.

    What is NOT auto-fixed is reported instead: assistant chatter aimed at the reviewer, and a
    caption with no hashtags at all. Rewriting those means guessing at intent, and a silent guess
    on a caption bound for Perkins' Instagram is worse than a flag the reviewer can act on.
    """
    fixes: list[str] = []
    problems: list[str] = []

    lines, stripped_labels = [], 0
    for line in text.splitlines():
        new = _LABEL_RE.sub("", line)
        if new != line:
            stripped_labels += 1
        lines.append(new)
    out = "\n".join(lines)
    if stripped_labels:
        fixes.append(f"removed {stripped_labels} structural label(s) the output rule forbids")

    tags = _HASHTAG_RE.findall(out)
    if len(tags) > max_hashtags:
        # Drop from the END so the model's own ordering (most relevant first) survives.
        for extra in reversed(tags[max_hashtags:]):
            idx = out.rfind(extra)
            if idx != -1:
                out = out[:idx] + out[idx + len(extra):]
        # Take the separator and spacing that belonged to the removed tag with it. A
        # comma-separated run ("#a, #b, #c.") otherwise trims to "#a, #b, ." — and that stranded
        # punctuation is what gets posted.
        out = re.sub(r"[ \t]*,(?=[ \t]*(?:[.,]|$))", "", out, flags=re.M)  # orphaned separator comma
        out = re.sub(r"(?m)^[ \t]*[,;]+[ \t]*", "", out)          # line now starting with a comma
        # Only where a tag was removed — running this over the whole caption silently reflowed
        # the author's prose, and only when a trim happened to occur.
        out = re.sub(r"(#\w+)[ \t]+([.!?,;])", r"\1\2", out)      # space stranded after a tag
        fixes.append(f"trimmed {len(tags) - max_hashtags} hashtag(s) over the limit of {max_hashtags}")
    elif not tags:
        problems.append("no hashtags — the prompt asks every caption to end with about 5")

    lowered = out.lower()
    for phrase in _CHATTER:
        if phrase in lowered:
            problems.append(f"reads like a reply to the operator, not a caption: {phrase!r}")

    # Trailing whitespace left by removed tags/labels, and any blank run they opened up.
    out = re.sub(r"[ \t]+(\n|$)", r"\1", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    if not out:
        raise DescriptionError("Nothing left after validation — the model returned only scaffolding.")
    return Checked(text=out, fixes=tuple(fixes), problems=tuple(problems))


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
