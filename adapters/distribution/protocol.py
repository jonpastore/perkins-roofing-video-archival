"""PlatformAdapter protocol — the interface every distribution adapter must satisfy (I/O — coverage-omitted).

SCAFFOLD: mocked — real API wiring blocked on app-review/creds.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PlatformAdapter(Protocol):
    """Structural protocol for all platform publishing adapters.

    Every adapter must expose a single ``publish`` method that accepts a
    video URL, caption text, and OAuth access token, and returns a dict
    containing at minimum a ``post_id`` key.
    """

    def publish(self, video_url: str, caption: str, token: str) -> dict:
        """Publish *video_url* to the platform.

        Args:
            video_url: Public HTTPS URL of the transcoded video.
            caption:   Platform-rendered caption + hashtags (already interpolated).
            token:     OAuth access token for the publishing account.

        Returns:
            Dict with at least ``{"post_id": str, "platform": str}``.
        """
        ...
