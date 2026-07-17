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


# ---------------------------------------------------------------------------
# Item 1: _load_words_for_clip — DB-backed implementation
# ---------------------------------------------------------------------------

def test_load_words_returns_empty_when_db_is_none():
    from jobs.render_job import _load_words_for_clip
    result = _load_words_for_clip(video_id="v1", clip_start=0.0, clip_end=10.0, db=None)
    assert result == []


def test_load_words_returns_empty_when_video_id_is_none():
    from jobs.render_job import _load_words_for_clip
    db = MagicMock()
    result = _load_words_for_clip(video_id=None, clip_start=0.0, clip_end=10.0, db=db)
    assert result == []


def test_load_words_returns_empty_when_clip_start_is_none():
    from jobs.render_job import _load_words_for_clip
    db = MagicMock()
    result = _load_words_for_clip(video_id="v1", clip_start=None, clip_end=10.0, db=db)
    assert result == []


def test_load_words_returns_empty_when_clip_end_is_none():
    from jobs.render_job import _load_words_for_clip
    db = MagicMock()
    result = _load_words_for_clip(video_id="v1", clip_start=0.0, clip_end=None, db=db)
    assert result == []


def _make_word_row(word, start, confidence=1.0):
    row = MagicMock()
    row.word = word
    row.start = start
    row.confidence = confidence
    return row


def _mock_db_with_rows(rows):
    """Build a mock DB session whose query chain returns *rows*."""
    db = MagicMock()
    # Chain: db.query(Word).filter(...).filter(...).order_by(...).all() → rows
    # Each .filter() returns the same mock so chaining works regardless of
    # how many .filter() calls are made.
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.order_by.return_value = chain
    chain.all.return_value = rows
    db.query.return_value = chain
    return db


def test_load_words_queries_db_and_computes_ends():
    from jobs.render_job import _load_words_for_clip

    rows = [
        _make_word_row("roof", 1.0),
        _make_word_row("damage", 1.5),
        _make_word_row("claim", 2.0),
    ]
    db = _mock_db_with_rows(rows)
    result = _load_words_for_clip(video_id="v1", clip_start=0.0, clip_end=5.0, db=db)

    assert len(result) == 3
    # End of word 0 = start of word 1
    assert result[0]["end"] == pytest.approx(1.5)
    # End of word 1 = start of word 2
    assert result[1]["end"] == pytest.approx(2.0)
    # Last word end = start + 0.3 (capped), still < clip_end
    assert result[2]["end"] == pytest.approx(2.3)
    assert result[0]["word"] == "roof"


def test_load_words_last_word_end_capped_to_clip_end():
    from jobs.render_job import _load_words_for_clip

    rows = [_make_word_row("test", 9.9)]
    db = _mock_db_with_rows(rows)
    result = _load_words_for_clip(video_id="v1", clip_start=0.0, clip_end=10.0, db=db)

    # 9.9 + 0.3 = 10.2 > clip_end=10.0 → should cap at 10.0
    assert result[0]["end"] == pytest.approx(10.0)


def test_load_words_db_exception_returns_empty():
    from jobs.render_job import _load_words_for_clip

    db = MagicMock()
    db.query.side_effect = RuntimeError("DB error")

    result = _load_words_for_clip(video_id="v1", clip_start=0.0, clip_end=10.0, db=db)
    assert result == []


def test_load_words_no_rows_returns_empty():
    from jobs.render_job import _load_words_for_clip

    db = _mock_db_with_rows([])
    result = _load_words_for_clip(video_id="v1", clip_start=0.0, clip_end=10.0, db=db)
    assert result == []


# ---------------------------------------------------------------------------
# Item 5: hook overlay engine in _apply_track_a_engines
# ---------------------------------------------------------------------------

def _invoke_apply_engines_full(spec: ClipRenderSpec, words=None, hook_text=None) -> str:
    """Call _apply_track_a_engines with all I/O mocked; return final path."""
    from jobs.render_job import _apply_track_a_engines

    with (
        patch("jobs.render_job._load_words_for_clip", return_value=words or []),
        patch("jobs.render_job._resolve_music_track", return_value=None),
        patch("adapters.ffmpeg.run_ffmpeg_cmd"),
        patch("os.path.join", side_effect=lambda *a: "/".join(a)),
    ):
        return _apply_track_a_engines(
            "/tmp/clip.mp4", spec, "/tmp", series_id=1, part_index=0,
            hook_text=hook_text,
        )


def test_hook_overlay_applied_when_hook_text_present():
    spec = ClipRenderSpec()

    with (
        patch("jobs.render_job._load_words_for_clip", return_value=[]),
        patch("jobs.render_job._resolve_music_track", return_value=None),
        patch("adapters.ffmpeg.run_ffmpeg_cmd") as mock_run,
        patch("os.path.join", side_effect=lambda *a: "/".join(a)),
    ):
        from jobs.render_job import _apply_track_a_engines
        result = _apply_track_a_engines(
            "/tmp/clip.mp4", spec, "/tmp", 1, 0,
            hook_text="Did you know your roof could be covered?",
        )

    assert "hook" in result
    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert any("drawtext" in str(a) for a in cmd)


