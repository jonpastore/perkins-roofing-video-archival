"""Media cleanup adapter — thin I/O layer (coverage-omitted).

Audio:
    clean_audio() runs the arg-list from core.audio_filter via subprocess,
    matching the subprocess.run pattern from adapters/ffmpeg.py.

Video:
    VideoUpscaler is a client interface for a hosted upscaler API.
    # SCAFFOLD: mocked — pick + wire a cloud upscaler service (e.g. Replicate/Topaz Cloud).
    Config is read from env vars; no cerberus / host-GPU dependency.
"""
from __future__ import annotations

import os
import subprocess

from core.audio_filter import build_audio_cmd

# Hard timeout matching adapters/ffmpeg.py convention.
_ENCODE_TIMEOUT = 1200

# Video upscaler config (env-driven; swap in the real endpoint when chosen).
_UPSCALER_API_URL = os.getenv("UPSCALER_API_URL", "")
_UPSCALER_API_KEY = os.getenv("UPSCALER_API_KEY", "")


def clean_audio(
    in_path: str,
    out_path: str,
    *,
    target_lufs: float = -14.0,
    denoise: bool = True,
    dereverb: bool = False,
) -> str:
    """Denoise + loudness-normalise *in_path* and write the result to *out_path*.

    Runs the arg-list produced by ``core.audio_filter.build_audio_cmd`` via
    ``subprocess.run`` (no shell=True), matching the style of adapters/ffmpeg.py.

    Args:
        in_path:     Source audio or video file path.
        out_path:    Destination for the cleaned audio file.
        target_lufs: Target integrated loudness in LUFS (default -14.0).
        denoise:     Apply afftdn noise reduction (default True).
        dereverb:    Apply de-reverb afftdn pass (default False).

    Returns:
        *out_path* on success.

    Raises:
        subprocess.CalledProcessError: if ffmpeg exits non-zero.
        subprocess.TimeoutExpired: if the call exceeds the timeout.
    """
    cmd = build_audio_cmd(
        in_path,
        out_path,
        target_lufs=target_lufs,
        denoise=denoise,
        dereverb=dereverb,
    )
    subprocess.run(cmd, check=True, capture_output=True, timeout=_ENCODE_TIMEOUT)
    return out_path


class VideoUpscaler:
    """Client interface for a hosted video upscaler API.

    # SCAFFOLD: mocked — pick + wire a cloud upscaler service.
    #   Candidates: Replicate (topaz-video-ai model), Topaz Video AI Cloud,
    #               or a Cloud Run GPU job wrapping Real-ESRGAN.
    #   Wire: set UPSCALER_API_URL + UPSCALER_API_KEY in the environment,
    #         replace _mock_upscale() with the real API call, and add the
    #         chosen client lib to requirements.txt.
    #   No cerberus / host-GPU dependency — cloud only.
    """

    def __init__(
        self,
        api_url: str = _UPSCALER_API_URL,
        api_key: str = _UPSCALER_API_KEY,
    ) -> None:
        self.api_url = api_url
        self.api_key = api_key

    def upscale(
        self,
        in_path: str,
        out_path: str,
        *,
        scale: int = 2,
    ) -> str:
        """Submit *in_path* to the upscaler API and download the result to *out_path*.

        Args:
            in_path:  Source video file path.
            out_path: Destination for the upscaled video.
            scale:    Upscale factor (default 2×).

        Returns:
            *out_path* on success.

        Raises:
            NotImplementedError: always — scaffold not yet wired to a real service.
        """
        return self._mock_upscale(in_path, out_path, scale=scale)

    def _mock_upscale(self, in_path: str, out_path: str, *, scale: int) -> str:  # noqa: ARG002
        # SCAFFOLD: replace with real API call.
        raise NotImplementedError(
            "VideoUpscaler is not yet wired to a cloud upscaler service. "
            "Set UPSCALER_API_URL / UPSCALER_API_KEY and implement _mock_upscale()."
        )
