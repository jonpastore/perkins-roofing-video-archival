"""Pure speaker-tracking crop helpers — no I/O, deterministic. Coverage target: 100%.

Item 7: Face-centroid tracking for 9:16 reframe.

This module provides the pure-core side of speaker-tracking reframe:
  - ``smooth_centroids``: applies exponential smoothing + max-pan-speed clamping
    to a sequence of per-frame (or per-segment) face centroids so the crop window
    follows the speaker without whiplash.
  - ``build_tracking_crop_filter``: converts smoothed centroids into an ffmpeg
    ``crop`` vf filter expression with a stepped or constant x offset.

Dependency decision (Item 7 flag):
    Neither ``mediapipe`` nor ``opencv-python-headless`` is installed in the
    project venv.  Installing either adds ≥ 100 MB of compiled binaries.
    Rather than silently add that weight, the DETECTOR SEAM is left as a
    documented ``FaceDetector`` protocol (same pattern as core.reframe's
    ``SpeakerDetector``).  Callers that want real face detection should
    implement ``adapters/speaker_detector.py`` using one of:

        Option A (lighter):  ``opencv-python-headless`` DNN face detector
                             (Caffe/TF model ~10 MB, CPU-only, no GPU required).
        Option B (richer):   ``mediapipe`` Face Detection or Face Mesh
                             (GPU optional, CPU-feasible for 1080p).

    Until then, the ``NullFaceDetector`` is used, which returns ``None`` for
    every segment — falling through to the existing centre-crop path in
    render_job.py (no regression).

    The spec flag ``speaker_tracking`` is OFF by default; render_job.py only
    enters this path when the flag is enabled AND a real detector is wired.

No subprocess calls here.  All ffmpeg execution lives in adapters/.
"""
from __future__ import annotations

import os
from typing import Protocol, runtime_checkable  # noqa: F401 (Protocol used at runtime via isinstance)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum pan speed: fraction of crop-width per second.  Prevents whiplash when
# the speaker crosses the frame between segments.
DEFAULT_MAX_PAN_SPEED: float = 0.2

# EMA smoothing factor (0 < alpha ≤ 1): higher = more responsive, lower = smoother.
DEFAULT_EMA_ALPHA: float = 0.3

_FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")


# ---------------------------------------------------------------------------
# FaceDetector protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class FaceDetector(Protocol):
    """Interface for per-segment face-centroid detectors.

    Concrete implementations live in ``adapters/`` (e.g.
    ``adapters/speaker_detector.py``).  This module only defines the contract.

    Seam for Item 7:
        Implement this interface using one of:
          - ``cv2.dnn`` + a Caffe face-detection model (opencv-python-headless)
          - ``mediapipe.solutions.face_detection``
        Return the normalised x-position (0 = left, 1 = right) of the dominant
        face centroid sampled at the midpoint of each segment.
    """

    def detect_centroids(
        self,
        video_path: str,
        segments: list[dict],
    ) -> list[float | None]:
        """Return normalised x-centroid (0–1) per segment, or None when undetected.

        Args:
            video_path: Path to the source video file.
            segments:   List of dicts with ``"start"`` and ``"end"`` keys (seconds).

        Returns:
            List of the same length as *segments*; each element is a float in
            [0, 1] or None (no face detected in that segment).
        """
        ...


class NullFaceDetector:
    """No-op detector used when no real detector is wired.

    Returns ``None`` for every segment, which causes the crop pipeline to fall
    back to the centre-crop path (identical to the pre-Item-7 behaviour).

    Satisfies the ``FaceDetector`` protocol.
    """

    def detect_centroids(
        self,
        video_path: str,
        segments: list[dict],
    ) -> list[float | None]:
        return [None for _ in segments]


# ---------------------------------------------------------------------------
# smooth_centroids
# ---------------------------------------------------------------------------


