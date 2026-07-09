"""Behavioral validation: render_job reads render_spec + calls Track A engines.

All external I/O (GCS, ffmpeg, DB) is mocked so the test is hermetic.
Coverage note: jobs/ is coverage-omitted per R1 (I/O layer); these tests
validate the correct engine-invocation sequence and backward-compat behaviour.
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from core.render_spec import (
    ClipRenderSpec,
    BrollSpec,
    CaptionsSpec,
    FxSpec,
    MusicSpec,
    get_clips,
    get_render_spec,
    set_render_spec,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_series(parts_json=None, approved=1, video_id="vid1", title="T"):
    s = MagicMock()
    s.approved = approved
    s.video_id = video_id
    s.title = title
    s.parts_json = parts_json
    return s


def _make_video(archive_uri=None):
    v = MagicMock()
    v.archive_uri = archive_uri
    return v


# ---------------------------------------------------------------------------
# get_clips / get_render_spec round-trip through parts_json
# ---------------------------------------------------------------------------

def test_set_then_get_render_spec_roundtrip():
    clips = [{"title": "C", "start": 0.0, "end": 10.0}]
    spec = ClipRenderSpec(reframe=True, speech_cleanup=True)
    envelope = set_render_spec(clips, spec)
    assert get_clips(envelope) == clips
    recovered = get_render_spec(envelope)
    assert recovered.reframe is True
    assert recovered.speech_cleanup is True


def test_legacy_list_parts_json_returns_defaults():
    clips = [{"title": "C", "start": 0.0, "end": 10.0}]
    spec = get_render_spec(clips)
    assert isinstance(spec, ClipRenderSpec)
    assert spec.reframe is False
    assert spec.speech_cleanup is False


def test_null_parts_json_get_clips_returns_empty():
    assert get_clips(None) == []


def test_envelope_clips_preserved_after_spec_update():
    clips = [{"title": "C1", "start": 0.0, "end": 5.0},
             {"title": "C2", "start": 6.0, "end": 12.0}]
    envelope = set_render_spec(clips, ClipRenderSpec())
    new_spec = ClipRenderSpec(reframe=True)
    new_envelope = set_render_spec(envelope, new_spec)
    assert get_clips(new_envelope) == clips
    assert get_render_spec(new_envelope).reframe is True


# ---------------------------------------------------------------------------
# render_job._apply_track_a_engines — engine call ordering
# ---------------------------------------------------------------------------

def _invoke_apply_engines(spec: ClipRenderSpec, words: list | None = None) -> str:
    """Call _apply_track_a_engines with all I/O mocked; return final path."""
    from jobs.render_job import _apply_track_a_engines

    clip_path = "/tmp/clip.mp4"
    scratch = "/tmp/scratch"

    with (
        patch("jobs.render_job._load_words_for_clip", return_value=words or []),
        patch("jobs.render_job._resolve_music_track", return_value=None),
        patch("adapters.ffmpeg.run_ffmpeg_cmd"),
        patch("os.path.join", side_effect=lambda *a: "/".join(a)),
    ):
        return _apply_track_a_engines(clip_path, spec, scratch, series_id=1, part_index=0)


def test_default_spec_is_noop():
    spec = ClipRenderSpec()
    result = _invoke_apply_engines(spec)
    assert result == "/tmp/clip.mp4"


def test_reframe_changes_path():
    spec = ClipRenderSpec(reframe=True)

    with (
        patch("jobs.render_job._load_words_for_clip", return_value=[]),
        patch("jobs.render_job._resolve_music_track", return_value=None),
        patch("adapters.ffmpeg.run_ffmpeg_cmd"),
        patch("os.path.join", side_effect=lambda *a: "/".join(a)),
    ):
        from jobs.render_job import _apply_track_a_engines
        result = _apply_track_a_engines("/tmp/clip.mp4", spec, "/tmp", 1, 0)
    assert "reframe" in result


def test_speech_cleanup_with_words_changes_path():
    words = [
        {"word": "um", "start": 0.0, "end": 0.3},
        {"word": "hello", "start": 0.5, "end": 1.0},
    ]
    spec = ClipRenderSpec(speech_cleanup=True)

    with (
        patch("jobs.render_job._load_words_for_clip", return_value=words),
        patch("jobs.render_job._resolve_music_track", return_value=None),
        patch("adapters.ffmpeg.run_ffmpeg_cmd"),
        patch("os.path.join", side_effect=lambda *a: "/".join(a)),
    ):
        from jobs.render_job import _apply_track_a_engines
        result = _apply_track_a_engines("/tmp/clip.mp4", spec, "/tmp", 1, 0)
    assert "cleanup" in result


def test_speech_cleanup_no_words_is_noop():
    spec = ClipRenderSpec(speech_cleanup=True)
    result = _invoke_apply_engines(spec, words=[])
    assert result == "/tmp/clip.mp4"


def test_broll_no_key_skips_silently():
    spec = ClipRenderSpec(broll=BrollSpec(source="pexels"))
    with patch.dict("os.environ", {}, clear=False):
        import os
        os.environ.pop("PEXELS_API_KEY", None)
        result = _invoke_apply_engines(spec)
    assert result == "/tmp/clip.mp4"


def test_music_skipped_when_no_track_id():
    spec = ClipRenderSpec(music=MusicSpec(catalog="pixabay", track_id=""))
    result = _invoke_apply_engines(spec)
    assert result == "/tmp/clip.mp4"


def test_music_skipped_when_resolve_returns_none():
    spec = ClipRenderSpec(music=MusicSpec(catalog="pixabay", track_id="t1"))
    result = _invoke_apply_engines(spec)
    assert result == "/tmp/clip.mp4"


def test_captions_noop_with_default_style_no_words():
    spec = ClipRenderSpec(captions=CaptionsSpec(style="default", position="bottom"))
    result = _invoke_apply_engines(spec, words=[])
    assert result == "/tmp/clip.mp4"


def test_clip_fx_cut_is_noop():
    spec = ClipRenderSpec(fx=FxSpec(transition="cut", color_grade="none"))
    result = _invoke_apply_engines(spec)
    assert result == "/tmp/clip.mp4"


def test_clip_fx_fade_applies():
    spec = ClipRenderSpec(fx=FxSpec(transition="fade", color_grade="none"))

    with (
        patch("jobs.render_job._load_words_for_clip", return_value=[]),
        patch("jobs.render_job._resolve_music_track", return_value=None),
        patch("adapters.ffmpeg.run_ffmpeg_cmd") as mock_run,
        patch("os.path.join", side_effect=lambda *a: "/".join(a)),
    ):
        from jobs.render_job import _apply_track_a_engines
        result = _apply_track_a_engines("/tmp/clip.mp4", spec, "/tmp", 1, 0)

    assert "fx" in result
    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert any("fade" in str(a) for a in cmd)


def test_clip_fx_vivid_applies_eq():
    spec = ClipRenderSpec(fx=FxSpec(transition="cut", color_grade="vivid"))

    with (
        patch("jobs.render_job._load_words_for_clip", return_value=[]),
        patch("jobs.render_job._resolve_music_track", return_value=None),
        patch("adapters.ffmpeg.run_ffmpeg_cmd") as mock_run,
        patch("os.path.join", side_effect=lambda *a: "/".join(a)),
    ):
        from jobs.render_job import _apply_track_a_engines
        _apply_track_a_engines("/tmp/clip.mp4", spec, "/tmp", 1, 0)

    cmd = mock_run.call_args[0][0]
    assert any("eq=" in str(a) for a in cmd)


def test_engine_exception_does_not_propagate():
    spec = ClipRenderSpec(reframe=True)

    with (
        patch("jobs.render_job._load_words_for_clip", return_value=[]),
        patch("jobs.render_job._resolve_music_track", return_value=None),
        patch("adapters.ffmpeg.run_ffmpeg_cmd", side_effect=RuntimeError("ffmpeg died")),
        patch("os.path.join", side_effect=lambda *a: "/".join(a)),
    ):
        from jobs.render_job import _apply_track_a_engines
        result = _apply_track_a_engines("/tmp/clip.mp4", spec, "/tmp", 1, 0)

    assert result == "/tmp/clip.mp4"


# ---------------------------------------------------------------------------
# parts_json backward-compat: run() uses get_clips() on legacy list form
# ---------------------------------------------------------------------------

def test_run_get_clips_handles_legacy_list():
    clips = [{"title": "C", "start": 0.0, "end": 10.0}]
    assert get_clips(clips) == clips


def test_run_get_clips_handles_envelope():
    clips = [{"title": "C", "start": 0.0, "end": 10.0}]
    envelope = {"clips": clips, "render_spec": {"reframe": True}}
    assert get_clips(envelope) == clips


def test_render_spec_defaults_when_parts_json_is_none():
    spec = get_render_spec(None)
    assert spec.reframe is False
    assert spec.speech_cleanup is False
    assert spec.fx.transition == "cut"
