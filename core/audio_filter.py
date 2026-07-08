"""Pure audio filter-chain builder — no I/O, deterministic. Coverage target: 100%.

Builds ffmpeg `-af` filter strings and full argument lists for audio cleanup:
  - `afftdn` noise reduction (denoise)
  - `loudnorm` EBU R128 loudness normalisation to a target LUFS
  - optional `afreqshift`-based de-reverb placeholder (afftdn nr mode)

No subprocess calls here. All execution lives in adapters/media_cleanup.py.
"""
from __future__ import annotations

import os

_FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")

# Hard encode timeout matching adapters/ffmpeg.py convention.
_ENCODE_TIMEOUT = 1200


def denoise_loudnorm_chain(
    target_lufs: float = -14.0,
    *,
    denoise: bool = True,
    dereverb: bool = False,
) -> str:
    """Return an ffmpeg ``-af`` filter string for audio cleanup.

    Filters applied in order (each only when the flag is set):
      1. ``afftdn`` — spectral-subtraction noise reduction (when *denoise* is True).
      2. ``afftdn`` in de-reverb / dereverberation mode (when *dereverb* is True).
      3. ``loudnorm`` — EBU R128 loudness normalisation to *target_lufs*.

    The returned string is deterministic and safe to pass directly as the
    value for ffmpeg's ``-af`` option.

    Args:
        target_lufs: Target integrated loudness in LUFS (default -14.0, the
                     social-media standard).
        denoise:     Apply ``afftdn`` noise reduction (default True).
        dereverb:    Apply a second ``afftdn`` pass tuned for de-reverberation
                     (default False).

    Returns:
        A comma-joined ffmpeg audio filter chain string, e.g.
        ``"afftdn=nf=-25,loudnorm=I=-14:LRA=11:TP=-1.5"``.
    """
    parts: list[str] = []

    if denoise:
        # afftdn: spectral noise floor -25 dBFS, adaptive noise profiling
        parts.append("afftdn=nf=-25")

    if dereverb:
        # Second afftdn pass with de-reverb noise reduction type
        parts.append("afftdn=nr=10:nf=-25:nt=w")

    # loudnorm always last; LRA=11 and TP=-1.5 match existing fuse_videos convention
    parts.append(f"loudnorm=I={target_lufs:.1f}:LRA=11:TP=-1.5")

    return ",".join(parts)


def build_audio_cmd(
    in_path: str,
    out_path: str,
    *,
    target_lufs: float = -14.0,
    denoise: bool = True,
    dereverb: bool = False,
) -> list[str]:
    """Return the full ffmpeg argument list for audio cleanup.

    The list is suitable for ``subprocess.run(cmd, ...)`` with ``shell=False``
    (no shell-injection surface). Matches the arg-list style of
    ``adapters/ffmpeg.py``.

    Args:
        in_path:     Path to the source audio/video file.
        out_path:    Destination path for the cleaned audio file.
        target_lufs: Target integrated loudness in LUFS (default -14.0).
        denoise:     Apply afftdn noise reduction (default True).
        dereverb:    Apply de-reverb afftdn pass (default False).

    Returns:
        A ``list[str]`` ffmpeg command, e.g.::

            ["ffmpeg", "-y", "-i", "in.mp4",
             "-af", "afftdn=nf=-25,loudnorm=I=-14.0:LRA=11:TP=-1.5",
             "-vn", "out.m4a"]
    """
    af = denoise_loudnorm_chain(target_lufs, denoise=denoise, dereverb=dereverb)
    return [
        _FFMPEG, "-y",
        "-i", in_path,
        "-af", af,
        "-vn",          # drop video stream — audio-only output
        out_path,
    ]
