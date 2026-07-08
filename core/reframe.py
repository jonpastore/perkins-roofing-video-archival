"""Pure 9:16 reframe + active-speaker tracking builders — no I/O, deterministic.

Track A2: Builds ffmpeg crop filtergraphs for 9:16 (and other) target ratios,
smooths per-segment active-speaker x-positions into pan-safe crop keyframes,
and assembles final ffmpeg arg lists for reframe jobs.

No subprocess calls here.  All execution lives in adapters/.
Coverage target: 100%.

Real MediaPipe / TalkNet speaker-detector implementations belong in adapters/;
see the ``SpeakerDetector`` protocol below for the expected interface.
"""
from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Supported target aspect ratios
# ---------------------------------------------------------------------------

_RATIO_DIMENSIONS: dict[str, tuple[float, float]] = {
    "9:16": (9.0, 16.0),
    "1:1": (1.0, 1.0),
    "4:5": (4.0, 5.0),
}

_VALID_RATIOS: frozenset[str] = frozenset(_RATIO_DIMENSIONS)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

# Maximum pan speed: fraction of *crop-width* per second.  Keeps the eye from
# whiplashing when a speaker changes sides quickly.
DEFAULT_MAX_PAN_SPEED: float = 0.15

# ---------------------------------------------------------------------------
# crop_filter_9x16
# ---------------------------------------------------------------------------


def crop_filter_9x16(
    src_w: int,
    src_h: int,
    focus_x: float | None = None,
    *,
    ratio: str = "9:16",
) -> str:
    """Return an ffmpeg ``crop`` filter expression for *ratio* from a source frame.

    The crop window is sized so the output exactly matches *ratio* without
    upscaling: the smaller of the two constrained dimensions is used.

    For a typical 1920×1080 source and ratio ``"9:16"``:
    * The 9:16 crop height is capped at src_h (1080).
    * The corresponding width = 1080 * 9/16 = 607.5 → 607 (truncated to even).

    If *focus_x* is given (normalised 0..1, where 0=left edge, 1=right edge),
    the crop window is centred on that x position (clamped so the window stays
    within the frame).  Without *focus_x* the window is centre-cropped.

    Args:
        src_w:   Source frame width in pixels.
        src_h:   Source frame height in pixels.
        focus_x: Optional normalised x position (0.0–1.0) of the active speaker
                 to centre the crop window on.
        ratio:   Target aspect ratio — one of ``"9:16"`` (default), ``"1:1"``,
                 ``"4:5"``.

    Returns:
        An ffmpeg ``crop`` filter string, e.g.
        ``"crop=607:1080:656:0"``  (w:h:x:y).

    Raises:
        ValueError: if *ratio* is not a supported value.
        ValueError: if *src_w* or *src_h* is ≤ 0.
    """
    if ratio not in _VALID_RATIOS:
        raise ValueError(
            f"Unsupported ratio {ratio!r}. Choose from: {sorted(_VALID_RATIOS)}"
        )
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"src_w and src_h must be positive, got {src_w}×{src_h}")

    r_w, r_h = _RATIO_DIMENSIONS[ratio]

    # Determine crop dimensions — largest window that fits inside src and matches ratio.
    # Option A: full height, constrained width.
    cw_from_h = int(src_h * r_w / r_h)
    # Option B: full width, constrained height.
    ch_from_w = int(src_w * r_h / r_w)

    if cw_from_h <= src_w:
        # Height is the binding constraint.
        crop_w = cw_from_h
        crop_h = src_h
    else:
        # Width is the binding constraint.
        crop_w = src_w
        crop_h = ch_from_w

    # Make crop dimensions even (required by most codecs).
    crop_w = crop_w - (crop_w % 2)
    crop_h = crop_h - (crop_h % 2)

    # Determine crop x origin.
    if focus_x is not None:
        # Centre the window on focus_x (normalised → pixels).
        centre_px = int(focus_x * src_w)
        x = centre_px - crop_w // 2
        # Clamp so the window stays within [0, src_w - crop_w].
        x = max(0, min(x, src_w - crop_w))
    else:
        x = (src_w - crop_w) // 2

    # Crop y is always centred vertically.
    y = (src_h - crop_h) // 2

    return f"crop={crop_w}:{crop_h}:{x}:{y}"


