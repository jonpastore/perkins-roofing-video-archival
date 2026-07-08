"""100% line-coverage tests for core.clip_fx (A9, A10, A11).

A9  Transitions: build_transition_filter, build_concat_with_transitions
A10 Overlays:    build_overlay_filter (single + multiple, with/without end time)
A11 Floating text: build_floating_text_filter, _escape_drawtext
     — apostrophes ("Tim's"), filtergraph metacharacters (: , ; [ ]),
       single spec, multiple specs, box enabled, fontfile, empty raises ValueError.
"""
from __future__ import annotations

import pytest

import core.clip_fx as fx


# ---------------------------------------------------------------------------
# A9 — Transitions: build_transition_filter
# ---------------------------------------------------------------------------


class TestBuildTransitionFilter:
    def test_returns_string(self) -> None:
        r = fx.build_transition_filter(duration=0.5, offset=5.0)
        assert isinstance(r, str)

    def test_default_is_fade(self) -> None:
        r = fx.build_transition_filter(duration=0.5, offset=5.0)
        assert "transition=fade" in r

    def test_wipe_transition(self) -> None:
        r = fx.build_transition_filter(duration=0.5, offset=5.0, kind="wipe")
        assert "transition=wipeleft" in r

    def test_slide_transition(self) -> None:
        r = fx.build_transition_filter(duration=0.5, offset=5.0, kind="slide")
        assert "transition=slideleft" in r

    def test_dissolve_transition(self) -> None:
        r = fx.build_transition_filter(duration=0.5, offset=5.0, kind="dissolve")
        assert "transition=dissolve" in r

    def test_duration_in_output(self) -> None:
        r = fx.build_transition_filter(duration=1.25, offset=5.0)
        assert "duration=1.250000" in r

    def test_offset_in_output(self) -> None:
        r = fx.build_transition_filter(duration=0.5, offset=7.3)
        assert "offset=7.300000" in r

    def test_default_stream_labels(self) -> None:
        r = fx.build_transition_filter(duration=0.5, offset=5.0)
        assert "[0:v]" in r
        assert "[1:v]" in r

    def test_custom_stream_labels(self) -> None:
        r = fx.build_transition_filter(
            duration=0.5, offset=5.0,
            clip_a_stream="xf1", clip_b_stream="2:v",
        )
        assert "[xf1]" in r
        assert "[2:v]" in r

    def test_default_out_label(self) -> None:
        r = fx.build_transition_filter(duration=0.5, offset=5.0)
        assert "[vout]" in r

    def test_custom_out_label(self) -> None:
        r = fx.build_transition_filter(duration=0.5, offset=5.0, out_label="xf1")
        assert "[xf1]" in r

    def test_invalid_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported transition kind"):
            fx.build_transition_filter(duration=0.5, offset=5.0, kind="spin")


# ---------------------------------------------------------------------------
# A9 — Transitions: build_concat_with_transitions
# ---------------------------------------------------------------------------