def smooth_centroids(
    raw: list[float | None],
    *,
    ema_alpha: float = DEFAULT_EMA_ALPHA,
    max_pan_speed: float = DEFAULT_MAX_PAN_SPEED,
    timestamps: list[float] | None = None,
) -> list[float]:
    """Smooth a sequence of raw face-centroid x-positions.

    Two-pass smoothing:
      1. Fill ``None`` gaps with the last known value (or 0.5 if no prior value).
      2. Apply exponential moving average (EMA) for intra-segment smoothness.
      3. Clamp the per-step delta to ``max_pan_speed * dt`` (where dt is the
         time between consecutive samples, defaulting to 1.0 s when
         *timestamps* is not supplied) to prevent pan whiplash.

    Args:
        raw:           Per-segment raw centroids from ``FaceDetector.detect_centroids``.
                       ``None`` entries are gap-filled before smoothing.
        ema_alpha:     EMA weight for the current sample (0 < alpha ≤ 1).
                       Higher = more responsive; lower = smoother.
        max_pan_speed: Maximum position change per second as a fraction of
                       frame width.  Applied after EMA.
        timestamps:    Optional list of sample timestamps (seconds) — same length
                       as *raw*.  Used to compute ``dt`` for the pan-speed clamp.
                       When absent each step is treated as 1 second apart.

    Returns:
        A list of the same length as *raw* containing smoothed x-positions in
        [0, 1].  Never contains ``None``.

    Raises:
        ValueError: if *ema_alpha* is outside (0, 1] or *max_pan_speed* ≤ 0.
        ValueError: if *timestamps* is supplied but differs in length from *raw*.
    """
    if not (0 < ema_alpha <= 1.0):
        raise ValueError(f"ema_alpha must be in (0, 1], got {ema_alpha!r}")
    if max_pan_speed <= 0:
        raise ValueError(f"max_pan_speed must be > 0, got {max_pan_speed!r}")
    if timestamps is not None and len(timestamps) != len(raw):
        raise ValueError(
            f"timestamps length {len(timestamps)} != raw length {len(raw)}"
        )
    if not raw:
        return []

    # ── Pass 1: gap-fill ────────────────────────────────────────────────────
    filled: list[float] = []
    last = 0.5
    for v in raw:
        if v is None:
            filled.append(last)
        else:
            v_clamped = max(0.0, min(1.0, float(v)))
            filled.append(v_clamped)
            last = v_clamped

    # ── Pass 2: EMA + pan-speed clamp ───────────────────────────────────────
    smoothed: list[float] = []
    prev = filled[0]
    smoothed.append(prev)

    for i in range(1, len(filled)):
        # EMA
        ema_val = ema_alpha * filled[i] + (1.0 - ema_alpha) * prev

        # Pan-speed clamp
        dt = 1.0
        if timestamps is not None:
            dt = max(1e-6, timestamps[i] - timestamps[i - 1])
        max_delta = max_pan_speed * dt
        delta = ema_val - prev
        if abs(delta) > max_delta:
            ema_val = prev + max_delta * (1.0 if delta > 0.0 else -1.0)

        ema_val = max(0.0, min(1.0, ema_val))
        smoothed.append(ema_val)
        prev = ema_val

    return smoothed


# ---------------------------------------------------------------------------
# build_tracking_crop_filter
# ---------------------------------------------------------------------------


def build_tracking_crop_filter(
    smoothed_x: list[float],
    timestamps: list[float],
    *,
    src_w: int = 1920,
    src_h: int = 1080,
    ratio: str = "9:16",
) -> str:
    """Build an ffmpeg ``crop`` vf filter string with stepped x tracking.

    Converts a list of smoothed centroid x-positions (and their timestamps)
    into a ``crop=W:H:X_EXPR:Y`` filter where ``X_EXPR`` is a nested ffmpeg
    ``if(lte(t,...), x_px, ...)`` expression that steps through each keyframe.

    When *smoothed_x* is empty, falls back to a static centre-crop.

    Args:
        smoothed_x:  Smoothed x-positions from ``smooth_centroids``, one per
                     segment.  Values in [0, 1].
        timestamps:  Segment midpoint timestamps (seconds), same length as
                     *smoothed_x*.
        src_w:       Source frame width in pixels (default 1920).
        src_h:       Source frame height in pixels (default 1080).
        ratio:       Target aspect ratio — ``"9:16"`` (default) or ``"1:1"``.

    Returns:
        An ffmpeg vf filter string, e.g. ``"crop=606:1080:if(lte(t,...),x1,x2):0"``.

    Raises:
        ValueError: if *smoothed_x* and *timestamps* differ in length.
        ValueError: if *ratio* is not supported.
        ValueError: if *src_w* or *src_h* ≤ 0.
    """
    _SUPPORTED_RATIOS = {"9:16", "1:1"}
    if ratio not in _SUPPORTED_RATIOS:
        raise ValueError(f"ratio must be one of {sorted(_SUPPORTED_RATIOS)}, got {ratio!r}")
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"src_w and src_h must be positive, got {src_w}x{src_h}")
    if len(smoothed_x) != len(timestamps):
        raise ValueError(
            f"smoothed_x length {len(smoothed_x)} != timestamps length {len(timestamps)}"
        )

    # Compute crop dimensions from ratio.
    if ratio == "9:16":
        r_w, r_h = 9.0, 16.0
    else:  # "1:1"
        r_w, r_h = 1.0, 1.0

    cw_from_h = int(src_h * r_w / r_h)
    if cw_from_h <= src_w:
        crop_w = cw_from_h
        crop_h = src_h
    else:
        crop_w = src_w
        crop_h = int(src_w * r_h / r_w)

    crop_w = crop_w - (crop_w % 2)
    crop_h = crop_h - (crop_h % 2)
    crop_y = (src_h - crop_h) // 2
    max_x = src_w - crop_w

    if not smoothed_x:
        # Static centre-crop fallback.
        centre_x = (src_w - crop_w) // 2
        return f"crop={crop_w}:{crop_h}:{centre_x}:{crop_y}"

    def _x_px(norm_x: float) -> int:
        """Convert normalised x to pixel offset, clamped to [0, max_x]."""
        centre_px = int(norm_x * src_w)
        x = centre_px - crop_w // 2
        return max(0, min(x, max_x))

    if len(smoothed_x) == 1:
        return f"crop={crop_w}:{crop_h}:{_x_px(smoothed_x[0])}:{crop_y}"

    # Build nested if(lte(t, T), x_px, ...) expression, innermost = last keyframe.
    x_expr = str(_x_px(smoothed_x[-1]))
    for i in range(len(smoothed_x) - 2, -1, -1):
        x_px = _x_px(smoothed_x[i])
        t = timestamps[i]
        x_expr = f"if(lte(t,{t:.6f}),{x_px},{x_expr})"

    return f"crop={crop_w}:{crop_h}:{x_expr}:{crop_y}"
