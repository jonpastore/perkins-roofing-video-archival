"""Multi-platform distribution adapters (I/O — coverage-omitted).

SCAFFOLD: mocked — real API wiring blocked on app-review/creds for all platforms in this package.

Exports:
    PlatformAdapter   — Protocol all adapters implement
    OAuthStore        — In-memory token store (mocked; real: Secret Manager)
    youtube_shorts    — Mock YouTube Shorts adapter
    facebook          — Mock Facebook Reels adapter
    linkedin          — Mock LinkedIn adapter
    x                 — Mock X/Twitter adapter
    pinterest         — Mock Pinterest adapter
"""
from adapters.distribution import facebook, linkedin, pinterest, x, youtube_shorts
from adapters.distribution.oauth_store import OAuthStore
from adapters.distribution.protocol import PlatformAdapter

__all__ = [
    "PlatformAdapter",
    "OAuthStore",
    "youtube_shorts",
    "facebook",
    "linkedin",
    "x",
    "pinterest",
]
