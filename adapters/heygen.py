"""HeyGen avatar render adapter (I/O — coverage-omitted).

# SCAFFOLD: mocked — real API wiring blocked on keys.
# Replace the stub implementations below once HEYGEN_API_KEY is available.

Environment variables (documented; never hardcoded):
  HEYGEN_API_KEY   — HeyGen API key (required for real calls)
  HEYGEN_AVATAR_ID — Default avatar ID for Tim's photoreal avatar (required for real calls)

Public API:
  HeyGenAvatar.render(script_text, *, voice_audio, voice_id, avatar_id) -> {"job_id", "url"}
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# SCAFFOLD: mocked — real API wiring blocked on keys.
_MOCK_JOB_ID = "mock-heygen-job-id-001"
_MOCK_VIDEO_URL = "https://mock.heygen.example/videos/mock-render-001.mp4"


class HeyGenAvatar:
    """Thin client for HeyGen avatar video generation.

    Reads HEYGEN_API_KEY and HEYGEN_AVATAR_ID from the environment.  All
    methods currently return mock values — wire real HTTP calls once the API
    key is available.

    # SCAFFOLD: mocked — real API wiring blocked on keys.
    """

    def __init__(self, api_key: str | None = None, default_avatar_id: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("HEYGEN_API_KEY", "")
        self._default_avatar_id = (
            default_avatar_id or os.environ.get("HEYGEN_AVATAR_ID", "mock-avatar-id-tim")
        )
        if not self._api_key:
            logger.warning(
                "HEYGEN_API_KEY not set — HeyGenAvatar running in mock mode"
            )

    def render(
        self,
        script_text: str,
        *,
        voice_audio: bytes | None = None,
        voice_id: str | None = None,
        avatar_id: str | None = None,
    ) -> dict[str, str]:
        """Submit a talking-head avatar render job to HeyGen.

        # SCAFFOLD: mocked — real API wiring blocked on keys.
        Real implementation: POST /v2/video/generate with JSON body containing
        avatar_id, voice (either audio_url from GCS or voice_id), and script.
        Poll GET /v1/video_status.get?video_id={job_id} until status=="completed".

        Exactly one of *voice_audio* or *voice_id* should be provided:
          - voice_audio: raw MP3/WAV bytes from ElevenLabsVoice.tts(); will be
                         uploaded to GCS and referenced as audio_url in real impl.
          - voice_id:    ElevenLabs or HeyGen voice_id for server-side synthesis.

        Args:
            script_text:  The avatar script text to render.
            voice_audio:  Optional audio bytes (from ElevenLabs TTS).
            voice_id:     Optional voice identifier (ElevenLabs or HeyGen).
            avatar_id:    HeyGen avatar ID.  Defaults to HEYGEN_AVATAR_ID env var.

        Returns:
            Dict with keys:
              "job_id" (str) — HeyGen video/job ID (poll for completion)
              "url"    (str) — Final video URL (populated when render completes;
                               mock returns a placeholder URL immediately)
        """
        # SCAFFOLD: mocked — real API wiring blocked on keys.
        resolved_avatar = avatar_id or self._default_avatar_id
        logger.info(
            "HeyGenAvatar.render called: avatar_id=%r, script_len=%d, "
            "has_audio=%s, voice_id=%r — returning mock job",
            resolved_avatar,
            len(script_text),
            voice_audio is not None,
            voice_id,
        )
        return {"job_id": _MOCK_JOB_ID, "url": _MOCK_VIDEO_URL}
