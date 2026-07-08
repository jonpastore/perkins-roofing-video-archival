"""Pure word-highlight (karaoke) caption builder — no I/O, deterministic.

Track A3: groups Whisper word-level timestamps into caption cue lines and renders
them as ASS karaoke (\\k tags) or plain SRT.  All functions are pure; the ffmpeg
burn step that consumes caption_events() lives at the adapter/job boundary.

Caption/social text must pass adapters.safety.run_gate before publish (Track E).
"""
from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_MAX_CHARS: int = 32   # chars per caption line (sweet spot for 9:16 reels)
DEFAULT_MAX_DUR: float = 3.0  # seconds per caption line

# ---------------------------------------------------------------------------
# ASS style templates (two brand styles)
# ---------------------------------------------------------------------------

# Style fields: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,
# OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,
# ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,
# Alignment, MarginL, MarginR, MarginV, Encoding
_ASS_STYLES: dict[str, str] = {
    "default": (
        "Style: Default,Arial,48,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,"
        "1,0,0,0,100,100,0,0,1,3,1,2,10,10,30,1"
    ),
    "bold_yellow": (
        "Style: BoldYellow,Arial Black,52,&H0000FFFF,&H00FFFFFF,&H00000000,&H80000000,"
        "1,0,0,0,100,100,0,0,1,3,1,2,10,10,30,1"
    ),
}

_ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, \
BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, \
BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style_line}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_ts(seconds: float) -> str:
    """Convert float seconds to ASS timestamp H:MM:SS.cc."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - math.floor(seconds)) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _srt_ts(seconds: float) -> str:
    """Convert float seconds to SRT timestamp HH:MM:SS,mmm."""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - math.floor(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------------------------------------------------------------------
# Core grouping
# ---------------------------------------------------------------------------


def group_caption_lines(
    words: list[dict],
    max_chars: int = DEFAULT_MAX_CHARS,
    max_dur: float = DEFAULT_MAX_DUR,
) -> list[dict]:
    """Group words into caption cue lines respecting character and duration limits.

    Each word dict must carry ``word`` (str), ``start`` (float), ``end`` (float).
    Extra keys are ignored.

    A new line begins when adding the next word would exceed ``max_chars`` characters
    (including joining space) OR when the line's duration would exceed ``max_dur`` seconds.

    Returns a list of line dicts::

        {
            "text":  str,           # joined words with single spaces
            "start": float,         # start time of first word
            "end":   float,         # end time of last word
            "words": list[dict],    # original word dicts in this line
        }

    Empty or whitespace-only words are skipped.  Returns ``[]`` for empty input.
    """
    if not words:
        return []

    lines: list[dict] = []
    cur_words: list[dict] = []
    cur_text = ""

    for w in words:
        word_str = str(w.get("word") or "").strip()
        if not word_str:
            continue
        w_start = float(w.get("start") or 0.0)
        w_end = float(w.get("end") or w_start)

        candidate = (cur_text + " " + word_str).strip() if cur_text else word_str
        line_start = float(cur_words[0].get("start") or 0.0) if cur_words else w_start
        line_dur = w_end - line_start

        if cur_words and (len(candidate) > max_chars or line_dur > max_dur):
            # Flush current line
            lines.append(_make_line(cur_words, cur_text))
            cur_words = []
            cur_text = ""
            candidate = word_str

        cur_words.append(w)
        cur_text = candidate

    if cur_words:
        lines.append(_make_line(cur_words, cur_text))

    return lines


def _make_line(words: list[dict], text: str) -> dict:
    last = words[-1]
    last_start = float(last.get("start") or 0.0)
    last_end = float(last.get("end") or last_start)
    return {
        "text": text,
        "start": float(words[0].get("start") or 0.0),
        "end": last_end,
        "words": list(words),
    }


# ---------------------------------------------------------------------------
# Structured cue list for ffmpeg
# ---------------------------------------------------------------------------


def caption_events(
    words: list[dict],
    max_chars: int = DEFAULT_MAX_CHARS,
    max_dur: float = DEFAULT_MAX_DUR,
) -> list[dict]:
    """Return structured caption cue list suitable for an ffmpeg burn step.

    Calls ``group_caption_lines`` and enriches each line with per-word timing
    offsets (centiseconds from line start) for karaoke highlight rendering.

    Each returned event dict::

        {
            "text":    str,
            "start":   float,
            "end":     float,
            "words": [
                {"word": str, "start": float, "end": float,
                 "k_cs": int},   # karaoke delay in centiseconds from line start
                ...
            ],
        }

    ``k_cs`` is the cumulative start offset of the word from the line's start,
    in centiseconds (ASS \\k unit).
    """
    lines = group_caption_lines(words, max_chars=max_chars, max_dur=max_dur)
    events: list[dict] = []
    for line in lines:
        line_start = line["start"]
        enriched_words = []
        for w in line["words"]:
            w_start = float(w.get("start") or 0.0)
            k_cs = max(0, int(round((w_start - line_start) * 100)))
            enriched_words.append({
                "word": str(w.get("word") or "").strip(),
                "start": w_start,
                "end": float(w.get("end") or w_start),
                "k_cs": k_cs,
            })
        events.append({
            "text": line["text"],
            "start": line["start"],
            "end": line["end"],
            "words": enriched_words,
        })
    return events


# ---------------------------------------------------------------------------
# ASS karaoke renderer
# ---------------------------------------------------------------------------


def to_ass_karaoke(lines: list[dict], style: str = "default") -> str:
    """Render caption lines as an ASS subtitle file with per-word \\k karaoke tags.

    ``lines`` is the output of ``group_caption_lines()`` or equivalent.
    ``style`` must be one of ``'default'`` or ``'bold_yellow'``.

    Each word gets an ``\\k<cs>`` tag (centisecond duration until next word highlight).
    The ASS file targets a 1080x1920 (9:16) canvas.

    Returns the full ASS file content as a string.
    """
    style_key = style if style in _ASS_STYLES else "default"
    style_line = _ASS_STYLES[style_key]
    style_name = style_line.split(",")[0].replace("Style: ", "")

    header = _ASS_HEADER.format(style_line=style_line)
    dialogue_lines: list[str] = []

    for line in lines:
        start_ts = _ass_ts(line["start"])
        end_ts = _ass_ts(line["end"])
        words = line.get("words", [])

        if not words:
            text_body = line.get("text", "")
        else:
            # Build karaoke text: each word preceded by \k<duration_cs>
            # Duration for word i = start of word(i+1) - start of word(i), in cs.
            # Last word: line end - word start.
            parts: list[str] = []
            for i, w in enumerate(words):
                w_start = float(w.get("start") or line["start"])
                if i + 1 < len(words):
                    next_start = float(words[i + 1].get("start") or w_start)
                else:
                    next_start = line["end"]
                dur_cs = max(1, int(round((next_start - w_start) * 100)))
                word_str = str(w.get("word") or "").strip()
                parts.append(f"{{\\k{dur_cs}}}{word_str}")
            text_body = " ".join(parts)

        dialogue_lines.append(
            f"Dialogue: 0,{start_ts},{end_ts},{style_name},,0,0,0,,{text_body}"
        )

    return header + "\n".join(dialogue_lines) + "\n"


# ---------------------------------------------------------------------------
# SRT renderer
# ---------------------------------------------------------------------------


def to_srt(lines: list[dict]) -> str:
    """Render caption lines as a plain SRT subtitle string.

    ``lines`` is the output of ``group_caption_lines()`` or equivalent.
    No karaoke tags — straight text cues, sequentially numbered.

    Returns the full SRT content as a string (UTF-8 safe).
    """
    if not lines:
        return ""

    blocks: list[str] = []
    for i, line in enumerate(lines, start=1):
        start_ts = _srt_ts(line["start"])
        end_ts = _srt_ts(line["end"])
        text = line.get("text", "")
        blocks.append(f"{i}\n{start_ts} --> {end_ts}\n{text}\n")

    return "\n".join(blocks)
