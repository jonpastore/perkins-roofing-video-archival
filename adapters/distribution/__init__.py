"""Multi-platform distribution adapters (I/O — coverage-omitted).

Publishers match TikTok/IG: creds in __init__, publish(*, video_url, caption,
idempotency_key) -> str. Live posts still need app-review tokens.

Exports:
    PlatformAdapter
    OAuthStore
    youtube_shorts / facebook / linkedin / x / pinterest
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
