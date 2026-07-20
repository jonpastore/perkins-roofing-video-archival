"""Per-platform short-form video requirements — the single source of truth.

Moved out of core/publish_dispatch.py (the mocked distribute_job lane) so social_job
and the /clips preflight check share one table. Pure data + a validate() helper; no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranscodeSpec:
    platform: str
    aspect_ratio: str
    codec_video: str
    codec_audio: str
    max_length_seconds: int
    max_file_size_mb: int
    min_resolution: str  # "WxH"
    notes: str = ""


PLATFORM_SPECS: dict[str, TranscodeSpec] = {
    "tiktok": TranscodeSpec("tiktok", "9:16", "h264", "aac", 600, 287, "720x1280"),
    "instagram": TranscodeSpec("instagram", "9:16", "h264", "aac", 90, 1000, "720x1280"),
    "youtube_shorts": TranscodeSpec("youtube_shorts", "9:16", "h264", "aac", 60, 256000, "1080x1920"),
    "facebook": TranscodeSpec("facebook", "9:16", "h264", "aac", 90, 4096, "720x1280"),
    "linkedin": TranscodeSpec("linkedin", "9:16", "h264", "aac", 600, 5120, "360x640"),
    "x": TranscodeSpec("x", "9:16", "h264", "aac", 140, 512, "32x32"),
    "pinterest": TranscodeSpec("pinterest", "9:16", "h264", "aac", 900, 2048, "240x240"),
}


def validate(meta: dict, platform: str) -> list[str]:
    """Return human-readable failure strings for a clip's meta vs a platform's spec.

    meta keys: duration_seconds, width, height, size_mb, codec_video, codec_audio.
    Empty list == passes. Unknown platform is a single-item error list.
    """
    if platform not in PLATFORM_SPECS:
        return [f"unknown platform '{platform}'"]
    spec = PLATFORM_SPECS[platform]
    errors: list[str] = []
    if meta.get("duration_seconds", 0) > spec.max_length_seconds:
        errors.append(f"duration exceeds {spec.max_length_seconds}s for {platform}")
    min_w, min_h = (int(x) for x in spec.min_resolution.split("x"))
    if meta.get("width", 0) < min_w or meta.get("height", 0) < min_h:
        errors.append(f"resolution below {spec.min_resolution} for {platform}")
    if meta.get("size_mb", 0) > spec.max_file_size_mb:
        errors.append(f"file size exceeds {spec.max_file_size_mb}MB for {platform}")
    if meta.get("codec_video") != spec.codec_video:
        errors.append(f"video codec must be {spec.codec_video} for {platform}")
    if meta.get("codec_audio") != spec.codec_audio:
        errors.append(f"audio codec must be {spec.codec_audio} for {platform}")
    return errors


# Creative presets injected into the clip-generation prompt per target platform.
PLATFORM_PRESETS: dict[str, dict] = {
    "tiktok": {"hook_seconds": 2, "caption_style": "fast/punchy", "hashtag_count": 5, "text_cadence": "quick cuts"},
    "instagram": {"hook_seconds": 2, "caption_style": "stylish", "hashtag_count": 4, "text_cadence": "smooth"},
    "youtube_shorts": {"hook_seconds": 3, "caption_style": "energetic", "hashtag_count": 3, "text_cadence": "dynamic"},
    "facebook": {"hook_seconds": 3, "caption_style": "engaging", "hashtag_count": 3, "text_cadence": "conversational"},
    "linkedin": {"hook_seconds": 4, "caption_style": "professional", "hashtag_count": 2, "text_cadence": "measured"},
    "x": {"hook_seconds": 2, "caption_style": "witty", "hashtag_count": 3, "text_cadence": "snappy"},
    "pinterest": {"hook_seconds": 3, "caption_style": "inspirational", "hashtag_count": 4, "text_cadence": "flowing"},
}