class TestBuildConcatWithTransitions:
    def test_two_clips_default_fade(self) -> None:
        r = fx.build_concat_with_transitions(
            n_clips=2,
            transition_duration=0.5,
            clip_durations=[10.0, 10.0],
        )
        assert "xfade" in r
        assert "[vout]" in r

    def test_three_clips_produces_two_xfade_nodes(self) -> None:
        r = fx.build_concat_with_transitions(
            n_clips=3,
            transition_duration=0.5,
            clip_durations=[10.0, 10.0, 10.0],
        )
        # Two xfade calls separated by semicolon
        assert r.count("xfade") == 2
        assert "[vout]" in r

    def test_intermediate_labels_present(self) -> None:
        r = fx.build_concat_with_transitions(
            n_clips=3,
            transition_duration=0.5,
            clip_durations=[10.0, 10.0, 10.0],
        )
        assert "[xf1]" in r

    def test_transition_kind_wipe(self) -> None:
        r = fx.build_concat_with_transitions(
            n_clips=2,
            transition_duration=0.5,
            clip_durations=[10.0, 10.0],
            kind="wipe",
        )
        assert "transition=wipeleft" in r

    def test_transition_kind_slide(self) -> None:
        r = fx.build_concat_with_transitions(
            n_clips=2,
            transition_duration=0.5,
            clip_durations=[10.0, 10.0],
            kind="slide",
        )
        assert "transition=slideleft" in r

    def test_transition_kind_dissolve(self) -> None:
        r = fx.build_concat_with_transitions(
            n_clips=2,
            transition_duration=0.5,
            clip_durations=[10.0, 10.0],
            kind="dissolve",
        )
        assert "transition=dissolve" in r

    def test_offset_computed_correctly_two_clips(self) -> None:
        # offset = clip_duration[0] - transition_duration = 10.0 - 0.5 = 9.5
        r = fx.build_concat_with_transitions(
            n_clips=2,
            transition_duration=0.5,
            clip_durations=[10.0, 10.0],
        )
        assert "offset=9.500000" in r

    def test_offset_computed_correctly_three_clips(self) -> None:
        # First transition offset: 10.0 - 0.5 = 9.5
        # Second transition offset: 9.5 + (10.0 - 0.5) = 19.0
        r = fx.build_concat_with_transitions(
            n_clips=3,
            transition_duration=0.5,
            clip_durations=[10.0, 10.0, 10.0],
        )
        assert "offset=9.500000" in r
        assert "offset=19.000000" in r

    def test_n_clips_less_than_two_raises(self) -> None:
        with pytest.raises(ValueError, match="n_clips must be"):
            fx.build_concat_with_transitions(
                n_clips=1, transition_duration=0.5, clip_durations=[10.0]
            )

    def test_mismatched_clip_durations_raises(self) -> None:
        with pytest.raises(ValueError, match="clip_durations length"):
            fx.build_concat_with_transitions(
                n_clips=2, transition_duration=0.5, clip_durations=[10.0]
            )

    def test_invalid_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported transition kind"):
            fx.build_concat_with_transitions(
                n_clips=2, transition_duration=0.5, clip_durations=[10.0, 10.0], kind="zoom"
            )

    def test_semicolon_separates_nodes(self) -> None:
        r = fx.build_concat_with_transitions(
            n_clips=3, transition_duration=0.5, clip_durations=[10.0, 10.0, 10.0]
        )
        assert ";" in r

    def test_returns_string(self) -> None:
        r = fx.build_concat_with_transitions(
            n_clips=2, transition_duration=0.5, clip_durations=[10.0, 10.0]
        )
        assert isinstance(r, str)

    def test_input_stream_indices_correct(self) -> None:
        r = fx.build_concat_with_transitions(
            n_clips=3, transition_duration=0.5, clip_durations=[5.0, 5.0, 5.0]
        )
        assert "[1:v]" in r
        assert "[2:v]" in r


# ---------------------------------------------------------------------------
# A10 — Overlays
# ---------------------------------------------------------------------------