# ---------------------------------------------------------------------------
# SpeakerDetector protocol + mock implementation
# ---------------------------------------------------------------------------


@runtime_checkable
class SpeakerDetector(Protocol):
    """Interface for active-speaker detection adapters.

    A concrete implementation (e.g. MediaPipe face-mesh + TalkNet) would
    analyse each video segment and return the normalised x-position (0..1)
    of the dominant speaker's face centre.  This module only defines the
    contract; real implementations live in ``adapters/``.

    TODO: Implement ``adapters/speaker_mediapipe.py`` using MediaPipe face
    detection + TalkNet ASD scoring to produce per-segment x positions.
    """

    def detect(self, video_path: str, segments: list[dict]) -> list[float | None]:
        """Return a list of normalised x-positions for each segment.

        Args:
            video_path: Path to the source video file.
            segments:   List of segment dicts with at least ``"start"`` and
                        ``"end"`` keys (seconds).

        Returns:
            A list of the same length as *segments*.  Each element is either
            a float in 0..1 (speaker detected) or ``None`` (no detection).
        """
        ...


class MockSpeakerDetector:
    """Mock speaker detector that always returns centred positions (0.5).

    Used in tests and as a safe no-op when no real detector is configured.
    Satisfies the ``SpeakerDetector`` protocol.
    """

    def detect(self, video_path: str, segments: list[dict]) -> list[float | None]:
        """Return 0.5 (frame centre) for every segment."""
        return [0.5 for _ in segments]


# ---------------------------------------------------------------------------
# speaker_track_windows
# ---------------------------------------------------------------------------


def speaker_track_windows(
    segments: list[dict],
    *,
    smoothing: float = DEFAULT_MAX_PAN_SPEED,
) -> list[dict]:
    """Convert per-segment active-speaker x-positions into smooth crop keyframes.

    This is a PURE function — it only processes data, never touches the filesystem
    or any detector.  Feed it the OUTPUT of a ``SpeakerDetector.detect()`` call
    (or any equivalent list of per-segment speaker positions) via the ``"x"`` key
    of each segment dict.

    Smoothing works by clamping the pan speed: the crop centre cannot move more
    than ``smoothing`` * crop_width fraction per second between consecutive
    keyframes.  Positions normalised to 0..1 are used throughout (the actual pixel
    clamping happens later in ``crop_filter_9x16``).

    Missing / ``None`` x values fall back to the previous position (or 0.5 if no
    previous position exists), preventing head-cut artefacts at segment boundaries.

    Args:
        segments:  List of dicts, each with:
                   - ``"start"`` (float): segment start time in seconds.
                   - ``"end"``   (float): segment end time in seconds.
                   - ``"x"``     (float | None): normalised speaker x-position.
        smoothing: Maximum position change per second (fraction of frame width,
                   default ``0.15``).  Lower = smoother but slower to follow a
                   speaker who crosses the frame.

    Returns:
        A list of keyframe dicts::

            [
                {"t": float,  # midpoint of the segment (seconds)
                 "x": float}, # smoothed crop-centre position (0..1)
                ...
            ]

        Returns ``[]`` for empty input.

    Raises:
        ValueError: if *smoothing* ≤ 0.
    """
    if smoothing <= 0:
        raise ValueError(f"smoothing must be > 0, got {smoothing!r}")
    if not segments:
        return []

    keyframes: list[dict] = []
    prev_x: float = 0.5
    prev_t: float | None = None

    for seg in segments:
        start = float(seg.get("start") or 0.0)
        end = float(seg.get("end") or start)
        t = (start + end) / 2.0

        raw_x = seg.get("x")
        if raw_x is None:
            target_x = prev_x
        else:
            target_x = float(raw_x)
            # Clamp to [0, 1].
            target_x = max(0.0, min(1.0, target_x))

        # Clamp pan speed: limit how far x can move from the previous position.
        if prev_t is not None:
            dt = t - prev_t
            if dt > 0:
                max_delta = smoothing * dt
                delta = target_x - prev_x
                if abs(delta) > max_delta:
                    target_x = prev_x + max_delta * (1.0 if delta > 0 else -1.0)
            # If dt == 0 (duplicate timestamp), keep previous position.
            else:
                target_x = prev_x

        keyframes.append({"t": t, "x": target_x})
        prev_x = target_x
        prev_t = t

    return keyframes


