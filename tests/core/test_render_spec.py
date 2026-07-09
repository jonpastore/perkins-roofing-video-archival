"""100% coverage tests for core/render_spec.py (pure, no I/O)."""
import pytest

from core.render_spec import (
    build_filtergraph,
    output_args,
    _W,
    _H,
    ClipRenderSpec,
    CaptionsSpec,
    BrollSpec,
    MusicSpec,
    FxSpec,
    get_clips,
    get_render_spec,
    set_render_spec,
)


# ---------------------------------------------------------------------------
# build_filtergraph
# ---------------------------------------------------------------------------

def test_build_filtergraph_returns_string():
    fg = build_filtergraph(3.0, 3.0)
    assert isinstance(fg, fg.__class__)  # always str
    assert isinstance(fg, str)


def test_filtergraph_contains_scale_1080_1920():
    fg = build_filtergraph(3.0, 3.0)
    assert f"scale={_W}:{_H}" in fg


def test_filtergraph_contains_force_original_aspect_ratio():
    fg = build_filtergraph(3.0, 3.0)
    assert "force_original_aspect_ratio=decrease" in fg


def test_filtergraph_contains_pad():
    fg = build_filtergraph(3.0, 3.0)
    assert "pad=" in fg


def test_filtergraph_contains_setsar():
    fg = build_filtergraph(3.0, 3.0)
    assert "setsar=1" in fg


def test_filtergraph_contains_loudnorm():
    fg = build_filtergraph(3.0, 3.0)
    assert "loudnorm" in fg
    assert "I=-14" in fg


def test_filtergraph_contains_concat():
    fg = build_filtergraph(3.0, 3.0)
    assert "concat=n=3" in fg


def test_filtergraph_three_video_streams_scaled():
    """All three segments must have their video scaled/padded."""
    fg = build_filtergraph(3.0, 3.0)
    # v0, v1, v2 output labels must all be present
    assert "[v0]" in fg
    assert "[v1]" in fg
    assert "[v2]" in fg


def test_filtergraph_three_audio_streams():
    """All three segments must have audio labels."""
    fg = build_filtergraph(3.0, 3.0)
    assert "[a0]" in fg
    assert "[a1]" in fg
    assert "[a2]" in fg


def test_filtergraph_output_labels():
    fg = build_filtergraph(3.0, 3.0)
    assert "[vout]" in fg
    assert "[aout]" in fg


def test_filtergraph_title_silence_uses_title_secs():
    fg = build_filtergraph(5.0, 3.0)
    assert "duration=5.000000" in fg


def test_filtergraph_closing_silence_uses_closing_secs():
    fg = build_filtergraph(3.0, 7.5)
    assert "duration=7.500000" in fg


def test_filtergraph_is_deterministic():
    assert build_filtergraph(3.0, 3.0) == build_filtergraph(3.0, 3.0)


def test_filtergraph_different_secs_differ():
    assert build_filtergraph(2.0, 3.0) != build_filtergraph(3.0, 3.0)


def test_filtergraph_stereo_48k_silence():
    fg = build_filtergraph(3.0, 3.0)
    assert "channel_layout=stereo" in fg
    assert "sample_rate=48000" in fg


def test_filtergraph_audio_48k_sample_rate():
    """Loudnorm is applied to the clip audio stream ([1:a])."""
    fg = build_filtergraph(3.0, 3.0)
    assert "[1:a]loudnorm" in fg


def test_filtergraph_semicolon_separated():
    """filter_complex segments must be semicolon-separated."""
    fg = build_filtergraph(3.0, 3.0)
    assert ";" in fg


# ---------------------------------------------------------------------------
# output_args
# ---------------------------------------------------------------------------

def test_output_args_returns_list():
    args = output_args()
    assert isinstance(args, list)


def test_output_args_has_libx264():
    assert "libx264" in output_args()


def test_output_args_high_profile():
    args = output_args()
    idx = args.index("-profile:v")
    assert args[idx + 1] == "high"


