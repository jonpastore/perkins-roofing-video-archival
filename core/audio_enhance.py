"""Pure audio enhancement filter-string builder — no I/O, deterministic.

Item 10: opt-in ``audio_enhance: bool`` spec field → ffmpeg chain:
  afftdn (noise denoise) + acompressor + loudnorm (EBU R128, -14 LUFS target).

Coverage target: 100%.

No subprocess calls here.  All execution lives in adapters/ (render_job.py uses
adapters.ffmpeg.run_ffmpeg_cmd).  The functions here only build arg lists and
filter strings so they are trivially testable without ffmpeg installed.
"""
from __future__ import annotations

import os

_FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")

# EBU R128 loudness target for social-media reels (matches existing fuse pipeline).
DEFAULT_TARGET_LUFS: float = -14.0

# afftdn spectral noise floor (dBFS).  -25 catches HVAC/room noise without
# suppressing quiet speech.
_AFFTDN_NF: float = -25.0

# acompressor settings: moderate compression for vocal presence.
#   threshold: -18 dBFS starts compression above speech peaks.
#   ratio:     4:1 — punchy but not over-compressed.
#   attack:    10 ms — fast enough to catch transients.
#   release:   150 ms — natural decay.
_ACOMPRESSOR_PARAMS = "threshold=-18dB:ratio=4:attack=10:release=150:makeup=2dB"

# loudnorm EBU R128 target parameters (matches render_spec.py build_filtergraph).
_LOUDNORM_LRA: float = 11.0
_LOUDNORM_TP: float = -1.5


def build_enhance_filter(
    *,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    denoise: bool = True,
    compress: bool = True,
) -> str:
    """Return an ffmpeg ``-af`` filter string for the audio enhancement chain.

    Applies filters in order:
      1. ``afftdn`` spectral noise reduction (when *denoise* is True).
      2. ``acompressor`` for vocal presence and dynamic range (when *compress* is True).
      3. ``loudnorm`` EBU R128 normalisation to *target_lufs*.

    Args:
        target_lufs: Target integrated loudness in LUFS (default -14.0).
        denoise:     Apply ``afftdn`` noise reduction (default True).
        compress:    Apply ``acompressor`` (default True).

    Returns:
        A comma-joined ffmpeg ``-af`` filter chain string.

    Raises:
        ValueError: if *target_lufs* is outside the range [-70, 0].
    """
    if not (-70.0 <= target_lufs <= 0.0):
        raise ValueError(
            f"target_lufs must be in [-70, 0], got {target_lufs!r}"
        )

    parts: list[str] = []

    if denoise:
        parts.append(f"afftdn=nf={_AFFTDN_NF:.0f}")

    if compress:
        parts.append(f"acompressor={_ACOMPRESSOR_PARAMS}")

    parts.append(
        f"loudnorm=I={target_lufs:.1f}:LRA={_LOUDNORM_LRA:.0f}:TP={_LOUDNORM_TP:.1f}"
    )

    return ",".join(parts)


def build_enhance_cmd(
    in_path: str,
    out_path: str,
    *,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    denoise: bool = True,
    compress: bool = True,
) -> list[str]:
    """Return a full ffmpeg arg list for in-place audio enhancement.

    The command processes audio only — video is copied without re-encode.

    Args:
        in_path:     Path to the source video/audio file.
        out_path:    Destination path (same container format as *in_path*).
        target_lufs: Target integrated loudness in LUFS (default -14.0).
        denoise:     Apply ``afftdn`` noise reduction (default True).
        compress:    Apply ``acompressor`` (default True).

    Returns:
        A ``list[str]`` suitable for ``subprocess.run(..., shell=False)``.

    Raises:
        ValueError: propagated from ``build_enhance_filter`` when *target_lufs*
                    is out of range.
    """
    af = build_enhance_filter(
        target_lufs=target_lufs,
        denoise=denoise,
        compress=compress,
    )
    return [
        _FFMPEG, "-y",
        "-i", in_path,
        "-af", af,
        "-c:v", "copy",    # copy video stream unchanged
        out_path,
    ]
