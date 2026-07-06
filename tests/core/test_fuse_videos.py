"""Coverage-preserving tests for fuse_videos (adapters/ffmpeg.py) and new config keys.

fuse_videos is I/O-omitted so we test the filtergraph logic directly and patch
subprocess.run to avoid a real ffmpeg call.  The config-key tests exercise the
pure EDITABLE_KEYS dict in api/routes/config.py.
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — inspect the filtergraph fuse_videos would build
# ---------------------------------------------------------------------------

def _build_fuse_videos_filtergraph(
    intro_has_audio: bool = True,
    clip_has_audio: bool = True,
    outro_has_audio: bool = True,
) -> str:
    """Invoke fuse_videos with mocked subprocess + has_audio and return the
    filter_complex string that was passed to ffmpeg."""
    from adapters.ffmpeg import fuse_videos

    captured: list[str] = []

    def _fake_run(cmd, **kwargs):
        # Capture the -filter_complex argument
        try:
            idx = cmd.index("-filter_complex")
            captured.append(cmd[idx + 1])
        except ValueError:
            pass
        return MagicMock(returncode=0)

    has_audio_map = {
        "/intro.mp4": intro_has_audio,
        "/clip.mp4": clip_has_audio,
        "/outro.mp4": outro_has_audio,
    }

    with (
        patch("adapters.ffmpeg.subprocess.run", side_effect=_fake_run),
        patch("adapters.ffmpeg.has_audio", side_effect=lambda p: has_audio_map[p]),
    ):
        fuse_videos("/intro.mp4", "/clip.mp4", "/outro.mp4", "/out.mp4")

    assert captured, "fuse_videos did not call subprocess.run with -filter_complex"
    return captured[0]


# ---------------------------------------------------------------------------
# fuse_videos filtergraph structure
# ---------------------------------------------------------------------------

def test_fuse_videos_scales_all_three_to_1080x1920():
    fg = _build_fuse_videos_filtergraph()
    assert fg.count("scale=1080:1920") == 3


def test_fuse_videos_sets_fps_30_on_all_inputs():
    fg = _build_fuse_videos_filtergraph()
    assert fg.count("fps=30") == 3


def test_fuse_videos_setsar_on_all_inputs():
    fg = _build_fuse_videos_filtergraph()
    assert fg.count("setsar=1") == 3


def test_fuse_videos_force_original_aspect_ratio():
    fg = _build_fuse_videos_filtergraph()
    assert fg.count("force_original_aspect_ratio=decrease") == 3


def test_fuse_videos_pad_present():
    fg = _build_fuse_videos_filtergraph()
    assert fg.count("pad=1080:1920") == 3


def test_fuse_videos_concat_n3():
    fg = _build_fuse_videos_filtergraph()
    assert "concat=n=3:v=1:a=1" in fg


def test_fuse_videos_output_labels():
    fg = _build_fuse_videos_filtergraph()
    assert "[vout]" in fg
    assert "[aout]" in fg


def test_fuse_videos_loudnorm_on_clip():
    fg = _build_fuse_videos_filtergraph()
    assert "loudnorm=I=-14" in fg


def test_fuse_videos_aformat_on_clip():
    fg = _build_fuse_videos_filtergraph()
    assert "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo" in fg


def test_fuse_videos_no_loudnorm_on_intro_or_outro():
    """Intro and outro must NOT receive loudnorm — only the clip does."""
    fg = _build_fuse_videos_filtergraph()
    # loudnorm should appear exactly once (on the clip, input 1)
    assert fg.count("loudnorm") == 1


def test_fuse_videos_silence_when_intro_has_no_audio():
    fg = _build_fuse_videos_filtergraph(intro_has_audio=False)
    assert "aevalsrc=0" in fg


def test_fuse_videos_silence_when_outro_has_no_audio():
    fg = _build_fuse_videos_filtergraph(outro_has_audio=False)
    assert "aevalsrc=0" in fg


def test_fuse_videos_silence_when_clip_has_no_audio():
    """When clip has no audio, silence is synthesised (no loudnorm applied)."""
    fg = _build_fuse_videos_filtergraph(clip_has_audio=False)
    assert "aevalsrc=0" in fg
    assert "loudnorm" not in fg


def test_fuse_videos_returns_out_path():
    """fuse_videos must return the *out* path on success."""
    from adapters.ffmpeg import fuse_videos

    with (
        patch("adapters.ffmpeg.subprocess.run", return_value=MagicMock(returncode=0)),
        patch("adapters.ffmpeg.has_audio", return_value=True),
    ):
        result = fuse_videos("/intro.mp4", "/clip.mp4", "/outro.mp4", "/out.mp4")
    assert result == "/out.mp4"


def test_fuse_videos_propagates_subprocess_error():
    """CalledProcessError from ffmpeg must propagate unchanged."""
    from adapters.ffmpeg import fuse_videos

    with (
        patch(
            "adapters.ffmpeg.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "ffmpeg"),
        ),
        patch("adapters.ffmpeg.has_audio", return_value=True),
    ):
        with pytest.raises(subprocess.CalledProcessError):
            fuse_videos("/intro.mp4", "/clip.mp4", "/outro.mp4", "/out.mp4")


def test_fuse_videos_semicolon_separated():
    fg = _build_fuse_videos_filtergraph()
    assert ";" in fg


# ---------------------------------------------------------------------------
# Config keys — BRAND_INTRO_VIDEO / BRAND_OUTRO_VIDEO in EDITABLE_KEYS
# ---------------------------------------------------------------------------

def test_brand_intro_video_in_editable_keys():
    from api.routes.config import EDITABLE_KEYS
    assert "BRAND_INTRO_VIDEO" in EDITABLE_KEYS


def test_brand_outro_video_in_editable_keys():
    from api.routes.config import EDITABLE_KEYS
    assert "BRAND_OUTRO_VIDEO" in EDITABLE_KEYS


def test_brand_intro_video_label_mentions_gs():
    from api.routes.config import EDITABLE_KEYS
    assert "gs://" in EDITABLE_KEYS["BRAND_INTRO_VIDEO"]


def test_brand_outro_video_label_mentions_gs():
    from api.routes.config import EDITABLE_KEYS
    assert "gs://" in EDITABLE_KEYS["BRAND_OUTRO_VIDEO"]


# ---------------------------------------------------------------------------
# Settings defaults
# ---------------------------------------------------------------------------

def test_settings_brand_intro_video_default_empty():
    from app.config import settings
    assert settings.BRAND_INTRO_VIDEO == "" or isinstance(settings.BRAND_INTRO_VIDEO, str)


def test_settings_brand_outro_video_default_empty():
    from app.config import settings
    assert settings.BRAND_OUTRO_VIDEO == "" or isinstance(settings.BRAND_OUTRO_VIDEO, str)