def test_output_args_faststart():
    args = output_args()
    idx = args.index("-movflags")
    assert "+faststart" in args[idx + 1]


def test_output_args_yuv420p():
    assert "yuv420p" in output_args()


def test_output_args_aac():
    assert "aac" in output_args()


def test_output_args_128k():
    args = output_args()
    idx = args.index("-b:a")
    assert args[idx + 1] == "128k"


def test_output_args_48000():
    args = output_args()
    idx = args.index("-ar")
    assert args[idx + 1] == "48000"


def test_output_args_is_deterministic():
    assert output_args() == output_args()


def test_output_args_even_length():
    """Each flag must have a value — list must be even-length."""
    assert len(output_args()) % 2 == 0


def test_filtergraph_aformat_on_clip_audio():
    """aformat must follow loudnorm on the clip audio stream so the concat
    filter receives matching sample_fmts/sample_rates/channel_layouts from
    all three segments (silence cards + clip)."""
    fg = build_filtergraph(3.0, 3.0)
    assert "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo" in fg


def test_filtergraph_aformat_after_loudnorm():
    """aformat must appear after loudnorm in the filter chain (same segment)."""
    fg = build_filtergraph(3.0, 3.0)
    loudnorm_pos = fg.index("loudnorm")
    aformat_pos = fg.index("aformat")
    assert aformat_pos > loudnorm_pos


# ---------------------------------------------------------------------------
# ClipRenderSpec — defaults
# ---------------------------------------------------------------------------

def test_render_spec_defaults():
    spec = ClipRenderSpec()
    assert spec.reframe is False
    assert spec.speech_cleanup is False
    assert spec.captions.style == "default"
    assert spec.captions.position == "bottom"
    assert spec.broll.source == "none"
    assert spec.broll.query_auto is True
    assert spec.music.catalog == "none"
    assert spec.music.track_id == ""
    assert spec.music.volume_db == -18.0
    assert spec.fx.transition == "cut"
    assert spec.fx.color_grade == "none"
    assert spec.fx.title_card is True


def test_render_spec_roundtrip():
    spec = ClipRenderSpec(
        reframe=True,
        speech_cleanup=True,
        captions=CaptionsSpec(style="bold_yellow", position="top"),
        broll=BrollSpec(source="pexels", query_auto=False),
        music=MusicSpec(catalog="pixabay", track_id="upbeat-001", volume_db=-20.0),
        fx=FxSpec(transition="fade", color_grade="vivid", title_card=False),
    )
    data = spec.to_dict()
    spec2 = ClipRenderSpec.from_dict(data)
    assert spec2.reframe is True
    assert spec2.speech_cleanup is True
    assert spec2.captions.style == "bold_yellow"
    assert spec2.broll.source == "pexels"
    assert spec2.music.catalog == "pixabay"
    assert spec2.music.track_id == "upbeat-001"
    assert spec2.music.volume_db == -20.0
    assert spec2.fx.transition == "fade"
    assert spec2.fx.color_grade == "vivid"
    assert spec2.fx.title_card is False


def test_render_spec_from_none_returns_defaults():
    spec = ClipRenderSpec.from_dict(None)
    assert spec.reframe is False
    assert spec.captions.style == "default"


def test_render_spec_from_empty_dict_returns_defaults():
    spec = ClipRenderSpec.from_dict({})
    assert spec.reframe is False


def test_render_spec_partial_dict():
    spec = ClipRenderSpec.from_dict({"reframe": True})
    assert spec.reframe is True
    assert spec.speech_cleanup is False


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

def test_captions_invalid_style_raises():
    with pytest.raises(Exception):
        CaptionsSpec(style="neon_rainbow")


def test_broll_invalid_source_raises():
    with pytest.raises(Exception):
        BrollSpec(source="shutterstock")


def test_music_invalid_catalog_raises():
    with pytest.raises(Exception):
        MusicSpec(catalog="spotify")


