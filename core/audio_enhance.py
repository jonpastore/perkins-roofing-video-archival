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

# ---------------------------------------------------------------------------
# Outdoor / wind profile
# ---------------------------------------------------------------------------
# The -25 above is tuned for INDOOR, STATIONARY noise — HVAC and room tone. Tim
# shoots outdoors on a phone, and wind is neither: it is low-frequency and
# non-stationary, so afftdn's noise profile chases it instead of subtracting it,
# and nothing in the default chain high-passes at all.
#
# The high-pass does the real work here. Wind energy on a phone mic sits mostly
# below ~100 Hz, which is also below the fundamental of adult speech (~85 Hz male,
# ~165 Hz female), so 90 Hz removes rumble while leaving voice intact. 90 rather
# than 100 because a low male voice can reach into the 80s and clipping it makes
# speech sound thin.
_WIND_HIGHPASS_HZ: float = 90.0

# With the rumble already gone, afftdn is left with the residual hiss/gust it can
# actually model. -20 is gentler than the indoor -25: over-denoising outdoor audio
# produces the watery artefacting that sounds worse than the wind did.
_WIND_AFFTDN_NF: float = -20.0

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
    wind: bool = False,
) -> str:
    """Return an ffmpeg ``-af`` filter string for the audio enhancement chain.

    Applies filters in order:
      0. ``highpass`` to strip wind rumble (only when *wind* is True).
      1. ``afftdn`` spectral noise reduction (when *denoise* is True).
      2. ``acompressor`` for vocal presence and dynamic range (when *compress* is True).
      3. ``loudnorm`` EBU R128 normalisation to *target_lufs*.

    Args:
        target_lufs: Target integrated loudness in LUFS (default -14.0).
        denoise:     Apply ``afftdn`` noise reduction (default True).
        compress:    Apply ``acompressor`` (default True).
        wind:        Outdoor profile — prepend a high-pass and soften the denoiser
                     (default False). See _WIND_HIGHPASS_HZ for why.

    ``wind=False`` produces a byte-identical string to the pre-wind implementation;
    ``test_default_chain_is_byte_identical`` pins that, because this filter runs on
    every enhanced render and a silent change here would alter existing output.

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

    if wind:
        parts.append(f"highpass=f={_WIND_HIGHPASS_HZ:.0f}")

    if denoise:
        nf = _WIND_AFFTDN_NF if wind else _AFFTDN_NF
        parts.append(f"afftdn=nf={nf:.0f}")

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
    wind: bool = False,
) -> list[str]:
    """Return a full ffmpeg arg list for in-place audio enhancement.

    The command processes audio only — video is copied without re-encode.

    Args:
        in_path:     Path to the source video/audio file.
        out_path:    Destination path (same container format as *in_path*).
        target_lufs: Target integrated loudness in LUFS (default -14.0).
        denoise:     Apply ``afftdn`` noise reduction (default True).
        compress:    Apply ``acompressor`` (default True).
        wind:        Outdoor profile — high-pass wind rumble (default False).

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
        wind=wind,
    )
    return [
        _FFMPEG, "-y",
        "-i", in_path,
        "-af", af,
        "-c:v", "copy",    # copy video stream unchanged
        out_path,
    ]
