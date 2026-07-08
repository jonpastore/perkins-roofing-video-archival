"""Pure clip-effects builders — no I/O, deterministic. Coverage target: 100%.

A9  TRANSITIONS: xfade-based transitions between two clips, plus a concat helper
    for N clips with transitions between each pair.
A10 OVERLAYS: overlay filter compositing one or more PNG images (with alpha) at
    specified x/y positions and time windows.
A11 FLOATING TEXT: drawtext-based positioned/animated text overlays, reusing the
    exact apostrophe-safe escaping from adapters/ffmpeg.py (the ``'\\''`` sequence
    + ``expansion=none``).

No subprocess calls here.  All execution lives in adapters/.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# A9 — Transitions
# ---------------------------------------------------------------------------

TransitionKind = Literal["fade", "wipe", "slide", "dissolve"]

_VALID_TRANSITIONS: frozenset[str] = frozenset({"fade", "wipe", "slide", "dissolve"})

# Map our friendly names to ffmpeg xfade transition identifiers.
_XFADE_MAP: dict[str, str] = {
    "fade": "fade",
    "wipe": "wipeleft",
    "slide": "slideleft",
    "dissolve": "dissolve",
}


def build_transition_filter(
    duration: float,
    offset: float,
    kind: str = "fade",
    *,
    clip_a_stream: str = "0:v",
    clip_b_stream: str = "1:v",
    out_label: str = "vout",
) -> str:
    """Return a ``-filter_complex`` string for an xfade transition between two clips.

    The two video inputs are connected with ``xfade`` at *offset* seconds into
    the first clip for *duration* seconds.  Audio is not handled here — callers
    are responsible for audio concat separately.

    Args:
        duration:       Transition duration in seconds (e.g. ``0.5``).
        offset:         Offset into the *first* clip (seconds) where the transition
                        begins — must be ≥ 0 and less than clip A's total duration.
        kind:           Transition style: ``"fade"``, ``"wipe"``, ``"slide"``,
                        ``"dissolve"`` (default ``"fade"``).
        clip_a_stream:  ffmpeg stream specifier for clip A video (default ``"0:v"``).
        clip_b_stream:  ffmpeg stream specifier for clip B video (default ``"1:v"``).
        out_label:      Name of the output stream label (default ``"vout"``).

    Returns:
        A ``-filter_complex`` string.

    Raises:
        ValueError: if *kind* is not one of the supported transition types.
    """
    if kind not in _VALID_TRANSITIONS:
        raise ValueError(
            f"Unsupported transition kind {kind!r}. "
            f"Choose from: {sorted(_VALID_TRANSITIONS)}"
        )
    xfade_name = _XFADE_MAP[kind]
    return (
        f"[{clip_a_stream}][{clip_b_stream}]"
        f"xfade=transition={xfade_name}:duration={duration:.6f}:offset={offset:.6f}"
        f"[{out_label}]"
    )


def build_concat_with_transitions(
    n_clips: int,
    transition_duration: float,
    clip_durations: list[float],
    kind: str = "fade",
) -> str:
    """Return a ``-filter_complex`` string that chains N clips with xfade transitions.

    Each consecutive pair of clips is joined with an xfade transition.  The
    offset for each transition is computed as::

        offset = sum(clip_durations[:i]) - transition_duration * i

    so that the transitions overlap the clip boundaries evenly.

    Args:
        n_clips:             Number of input clips (must be ≥ 2).
        transition_duration: Duration of each transition in seconds.
        clip_durations:      List of durations for each clip, in order.
                             Length must equal *n_clips*.
        kind:                Transition style (same options as
                             :func:`build_transition_filter`).

    Returns:
        A ``-filter_complex`` string with all xfade nodes chained.

    Raises:
        ValueError: if *n_clips* < 2, ``len(clip_durations) != n_clips``,
                    or *kind* is unsupported.
    """
    if n_clips < 2:
        raise ValueError(f"n_clips must be ≥ 2, got {n_clips}")
    if len(clip_durations) != n_clips:
        raise ValueError(
            f"clip_durations length {len(clip_durations)} != n_clips {n_clips}"
        )
    if kind not in _VALID_TRANSITIONS:
        raise ValueError(
            f"Unsupported transition kind {kind!r}. "
            f"Choose from: {sorted(_VALID_TRANSITIONS)}"
        )

    xfade_name = _XFADE_MAP[kind]
    parts: list[str] = []

    # After each xfade, the output label feeds the *next* xfade as its first input.
    prev_label = "0:v"
    running_offset = 0.0

    for i in range(1, n_clips):
        # Offset = start of clip[i-1] relative to the global timeline minus accumulated
        # transition time already subtracted by earlier transitions.
        running_offset += clip_durations[i - 1] - transition_duration
        out_label = f"xf{i}" if i < n_clips - 1 else "vout"
        next_stream = f"{i}:v"
        parts.append(
            f"[{prev_label}][{next_stream}]"
            f"xfade=transition={xfade_name}:"
            f"duration={transition_duration:.6f}:"
            f"offset={running_offset:.6f}"
            f"[{out_label}]"
        )
        prev_label = out_label

    return ";".join(parts)


# ---------------------------------------------------------------------------
# A10 — Overlays
# ---------------------------------------------------------------------------


@dataclass
class OverlaySpec:
    """Spec for a single image overlay composited onto the video.

    Args:
        image_path: Path to a PNG image (should have alpha channel).
        x:          Horizontal position expression (ffmpeg overlay ``x``
                    parameter, e.g. ``"10"``, ``"W-w-10"``).
        y:          Vertical position expression (e.g. ``"10"``).
        start:      Overlay start time in seconds (0 = from the beginning).
        end:        Overlay end time in seconds (None = until clip end).
    """

    image_path: str
    x: str = "10"
    y: str = "10"
    start: float = 0.0
    end: float | None = None


def build_overlay_filter(
    overlays: list[OverlaySpec],
    *,
    base_stream: str = "0:v",
) -> str:
    """Return a ``-filter_complex`` string compositing all *overlays* onto the base video.

    Each overlay image must be passed as a separate ffmpeg input (input index 1, 2, …
    for the first, second, … overlay).  The base video is *base_stream* (default ``"0:v"``).

    The filter chains overlay nodes sequentially:
    ``base → overlay(img1) → overlay(img2) → … → [vout]``

    Each overlay node uses ``enable='between(t,start,end)'`` to constrain the
    visible time window; when ``end`` is ``None`` the enable expression is omitted
    (overlay is visible for the full duration).

    Args:
        overlays:    List of :class:`OverlaySpec` instances (must be non-empty).
        base_stream: ffmpeg stream specifier for the base video.

    Returns:
        A ``-filter_complex`` string.

    Raises:
        ValueError: if *overlays* is empty.
    """
    if not overlays:
        raise ValueError("overlays list must not be empty")

    parts: list[str] = []
    prev_label = base_stream

    for idx, ov in enumerate(overlays):
        img_stream = f"{idx + 1}:v"
        out_label = f"ov{idx}" if idx < len(overlays) - 1 else "vout"

        if ov.end is not None:
            enable = f":enable='between(t,{ov.start:.6f},{ov.end:.6f})'"
        else:
            enable = ""

        parts.append(
            f"[{prev_label}][{img_stream}]overlay=x={ov.x}:y={ov.y}{enable}[{out_label}]"
        )
        prev_label = out_label

    return ";".join(parts)


# ---------------------------------------------------------------------------
# A11 — Floating text
# ---------------------------------------------------------------------------


@dataclass
class TextOverlaySpec:
    """Spec for a single drawtext overlay.

    Args:
        text:      The text to display.  Apostrophes and filtergraph metacharacters
                   are escaped automatically by :func:`build_floating_text_filter`.
        x:         Horizontal position expression (default ``"(w-text_w)/2"``).
        y:         Vertical position expression (default ``"(h-text_h)/2"``).
        start:     Display start time in seconds.
        end:       Display end time in seconds.
        fontsize:  Font size in pixels (default ``48``).
        fontcolor: Font colour string (default ``"white"``).
        box:       Whether to draw a background box behind the text (default ``False``).
        boxcolor:  Box colour with optional alpha (default ``"black@0.5"``).
        boxborderw: Box border/padding width in pixels (default ``5``).
        fontfile:  Optional path to a .ttf font file.
    """

    text: str
    x: str = "(w-text_w)/2"
    y: str = "(h-text_h)/2"
    start: float = 0.0
    end: float = 3.0
    fontsize: int = 48
    fontcolor: str = "white"
    box: bool = False
    boxcolor: str = "black@0.5"
    boxborderw: int = 5
    fontfile: str = ""


def _escape_drawtext(text: str) -> str:
    """Escape *text* for safe embedding inside an ffmpeg drawtext filter value.

    Replicates the exact escaping from ``adapters/ffmpeg.py::make_card``:

    - The text is single-quoted in the filter string (``text='...'``).
    - Apostrophes are written as the ``'\\''`` sequence (close-quote, literal
      single-quote, reopen-quote) so titles like ``"Tim's"`` render correctly
      without breaking the single-quoted value.
    - ``expansion=none`` is always appended to prevent drawtext from
      interpreting ``%`` and ``\\`` sequences.

    Filtergraph structural metacharacters (``:`` ``,`` ``;`` ``[`` ``]``) are
    *not* shell-escaped here — they are safely contained inside the single-quoted
    value and expansion=none further neutralises any remaining expansion.

    Returns:
        The escaped text (without surrounding quotes — the caller wraps it).
    """
    return text.replace("'", "'\\''")


def build_floating_text_filter(
    specs: list[TextOverlaySpec],
    *,
    base_stream: str = "0:v",
) -> str:
    """Return a ``-vf`` / ``-filter_complex`` value for one or more drawtext overlays.

    When there is a single spec the returned string is suitable as a ``-vf``
    value.  When there are multiple specs they are comma-joined (all drawtext
    filters sharing the same ``-vf`` chain).

    Each drawtext node includes ``expansion=none`` to prevent ``%``/``\\``
    expansion, matching the approach in ``adapters/ffmpeg.py``.

    Args:
        specs:       One or more :class:`TextOverlaySpec` instances.
        base_stream: Unused for ``-vf`` chains; provided for API symmetry and
                     future filter_complex integration.

    Returns:
        A ``-vf`` filter string (comma-joined drawtext nodes).

    Raises:
        ValueError: if *specs* is empty.
    """
    if not specs:
        raise ValueError("specs list must not be empty")

    nodes: list[str] = []
    for spec in specs:
        escaped = _escape_drawtext(spec.text)
        parts = [
            f"drawtext=text='{escaped}'",
            "expansion=none",
            f"fontsize={spec.fontsize}",
            f"fontcolor={spec.fontcolor}",
            f"x={spec.x}",
            f"y={spec.y}",
            f"enable='between(t,{spec.start:.6f},{spec.end:.6f})'",
        ]
        if spec.box:
            parts += [
                "box=1",
                f"boxcolor={spec.boxcolor}",
                f"boxborderw={spec.boxborderw}",
            ]
        if spec.fontfile:
            parts.append(f"fontfile={spec.fontfile}")
        nodes.append(":".join(parts))

    return ",".join(nodes)