def test_music_volume_too_high_raises():
    with pytest.raises(Exception):
        MusicSpec(volume_db=1.0)


def test_music_volume_too_low_raises():
    with pytest.raises(Exception):
        MusicSpec(volume_db=-100.0)


def test_fx_invalid_transition_raises():
    with pytest.raises(Exception):
        FxSpec(transition="zoom_punch")


def test_fx_invalid_color_grade_raises():
    with pytest.raises(Exception):
        FxSpec(color_grade="sepia")


# ---------------------------------------------------------------------------
# broll_enabled / music_enabled gates
# ---------------------------------------------------------------------------

def test_broll_enabled_requires_pexels_key():
    spec = ClipRenderSpec(broll=BrollSpec(source="pexels"))
    assert spec.broll_enabled(pexels_key_present=False) is False
    assert spec.broll_enabled(pexels_key_present=True) is True


def test_broll_disabled_when_source_none():
    spec = ClipRenderSpec(broll=BrollSpec(source="none"))
    assert spec.broll_enabled(pexels_key_present=True) is False


def test_music_enabled_requires_track_id():
    spec = ClipRenderSpec(music=MusicSpec(catalog="pixabay", track_id=""))
    assert spec.music_enabled() is False


def test_music_enabled_with_track_id():
    spec = ClipRenderSpec(music=MusicSpec(catalog="pixabay", track_id="upbeat-001"))
    assert spec.music_enabled() is True


def test_music_disabled_when_catalog_none():
    spec = ClipRenderSpec(music=MusicSpec(catalog="none", track_id="upbeat-001"))
    assert spec.music_enabled() is False


# ---------------------------------------------------------------------------
# parts_json envelope helpers
# ---------------------------------------------------------------------------

def test_get_clips_from_list():
    clips = [{"title": "T", "start": 0.0, "end": 10.0}]
    assert get_clips(clips) == clips


def test_get_clips_from_envelope():
    clips = [{"title": "T", "start": 0.0, "end": 10.0}]
    assert get_clips({"clips": clips, "render_spec": {}}) == clips


def test_get_clips_from_none():
    assert get_clips(None) == []


def test_get_clips_from_empty_envelope():
    assert get_clips({}) == []


def test_get_render_spec_from_list_returns_defaults():
    spec = get_render_spec([{"title": "T", "start": 0.0, "end": 10.0}])
    assert isinstance(spec, ClipRenderSpec)
    assert spec.reframe is False


def test_get_render_spec_from_envelope():
    envelope = {"clips": [], "render_spec": {"reframe": True}}
    spec = get_render_spec(envelope)
    assert spec.reframe is True


def test_get_render_spec_from_none():
    spec = get_render_spec(None)
    assert isinstance(spec, ClipRenderSpec)


def test_set_render_spec_upgrades_list():
    clips = [{"title": "T", "start": 0.0, "end": 10.0}]
    spec = ClipRenderSpec(reframe=True)
    envelope = set_render_spec(clips, spec)
    assert envelope["clips"] == clips
    assert envelope["render_spec"]["reframe"] is True


def test_set_render_spec_preserves_existing_clips():
    clips = [{"title": "C1", "start": 0.0, "end": 5.0}]
    old_envelope = {"clips": clips, "render_spec": {"reframe": False}}
    spec = ClipRenderSpec(reframe=True, speech_cleanup=True)
    new_envelope = set_render_spec(old_envelope, spec)
    assert new_envelope["clips"] == clips
    assert new_envelope["render_spec"]["reframe"] is True
    assert new_envelope["render_spec"]["speech_cleanup"] is True


def test_render_spec_to_dict_is_json_serialisable():
    import json
    spec = ClipRenderSpec(reframe=True, music=MusicSpec(catalog="pixabay", track_id="t1"))
    data = spec.to_dict()
    assert json.dumps(data)  # must not raise
