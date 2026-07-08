"""Pure platform-agnostic distribution dispatch logic — no I/O, 100%-coverable.

Covers:
  - Status state machine: PENDING → IN_FLIGHT → PUBLISHED | FAILED
  - Retry / exponential-backoff decisions
  - Per-platform caption/hashtag template interpolation
  - Platform transcode-spec table (aspect ratio, codec, length caps)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# Status state machine
# ---------------------------------------------------------------------------

Status = Literal["PENDING", "IN_FLIGHT", "PUBLISHED", "FAILED"]
Event = Literal["start", "success", "fail"]

# Valid transitions: (current, event) -> next
_TRANSITIONS: dict[tuple[Status, Event], Status] = {
    ("PENDING", "start"): "IN_FLIGHT",
    ("IN_FLIGHT", "success"): "PUBLISHED",
    ("IN_FLIGHT", "fail"): "FAILED",
}


def next_status(current: Status, event: Event) -> Status:
    """Return the next status for a given (current, event) pair.

    Raises:
        ValueError: if the transition is not valid.
    """
    key = (current, event)
    if key not in _TRANSITIONS:
        raise ValueError(
            f"Invalid transition: status={current!r} + event={event!r}. "
            f"Valid transitions: {sorted(_TRANSITIONS)}"
        )
    return _TRANSITIONS[key]


# ---------------------------------------------------------------------------
# Retry / backoff
# ---------------------------------------------------------------------------

_MAX_BACKOFF_SECONDS = 300  # cap at 5 min


def should_retry(attempt: int, max_attempts: int) -> bool:
    """Return True when another attempt should be made.

    Args:
        attempt:      Zero-based index of the attempt just completed (0 = first try).
        max_attempts: Maximum total attempts allowed (must be >= 1).
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be >= 1, got {max_attempts}")
    return attempt < max_attempts - 1


def backoff_seconds(attempt: int) -> float:
    """Exponential backoff with a 5-minute cap.

    Args:
        attempt: Zero-based attempt index (0 → 1s, 1 → 2s, 2 → 4s, …).

    Returns:
        Seconds to wait before the next attempt.
    """
    if attempt < 0:
        raise ValueError(f"attempt must be >= 0, got {attempt}")
    return min(2.0 ** attempt, _MAX_BACKOFF_SECONDS)


# ---------------------------------------------------------------------------
# Caption / hashtag interpolation
# ---------------------------------------------------------------------------

def render_caption(template: str, vars: dict[str, str]) -> str:  # noqa: A002
    """Interpolate ``{variable}`` placeholders in *template* using *vars*.

    Unknown variables are left as-is (the raw ``{key}`` text is preserved).
    This mirrors Python's ``str.format_map`` with a default-to-key fallback,
    which keeps captions partially usable even when optional vars are absent.

    Supported placeholder names (convention; not enforced here):
        ``{location}``  — e.g. "Palm Beach County"
        ``{product}``   — e.g. "standing-seam metal roofing"
        ``{crew}``      — e.g. "the Perkins crew"

    Args:
        template: Caption template string with ``{key}`` placeholders.
        vars:     Mapping of variable names to replacement strings.

    Returns:
        Interpolated caption string. Missing keys are replaced with the
        literal ``{key}`` text so the output is always a valid string.
    """

    class _KeepMissing(dict):
        def __missing__(self, key: str) -> str:
            return "{" + key + "}"

    return template.format_map(_KeepMissing(vars))


# ---------------------------------------------------------------------------
# Platform transcode-spec table
# ---------------------------------------------------------------------------

Platform = Literal["tiktok", "instagram", "youtube_shorts", "facebook", "linkedin", "x", "pinterest"]


@dataclass(frozen=True)
class TranscodeSpec:
    """Per-platform encoding requirements for short-form video distribution."""

    platform: Platform
    aspect_ratio: str       # e.g. "9:16"
    codec_video: str        # e.g. "h264"
    codec_audio: str        # e.g. "aac"
    max_length_seconds: int
    max_file_size_mb: int
    min_resolution: str     # e.g. "720x1280"
    notes: str = ""


# Reference: repurpose.io platform specs + each platform's developer docs (2026-07)
_PLATFORM_SPECS: dict[Platform, TranscodeSpec] = {
    "tiktok": TranscodeSpec(
        platform="tiktok",
        aspect_ratio="9:16",
        codec_video="h264",
        codec_audio="aac",
        max_length_seconds=600,
        max_file_size_mb=287,
        min_resolution="720x1280",
        notes="PULL_FROM_URL flow; DNS TXT verify required for GCS domain",
    ),
    "instagram": TranscodeSpec(
        platform="instagram",
        aspect_ratio="9:16",
        codec_video="h264",
        codec_audio="aac",
        max_length_seconds=90,
        max_file_size_mb=1000,
        min_resolution="720x1280",
        notes="Reels via Graph API container-creation flow; min 3s",
    ),
    "youtube_shorts": TranscodeSpec(
        platform="youtube_shorts",
        aspect_ratio="9:16",
        codec_video="h264",
        codec_audio="aac",
        max_length_seconds=60,
        max_file_size_mb=256000,
        min_resolution="1080x1920",
        notes="Data API v3 videos.insert; #Shorts in title/desc triggers Shorts shelf",
    ),
    "facebook": TranscodeSpec(
        platform="facebook",
        aspect_ratio="9:16",
        codec_video="h264",
        codec_audio="aac",
        max_length_seconds=90,
        max_file_size_mb=4096,
        min_resolution="720x1280",
        notes="Reels via Pages API; max 90s for Reels, 240min for standard video",
    ),
    "linkedin": TranscodeSpec(
        platform="linkedin",
        aspect_ratio="9:16",
        codec_video="h264",
        codec_audio="aac",
        max_length_seconds=600,
        max_file_size_mb=5120,
        min_resolution="360x640",
        notes="Posts API; org access via Partner Program required",
    ),
    "x": TranscodeSpec(
        platform="x",
        aspect_ratio="9:16",
        codec_video="h264",
        codec_audio="aac",
        max_length_seconds=140,
        max_file_size_mb=512,
        min_resolution="32x32",
        notes="API v2 media/upload chunked; paid tier ($200/mo Basic) required for posting",
    ),
    "pinterest": TranscodeSpec(
        platform="pinterest",
        aspect_ratio="9:16",
        codec_video="h264",
        codec_audio="aac",
        max_length_seconds=900,
        max_file_size_mb=2048,
        min_resolution="240x240",
        notes="API v5 /v5/pins multipart video upload; Trial→Standard app review",
    ),
}


def transcode_spec(platform: Platform) -> TranscodeSpec:
    """Return the :class:`TranscodeSpec` for *platform*.

    Raises:
        KeyError: if *platform* is not in the supported set.
    """
    if platform not in _PLATFORM_SPECS:
        raise KeyError(
            f"Unknown platform: {platform!r}. Supported: {sorted(_PLATFORM_SPECS)}"
        )
    return _PLATFORM_SPECS[platform]