def test_hook_overlay_skipped_when_hook_text_none():
    spec = ClipRenderSpec()
    result = _invoke_apply_engines_full(spec, hook_text=None)
    assert "hook" not in result


def test_hook_overlay_skipped_when_hook_text_empty():
    spec = ClipRenderSpec()
    result = _invoke_apply_engines_full(spec, hook_text="")
    assert "hook" not in result


def test_hook_overlay_skipped_when_hook_text_whitespace():
    spec = ClipRenderSpec()
    result = _invoke_apply_engines_full(spec, hook_text="   ")
    assert "hook" not in result


def test_hook_overlay_exception_does_not_propagate():
    spec = ClipRenderSpec()

    with (
        patch("jobs.render_job._load_words_for_clip", return_value=[]),
        patch("jobs.render_job._resolve_music_track", return_value=None),
        patch("adapters.ffmpeg.run_ffmpeg_cmd", side_effect=RuntimeError("ffmpeg died")),
        patch("os.path.join", side_effect=lambda *a: "/".join(a)),
    ):
        from jobs.render_job import _apply_track_a_engines
        result = _apply_track_a_engines(
            "/tmp/clip.mp4", spec, "/tmp", 1, 0,
            hook_text="Test hook",
        )

    assert result == "/tmp/clip.mp4"


# ---------------------------------------------------------------------------
# Item 2: new caption styles trigger ASS burn-in
# ---------------------------------------------------------------------------

def test_captions_tiktok_pop_style_applies():
    spec = ClipRenderSpec(captions=CaptionsSpec(style="tiktok_pop"))
    words = [
        {"word": "roof", "start": 0.0, "end": 0.4},
        {"word": "damage", "start": 0.5, "end": 0.9},
    ]

    with (
        patch("jobs.render_job._load_words_for_clip", return_value=words),
        patch("jobs.render_job._resolve_music_track", return_value=None),
        patch("adapters.ffmpeg.run_ffmpeg_cmd") as mock_run,
        patch("os.path.join", side_effect=lambda *a: "/".join(a)),
    ):
        from jobs.render_job import _apply_track_a_engines
        result = _apply_track_a_engines("/tmp/clip.mp4", spec, "/tmp", 1, 0)

    assert "captioned" in result
    assert mock_run.called


def test_captions_reels_clean_style_applies():
    spec = ClipRenderSpec(captions=CaptionsSpec(style="reels_clean"))
    words = [{"word": "shingle", "start": 0.0, "end": 0.5}]

    with (
        patch("jobs.render_job._load_words_for_clip", return_value=words),
        patch("jobs.render_job._resolve_music_track", return_value=None),
        patch("adapters.ffmpeg.run_ffmpeg_cmd"),
        patch("os.path.join", side_effect=lambda *a: "/".join(a)),
    ):
        from jobs.render_job import _apply_track_a_engines
        result = _apply_track_a_engines("/tmp/clip.mp4", spec, "/tmp", 1, 0)

    assert "captioned" in result


def test_captions_shorts_editorial_style_applies():
    spec = ClipRenderSpec(captions=CaptionsSpec(style="shorts_editorial"))
    words = [{"word": "warranty", "start": 0.0, "end": 0.5}]

    with (
        patch("jobs.render_job._load_words_for_clip", return_value=words),
        patch("jobs.render_job._resolve_music_track", return_value=None),
        patch("adapters.ffmpeg.run_ffmpeg_cmd"),
        patch("os.path.join", side_effect=lambda *a: "/".join(a)),
    ):
        from jobs.render_job import _apply_track_a_engines
        result = _apply_track_a_engines("/tmp/clip.mp4", spec, "/tmp", 1, 0)

    assert "captioned" in result


# ---------------------------------------------------------------------------
# Item 4: emoji_highlights spec field wires emoji_map into to_ass_karaoke
# ---------------------------------------------------------------------------

def test_emoji_highlights_enabled_passes_emoji_map_to_karaoke():
    spec = ClipRenderSpec(
        captions=CaptionsSpec(style="tiktok_pop"),
        emoji_highlights=True,
    )
    words = [{"word": "roof", "start": 0.0, "end": 0.4}]

    captured_kwargs = {}

    def fake_to_ass_karaoke(events, style="default", *, emoji_map=None,
                             brand_font=None, brand_primary_color=None):
        captured_kwargs["emoji_map"] = emoji_map
        return (
            "[Script Info]\n[V4+ Styles]\n"
            "Style: Default,Arial,48,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,"
            "1,0,0,0,100,100,0,0,1,3,1,2,10,10,30,1\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text\n"
        )

    with (
        patch("jobs.render_job._load_words_for_clip", return_value=words),
        patch("jobs.render_job._resolve_music_track", return_value=None),
        patch("adapters.ffmpeg.run_ffmpeg_cmd"),
        patch("os.path.join", side_effect=lambda *a: "/".join(a)),
        patch("core.captions.to_ass_karaoke", fake_to_ass_karaoke),
    ):
        from jobs.render_job import _apply_track_a_engines
        _apply_track_a_engines("/tmp/clip.mp4", spec, "/tmp", 1, 0)

    # emoji_map is not None when emoji_highlights=True
    assert captured_kwargs.get("emoji_map") is not None


