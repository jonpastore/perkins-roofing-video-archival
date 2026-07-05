"""Pure social-publishing logic (coverage-gated: core/).

SocialPublisher   — Protocol that all platform adapters implement.
already_posted    — Pure idempotency guard: True when the platform already has
                    a non-null external_id for this item.
build_caption     — Compose caption + hashtags, capped at 2 200 chars (IG max).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

_CAPTION_LIMIT = 2200


@runtime_checkable
class SocialPublisher(Protocol):
    """Publish a short-form video to a social platform.

    Args:
        video_url:       Publicly accessible HTTPS URL to the video file.
        caption:         Caption / description text (already formatted).
        idempotency_key: Stable string that uniquely identifies this post
                         (e.g. ``"series-{series_id}-part-{part}"``).

    Returns:
        Platform-assigned post / media identifier string.
    """

    def publish(self, *, video_url: str, caption: str, idempotency_key: str) -> str: ...


def already_posted(existing_posts: list, platform: str) -> bool:
    """Return True if *platform* already has a post with a non-null external_id.

    Args:
        existing_posts: Iterable of objects (or dicts) each carrying
                        ``.platform`` and ``.external_id`` attributes (or keys).
        platform:       Platform slug to look up, e.g. ``"instagram"`` or
                        ``"tiktok"``.

    Returns:
        True  — a matching row with a non-null, non-empty external_id exists.
        False — no such row found.
    """
    for post in existing_posts:
        if isinstance(post, dict):
            p = post.get("platform")
            ext = post.get("external_id")
        else:
            p = getattr(post, "platform", None)
            ext = getattr(post, "external_id", None)
        if p == platform and ext:
            return True
    return False


def build_caption(title: str, tags: list[str]) -> str:
    """Compose a social caption from *title* and *tags*.

    The caption is ``{title}\\n\\n{hashtags}`` where each tag in *tags* is
    prefixed with ``#`` (unless it already starts with ``#``).  The result is
    hard-truncated at 2 200 characters to comply with Instagram's limit.

    Args:
        title: Human-readable title text.
        tags:  List of tag strings (with or without leading ``#``).

    Returns:
        Caption string of at most 2 200 characters.
    """
    hashtags = " ".join(
        t if t.startswith("#") else f"#{t}"
        for t in tags
    )
    if hashtags:
        caption = f"{title}\n\n{hashtags}"
    else:
        caption = title
    return caption[:_CAPTION_LIMIT]