class TestBuildOverlayFilter:
    def test_single_overlay_returns_string(self) -> None:
        ov = fx.OverlaySpec(image_path="/logo.png", x="10", y="10", start=0.0, end=5.0)
        r = fx.build_overlay_filter([ov])
        assert isinstance(r, str)

    def test_single_overlay_contains_overlay_filter(self) -> None:
        ov = fx.OverlaySpec(image_path="/logo.png", x="10", y="10", start=0.0, end=5.0)
        r = fx.build_overlay_filter([ov])
        assert "overlay" in r

    def test_single_overlay_enable_between(self) -> None:
        ov = fx.OverlaySpec(image_path="/logo.png", x="10", y="10", start=1.0, end=4.0)
        r = fx.build_overlay_filter([ov])
        assert "between(t,1.000000,4.000000)" in r

    def test_single_overlay_no_end_omits_enable(self) -> None:
        ov = fx.OverlaySpec(image_path="/logo.png", x="50", y="50", start=0.0, end=None)
        r = fx.build_overlay_filter([ov])
        assert "enable" not in r

    def test_single_overlay_xy_in_output(self) -> None:
        ov = fx.OverlaySpec(image_path="/logo.png", x="W-w-10", y="H-h-10", start=0.0, end=5.0)
        r = fx.build_overlay_filter([ov])
        assert "x=W-w-10" in r
        assert "y=H-h-10" in r

    def test_single_overlay_vout_label(self) -> None:
        ov = fx.OverlaySpec(image_path="/logo.png", x="10", y="10", start=0.0, end=5.0)
        r = fx.build_overlay_filter([ov])
        assert "[vout]" in r

    def test_two_overlays_chained(self) -> None:
        ovs = [
            fx.OverlaySpec("/a.png", x="0", y="0", start=0.0, end=3.0),
            fx.OverlaySpec("/b.png", x="100", y="100", start=1.0, end=4.0),
        ]
        r = fx.build_overlay_filter(ovs)
        # First overlay produces intermediate label [ov0]
        assert "[ov0]" in r
        # Final output is [vout]
        assert "[vout]" in r
        # Two overlay nodes
        assert r.count("overlay") == 2

    def test_two_overlays_second_uses_intermediate(self) -> None:
        ovs = [
            fx.OverlaySpec("/a.png", x="0", y="0", start=0.0, end=3.0),
            fx.OverlaySpec("/b.png", x="100", y="100", start=1.0, end=4.0),
        ]
        r = fx.build_overlay_filter(ovs)
        # Second overlay must take [ov0] as its base
        assert "[ov0]" in r

    def test_three_overlays_intermediate_labels(self) -> None:
        ovs = [
            fx.OverlaySpec("/a.png", x="0", y="0"),
            fx.OverlaySpec("/b.png", x="10", y="10"),
            fx.OverlaySpec("/c.png", x="20", y="20"),
        ]
        r = fx.build_overlay_filter(ovs)
        assert "[ov0]" in r
        assert "[ov1]" in r
        assert "[vout]" in r

    def test_custom_base_stream(self) -> None:
        ov = fx.OverlaySpec("/logo.png", x="0", y="0")
        r = fx.build_overlay_filter([ov], base_stream="xf2")
        assert "[xf2]" in r

    def test_image_input_index_correct(self) -> None:
        ovs = [
            fx.OverlaySpec("/a.png", x="0", y="0"),
            fx.OverlaySpec("/b.png", x="10", y="10"),
        ]
        r = fx.build_overlay_filter(ovs)
        assert "[1:v]" in r
        assert "[2:v]" in r

    def test_empty_overlays_raises(self) -> None:
        with pytest.raises(ValueError, match="overlays list must not be empty"):
            fx.build_overlay_filter([])

    def test_overlay_spec_defaults(self) -> None:
        ov = fx.OverlaySpec("/logo.png")
        assert ov.x == "10"
        assert ov.y == "10"
        assert ov.start == 0.0
        assert ov.end is None

    def test_semicolon_separates_multiple_overlays(self) -> None:
        ovs = [fx.OverlaySpec("/a.png"), fx.OverlaySpec("/b.png")]
        r = fx.build_overlay_filter(ovs)
        assert ";" in r


# ---------------------------------------------------------------------------
# A11 — Floating text: _escape_drawtext
# ---------------------------------------------------------------------------


class TestEscapeDrawtext:
    def test_plain_text_unchanged(self) -> None:
        assert fx._escape_drawtext("Hello world") == "Hello world"

    def test_apostrophe_escaped(self) -> None:
        # "Tim's" -> "Tim'\'s"  (close, literal ', reopen)
        result = fx._escape_drawtext("Tim's")
        assert result == "Tim'\\''s"

    def test_double_apostrophe(self) -> None:
        result = fx._escape_drawtext("it's Tim's")
        assert result == "it'\\''s Tim'\\''s"

    def test_colon_not_further_escaped(self) -> None:
        # Colons are safe inside single quotes — no extra escaping needed
        result = fx._escape_drawtext("Hello: world")
        assert "Hello: world" in result

    def test_comma_not_further_escaped(self) -> None:
        result = fx._escape_drawtext("a, b")
        assert "a, b" in result

    def test_semicolon_not_further_escaped(self) -> None:
        result = fx._escape_drawtext("a; b")
        assert "a; b" in result

    def test_bracket_not_further_escaped(self) -> None:
        result = fx._escape_drawtext("[tag]")
        assert "[tag]" in result

    def test_empty_string(self) -> None:
        assert fx._escape_drawtext("") == ""


# ---------------------------------------------------------------------------
# A11 — Floating text: build_floating_text_filter
# ---------------------------------------------------------------------------


