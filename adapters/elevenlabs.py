"""ElevenLabs voice-clone + TTS adapter (I/O — coverage-omitted).

# SCAFFOLD: mocked — real API wiring blocked on keys.
# Replace the stub implementations below once ELEVENLABS_API_KEY is available.

Environment variables (documented; never hardcoded):
  ELEVENLABS_API_KEY  — ElevenLabs API key (required for real calls)

Public API:
  ElevenLabsVoice.clone(samples)          -> voice_id (str)
  ElevenLabsVoice.tts(text, voice_id)     -> audio_bytes (bytes)
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# SCAFFOLD: mocked — real API wiring blocked on keys.
_MOCK_VOICE_ID = "mock-voice-id-tim-perkins"
_MOCK_AUDIO_BYTES = b"MOCK_AUDIO_BYTES"


class ElevenLabsVoice:
    """Thin client for ElevenLabs Professional Voice Clone + TTS.

    Reads ELEVENLABS_API_KEY from the environment.  All methods currently
    return mock values — wire real HTTP calls once the API key is available.

    # SCAFFOLD: mocked — real API wiring blocked on keys.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        if not self._api_key:
            logger.warning(
                "ELEVENLABS_API_KEY not set — ElevenLabsVoice running in mock mode"
            )

    def clone(self, samples: list[str]) -> str:
        """Create (or retrieve) a Professional Voice Clone from audio sample paths/URLs.

        # SCAFFOLD: mocked — real API wiring blocked on keys.
        Real implementation: POST /v1/voices/add with multipart audio samples.
        Returns the ElevenLabs voice_id for the cloned voice.

        Args:
            samples: List of local file paths or GCS/HTTPS URLs pointing to
                     Tim's audio samples (WAV/MP3, ≥1 min each recommended).

        Returns:
            voice_id string (str).
        """
        # SCAFFOLD: mocked — real API wiring blocked on keys.
        logger.info(
            "ElevenLabsVoice.clone called with %d samples — returning mock voice_id",
            len(samples),
        )
        return _MOCK_VOICE_ID

    def tts(self, text: str, voice_id: str) -> bytes:
        """Synthesise speech from *text* using the cloned voice.

        # SCAFFOLD: mocked — real API wiring blocked on keys.
        Real implementation: POST /v1/text-to-speech/{voice_id} with JSON body
        {text, model_id, voice_settings}.  Returns raw audio bytes (MP3).

        Args:
            text:     The script text to synthesise.
            voice_id: ElevenLabs voice_id (from .clone() or the dashboard).

        Returns:
            Audio bytes (bytes) — MP3 in production, mock sentinel in scaffold.
        """
        # SCAFFOLD: mocked — real API wiring blocked on keys.
        logger.info(
            "ElevenLabsVoice.tts called: voice_id=%r, text_len=%d — returning mock audio",
            voice_id,
            len(text),
        )
        return _MOCK_AUDIO_BYTES
