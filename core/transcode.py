"""Per-platform conform primitives (pure ffmpeg-arg builders, no execution).

The master render is 1080x1920 h264/aac, which already satisfies every current
platform's aspect/codec/resolution — so the only conform action is trimming a clip
that exceeds a platform's max duration. These helpers build that ffmpeg command and
group platforms that share an output, ready to wire into render when a clip actually
exceeds a target's cap (rare for 20–60s clips; preflight already warns in the UI).
"""
from __future__ import annotations

from core.platform_specs import PLATFORM_SPECS


def needs_conform(meta: dict, spec) -> bool:
    """True when a clip's meta violates *spec* on duration or codec."""
    return bool(
        meta.get("duration_seconds", 0) > spec.max_length_seconds
        or meta.get("codec_video") != spec.codec_video
        or meta.get("codec_audio") != spec.codec_audio
    )


def conform_cmd(src_path: str, out_path: str, spec, src_duration: float) -> list[str] | None:
    """ffmpeg args to trim *src* to *spec*'s max duration and encode h264/aac.

    Returns None when no conform is needed (duration within the cap; codecs already
    match the master)."""
    if src_duration <= spec.max_length_seconds:
        return None
    return [
        "ffmpeg", "-y", "-i", src_path,
        "-t", str(spec.max_length_seconds),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        out_path,
    ]


def variants_for(platforms: list[str], src_duration: float) -> dict[str, str]:
    """Map each known platform to a short spec key (effective duration bucket) so
    platforms that share an output dedupe to one encode. All current platforms are
    9:16 h264/aac, so the key is just the min(clip, cap) duration."""
    out: dict[str, str] = {}
    for p in platforms:
        spec = PLATFORM_SPECS.get(p)
        if spec:
            out[p] = f"{min(src_duration, spec.max_length_seconds):.0f}s"
    return out