class TestBuildFloatingTextFilter:
    def _spec(self, text: str = "Hello", **kw) -> fx.TextOverlaySpec:
        return fx.TextOverlaySpec(text=text, **kw)

    def test_returns_string(self) -> None:
        r = fx.build_floating_text_filter([self._spec()])
        assert isinstance(r, str)

    def test_drawtext_present(self) -> None:
        r = fx.build_floating_text_filter([self._spec()])
        assert "drawtext" in r

    def test_expansion_none_present(self) -> None:
        r = fx.build_floating_text_filter([self._spec()])
        assert "expansion=none" in r

    def test_text_embedded(self) -> None:
        r = fx.build_floating_text_filter([self._spec("Hello world")])
        assert "text='Hello world'" in r

    def test_apostrophe_in_text_escaped(self) -> None:
        r = fx.build_floating_text_filter([self._spec("Tim's Roofing")])
        # The apostrophe must be escaped with the '\\'' sequence
        assert "Tim'\\''s Roofing" in r
        # The raw unescaped form must NOT appear
        assert "text='Tim's" not in r

    def test_filtergraph_colon_in_text_safe(self) -> None:
        r = fx.build_floating_text_filter([self._spec("Note: important")])
        assert "Note: important" in r

    def test_filtergraph_comma_in_text_safe(self) -> None:
        r = fx.build_floating_text_filter([self._spec("a, b")])
        assert "a, b" in r

    def test_filtergraph_semicolon_in_text_safe(self) -> None:
        r = fx.build_floating_text_filter([self._spec("a; b")])
        assert "a; b" in r

    def test_filtergraph_brackets_in_text_safe(self) -> None:
        r = fx.build_floating_text_filter([self._spec("[tag]")])
        assert "[tag]" in r

    def test_fontsize_in_output(self) -> None:
        r = fx.build_floating_text_filter([self._spec(fontsize=64)])
        assert "fontsize=64" in r

    def test_fontcolor_in_output(self) -> None:
        r = fx.build_floating_text_filter([self._spec(fontcolor="yellow")])
        assert "fontcolor=yellow" in r

    def test_position_xy_in_output(self) -> None:
        r = fx.build_floating_text_filter([self._spec(x="50", y="100")])
        assert "x=50" in r
        assert "y=100" in r

    def test_enable_between_in_output(self) -> None:
        r = fx.build_floating_text_filter([self._spec(start=1.0, end=4.0)])
        assert "between(t,1.000000,4.000000)" in r

    def test_default_position_center(self) -> None:
        r = fx.build_floating_text_filter([self._spec()])
        assert "x=(w-text_w)/2" in r
        assert "y=(h-text_h)/2" in r

    def test_box_disabled_by_default(self) -> None:
        r = fx.build_floating_text_filter([self._spec()])
        assert "box=1" not in r

    def test_box_enabled(self) -> None:
        r = fx.build_floating_text_filter([self._spec(box=True)])
        assert "box=1" in r
        assert "boxcolor=black@0.5" in r
        assert "boxborderw=5" in r

    def test_box_custom_color_and_border(self) -> None:
        r = fx.build_floating_text_filter(
            [self._spec(box=True, boxcolor="white@0.8", boxborderw=10)]
        )
        assert "boxcolor=white@0.8" in r
        assert "boxborderw=10" in r

    def test_fontfile_included_when_set(self) -> None:
        r = fx.build_floating_text_filter([self._spec(fontfile="/fonts/roboto.ttf")])
        assert "fontfile=/fonts/roboto.ttf" in r

    def test_fontfile_omitted_when_empty(self) -> None:
        r = fx.build_floating_text_filter([self._spec(fontfile="")])
        assert "fontfile" not in r

    def test_multiple_specs_comma_joined(self) -> None:
        specs = [
            fx.TextOverlaySpec("Top text", x="10", y="10", start=0.0, end=3.0),
            fx.TextOverlaySpec("Bottom text", x="10", y="H-50", start=1.0, end=4.0),
        ]
        r = fx.build_floating_text_filter(specs)
        # Two drawtext nodes separated by comma
        assert r.count("drawtext") == 2
        assert "," in r

    def test_multiple_specs_both_texts_present(self) -> None:
        specs = [
            fx.TextOverlaySpec("First"),
            fx.TextOverlaySpec("Second"),
        ]
        r = fx.build_floating_text_filter(specs)
        assert "First" in r
        assert "Second" in r

    def test_empty_specs_raises(self) -> None:
        with pytest.raises(ValueError, match="specs list must not be empty"):
            fx.build_floating_text_filter([])

    def test_text_overlay_spec_defaults(self) -> None:
        s = fx.TextOverlaySpec("Hi")
        assert s.x == "(w-text_w)/2"
        assert s.y == "(h-text_h)/2"
        assert s.start == 0.0
        assert s.end == 3.0
        assert s.fontsize == 48
        assert s.fontcolor == "white"
        assert s.box is False
        assert s.boxcolor == "black@0.5"
        assert s.boxborderw == 5
        assert s.fontfile == ""

    def test_base_stream_param_accepted(self) -> None:
        # base_stream is accepted for API symmetry — doesn't affect -vf output
        r = fx.build_floating_text_filter([self._spec()], base_stream="xf3")
        assert "drawtext" in r
