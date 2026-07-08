"""Pure speech-cleanup helpers — filler-word / stutter removal.

Track A6: given Whisper word-level timestamps, produces time ranges to cut and
the ffmpeg argument list that applies those cuts.  All functions are pure; the
subprocess call lives at the adapter/job boundary.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_FILLERS: frozenset[str] = frozenset({
    "um", "uh", "er", "ah", "hmm", "like", "you know",
})

# Pad (seconds) applied around each keep segment so cuts are not abrupt.
DEFAULT_PAD: float = 0.05


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\s]")


def _normalise(word: str) -> str:
    """Lower-case and strip punctuation so 'Um,' matches 'um'."""
    return _PUNCT_RE.sub("", word).strip().lower()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_fillers(
    words: list[dict],
    *,
    fillers: frozenset[str] | set[str] | None = None,
) -> list[dict]:
    """Return time ranges that should be CUT from the audio.

    Detects two classes of unwanted speech:

    1. **Single-word fillers** — any word whose normalised form appears in
       *fillers* (default: um, uh, er, ah, hmm, like, you know).
    2. **Multi-word phrase fillers** — consecutive words that, when joined,
       match a multi-word filler string (e.g. "you know").
    3. **Immediate stutter repeats** — a word that is identical (after
       normalisation) to the immediately preceding word.

    Args:
        words:   List of Whisper word dicts, each with ``word`` (str),
                 ``start`` (float), ``end`` (float).
        fillers: Override the default filler set.  Pass an empty set to
                 disable filler detection while still catching stutters.

    Returns:
        List of ``{"start": float, "end": float}`` dicts, one per cut range,
        in the order they appear in the transcript.  Ranges do not overlap.
    """
    if fillers is None:
        fillers = DEFAULT_FILLERS

    # Separate single-word from multi-word fillers.
    single_fillers: set[str] = {f for f in fillers if len(f.split()) == 1}
    multi_fillers: list[list[str]] = sorted(
        [f.split() for f in fillers if len(f.split()) > 1],
        key=len,
        reverse=True,  # try longest match first
    )

    cut_ranges: list[dict] = []
    n = len(words)
    prev_norm: str = ""

    i = 0
    while i < n:
        w = words[i]
        norm = _normalise(str(w.get("word") or ""))
        if not norm:
            i += 1
            continue

        # --- multi-word filler match (greedy, longest first) ---------------
        matched_multi = False
        for phrase_tokens in multi_fillers:
            plen = len(phrase_tokens)
            if i + plen > n:
                continue
            candidate_norms = [
                _normalise(str(words[i + k].get("word") or ""))
                for k in range(plen)
            ]
            if candidate_norms == phrase_tokens:
                start = float(words[i].get("start") or 0.0)
                end = float(words[i + plen - 1].get("end") or start)
                cut_ranges.append({"start": start, "end": end})
                prev_norm = _normalise(str(words[i + plen - 1].get("word") or ""))
                i += plen
                matched_multi = True
                break

        if matched_multi:
            continue

        # --- single-word filler --------------------------------------------
        if norm in single_fillers:
            start = float(w.get("start") or 0.0)
            end = float(w.get("end") or start)
            cut_ranges.append({"start": start, "end": end})
            prev_norm = norm
            i += 1
            continue

        # --- immediate stutter repeat --------------------------------------
        if norm == prev_norm:
            start = float(w.get("start") or 0.0)
            end = float(w.get("end") or start)
            cut_ranges.append({"start": start, "end": end})
            # prev_norm stays the same (consecutive triple stutter is handled)
            i += 1
            continue

        prev_norm = norm
        i += 1

    return cut_ranges


def keep_segments(
    duration: float,
    cut_ranges: list[dict],
    *,
    pad: float = DEFAULT_PAD,
) -> list[dict]:
    """Invert cut ranges into keep segments.

    Each cut range is expanded inward by *pad* seconds so the audio fades
    into/out of cuts without an abrupt click.  Adjacent keeps whose gap would
    be ≤ 0 after padding are merged.

    Args:
        duration:   Total clip duration in seconds.
        cut_ranges: Output of :func:`detect_fillers` (``start``/``end`` dicts).
        pad:        Seconds to shrink each keep segment boundary toward the cut.

    Returns:
        List of ``{"start": float, "end": float}`` keep-segment dicts in
        chronological order.  Returns ``[{"start": 0.0, "end": duration}]``
        when *cut_ranges* is empty.
    """
    if not cut_ranges:
        return [{"start": 0.0, "end": duration}]

    # Sort cuts so we can iterate in order.
    cuts = sorted(cut_ranges, key=lambda c: c["start"])

    raw_keeps: list[tuple[float, float]] = []
    cursor = 0.0
    for cut in cuts:
        cut_start = float(cut["start"])
        cut_end = float(cut["end"])
        keep_end = cut_start - pad
        keep_start = cursor + pad if cursor > 0.0 else cursor
        if keep_end > keep_start:
            raw_keeps.append((keep_start, keep_end))
        cursor = cut_end

    # Trailing segment after last cut
    final_start = cursor + pad if cursor > 0.0 else cursor
    if final_start < duration:
        raw_keeps.append((final_start, duration))

    if not raw_keeps:
        return [{"start": 0.0, "end": duration}]

    return [{"start": s, "end": e} for s, e in raw_keeps]


def build_cleanup_cmd(
    in_path: str,
    out_path: str,
    keep_segs: list[dict],
) -> list[str]:
    """Build an ffmpeg argument list that concatenates *keep_segs* into *out_path*.

    Uses the ``select``/``aselect`` trim-and-concat approach so no intermediate
    files are needed.  Each keep segment is expressed as a time-range condition
    inside a ``select`` expression; segments are then concatenated with the
    ``concat`` filter.

    Args:
        in_path:    Source video file path.
        out_path:   Destination file path (overwritten if it exists).
        keep_segs:  Output of :func:`keep_segments`.

    Returns:
        A ``list[str]`` suitable for passing directly to
        ``subprocess.run(cmd, ...)``.
    """
    n = len(keep_segs)

    if n == 1:
        # Optimisation: single keep → plain trim, no concat needed.
        seg = keep_segs[0]
        s = seg["start"]
        e = seg["end"]
        filter_complex = (
            f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[v0];"
            f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[a0]"
        )
        return [
            "ffmpeg", "-y",
            "-i", in_path,
            "-filter_complex", filter_complex,
            "-map", "[v0]",
            "-map", "[a0]",
            "-c:v", "libx264", "-c:a", "aac",
            out_path,
        ]

    # Multiple keeps → trim each then concat.
    filter_parts: list[str] = []
    v_labels: list[str] = []
    a_labels: list[str] = []

    for idx, seg in enumerate(keep_segs):
        s = seg["start"]
        e = seg["end"]
        vl = f"v{idx}"
        al = f"a{idx}"
        filter_parts.append(
            f"[0:v]trim=start={s}:end={e},setpts=PTS-STARTPTS[{vl}]"
        )
        filter_parts.append(
            f"[0:a]atrim=start={s}:end={e},asetpts=PTS-STARTPTS[{al}]"
        )
        v_labels.append(f"[{vl}]")
        a_labels.append(f"[{al}]")

    concat_inputs = "".join(v_labels + a_labels)
    filter_parts.append(
        f"{concat_inputs}concat=n={n}:v=1:a=1[vout][aout]"
    )
    filter_complex = ";".join(filter_parts)

    return [
        "ffmpeg", "-y",
        "-i", in_path,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264", "-c:a", "aac",
        out_path,
    ]