def test_emoji_highlights_disabled_passes_none_emoji_map():
    spec = ClipRenderSpec(
        captions=CaptionsSpec(style="tiktok_pop"),
        emoji_highlights=False,
    )
    words = [{"word": "roof", "start": 0.0, "end": 0.4}]

    captured_kwargs: dict = {}

    def fake_to_ass_karaoke(events, style="default", *, emoji_map=None,
                             brand_font=None, brand_primary_color=None):
        captured_kwargs["called"] = True
        captured_kwargs["emoji_map"] = emoji_map
        return (
            "[Script Info]\n[V4+ Styles]\n"
            "Style: Default,Arial,48,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,"
            "1,0,0,0,100,100,0,0,1,3,1,2,10,10,30,1\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text\n"
        )

    with (
        patch("jobs.render_job._load_words_for_clip", return_value=words),
        patch("jobs.render_job._resolve_music_track", return_value=None),
        patch("adapters.ffmpeg.run_ffmpeg_cmd"),
        patch("os.path.join", side_effect=lambda *a: "/".join(a)),
        patch("core.captions.to_ass_karaoke", fake_to_ass_karaoke),
    ):
        from jobs.render_job import _apply_track_a_engines
        _apply_track_a_engines("/tmp/clip.mp4", spec, "/tmp", 1, 0)

    assert captured_kwargs.get("emoji_map") is None


# ---------------------------------------------------------------------------
# Brand-kit caption theming: brand_kit param reaches to_ass_karaoke
# ---------------------------------------------------------------------------

def test_brand_kit_font_and_color_passed_to_captions():
    spec = ClipRenderSpec(captions=CaptionsSpec(style="tiktok_pop"))
    words = [{"word": "roof", "start": 0.0, "end": 0.4}]
    brand_kit = {"font_heading": "Montserrat", "primary_color": "#1a3c5e"}

    captured_kwargs = {}

    def fake_to_ass_karaoke(events, style="default", *, emoji_map=None,
                             brand_font=None, brand_primary_color=None):
        captured_kwargs["brand_font"] = brand_font
        captured_kwargs["brand_primary_color"] = brand_primary_color
        return (
            "[Script Info]\n[V4+ Styles]\n"
            "Style: Default,Arial,48,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,"
            "1,0,0,0,100,100,0,0,1,3,1,2,10,10,30,1\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text\n"
        )

    with (
        patch("jobs.render_job._load_words_for_clip", return_value=words),
        patch("jobs.render_job._resolve_music_track", return_value=None),
        patch("adapters.ffmpeg.run_ffmpeg_cmd"),
        patch("os.path.join", side_effect=lambda *a: "/".join(a)),
        patch("core.captions.to_ass_karaoke", fake_to_ass_karaoke),
    ):
        from jobs.render_job import _apply_track_a_engines
        _apply_track_a_engines(
            "/tmp/clip.mp4", spec, "/tmp", 1, 0, brand_kit=brand_kit,
        )

    assert captured_kwargs.get("brand_font") == "Montserrat"
    assert captured_kwargs.get("brand_primary_color") == "#1a3c5e"


def test_no_brand_kit_passes_none_to_captions():
    spec = ClipRenderSpec(captions=CaptionsSpec(style="tiktok_pop"))
    words = [{"word": "roof", "start": 0.0, "end": 0.4}]

    captured_kwargs = {}

    def fake_to_ass_karaoke(events, style="default", *, emoji_map=None,
                             brand_font=None, brand_primary_color=None):
        captured_kwargs["brand_font"] = brand_font
        captured_kwargs["brand_primary_color"] = brand_primary_color
        return (
            "[Script Info]\n[V4+ Styles]\n"
            "Style: Default,Arial,48,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,"
            "1,0,0,0,100,100,0,0,1,3,1,2,10,10,30,1\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text\n"
        )

    with (
        patch("jobs.render_job._load_words_for_clip", return_value=words),
        patch("jobs.render_job._resolve_music_track", return_value=None),
        patch("adapters.ffmpeg.run_ffmpeg_cmd"),
        patch("os.path.join", side_effect=lambda *a: "/".join(a)),
        patch("core.captions.to_ass_karaoke", fake_to_ass_karaoke),
    ):
        from jobs.render_job import _apply_track_a_engines
        _apply_track_a_engines("/tmp/clip.mp4", spec, "/tmp", 1, 0)

    assert captured_kwargs.get("brand_font") is None
    assert captured_kwargs.get("brand_primary_color") is None
