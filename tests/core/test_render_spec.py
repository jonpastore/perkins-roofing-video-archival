"""100% coverage tests for core/render_spec.py (pure, no I/O)."""
import pytest

from core.render_spec import build_filtergraph, output_args, _W, _H


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