# ---------------------------------------------------------------------------
# build_reframe_cmd
# ---------------------------------------------------------------------------

_FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")

# Hard encode timeout matching adapters/ffmpeg.py.
_ENCODE_TIMEOUT = 1200


def build_reframe_cmd(
    in_path: str,
    out_path: str,
    windows: list[dict],
    *,
    ratio: str = "9:16",
    src_w: int = 1920,
    src_h: int = 1080,
) -> list[str]:
    """Build an ffmpeg arg list that reframes *in_path* to *ratio* with optional pan.

    When *windows* is empty, a static centre-crop is applied (no animation).
    When *windows* is non-empty each keyframe drives a ``crop`` filter with
    ``x`` animated via the ``eval=frame`` mode and an ffmpeg ``if``/``between``
    expression so each keyframe's position holds until the next one begins.

    The output is 1080×1920 for 9:16, 1080×1080 for 1:1, or 1080×1350 for 4:5
    (always 1080 wide; height follows the ratio).

    Args:
        in_path:  Path to the source video.
        out_path: Destination path (MP4).
        windows:  Keyframe list from :func:`speaker_track_windows`
                  (each dict has ``"t"`` and ``"x"``).  Empty → centre-crop.
        ratio:    Target aspect ratio (``"9:16"``, ``"1:1"``, or ``"4:5"``).
        src_w:    Source frame width in pixels (default 1920).
        src_h:    Source frame height in pixels (default 1080).

    Returns:
        A ``list[str]`` ready to pass to ``subprocess.run``.

    Raises:
        ValueError: if *ratio* is unsupported.
    """
    if ratio not in _VALID_RATIOS:
        raise ValueError(
            f"Unsupported ratio {ratio!r}. Choose from: {sorted(_VALID_RATIOS)}"
        )

    r_w, r_h = _RATIO_DIMENSIONS[ratio]

    # Compute output dimensions: fix width at 1080, derive height.
    out_w = 1080
    out_h = int(out_w * r_h / r_w)
    out_h = out_h - (out_h % 2)  # even

    # Compute crop dimensions from source.
    crop_filter = crop_filter_9x16(src_w, src_h, ratio=ratio)
    # Extract crop_w from "crop=W:H:X:Y"
    parts = crop_filter[len("crop="):].split(":")
    crop_w = int(parts[0])
    crop_h = int(parts[1])

    if not windows:
        # Static centre crop — use the pre-built filter string directly.
        vf = f"{crop_filter},scale={out_w}:{out_h}"
    else:
        # Animated crop: build an expression for x that steps through keyframes.
        # For each keyframe i, x = keyframe[i].x * (src_w - crop_w) while t is in
        # [t_i, t_{i+1}).  We build nested if(between(t,...)) expressions.
        # The default (outermost else) is the last keyframe position.
        x_expr = _build_x_expr(windows, src_w, crop_w)
        # Crop filter with per-frame eval and animated x.
        vf = (
            f"crop={crop_w}:{crop_h}:{x_expr}:0:exact=1,"
            f"scale={out_w}:{out_h}"
        )

    cmd = [
        _FFMPEG, "-y",
        "-i", in_path,
        "-vf", vf,
        "-c:v", "libx264",
        "-crf", "18",
        "-preset", "fast",
        "-c:a", "copy",
        out_path,
    ]
    return cmd


def _build_x_expr(windows: list[dict], src_w: int, crop_w: int) -> str:
    """Build an ffmpeg ``x`` expression for a stepped animated crop.

    Each keyframe holds its position until the next keyframe begins.
    The final keyframe's position is used for all time beyond it.

    The expression uses nested ``if(lte(t,T),X_px,...)`` so ffmpeg evaluates
    each keyframe in order and stops at the first match.
    """
    max_x = src_w - crop_w

    def _x_px(norm_x: float) -> int:
        return max(0, min(int(norm_x * src_w) - crop_w // 2, max_x))

    # Build from the last keyframe backwards so the innermost value is the last.
    expr = str(_x_px(windows[-1]["x"]))
    for kf in reversed(windows[:-1]):
        x_px = _x_px(kf["x"])
        expr = f"if(lte(t,{kf['t']:.6f}),{x_px},{expr})"
    return expr
