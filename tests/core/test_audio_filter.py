"""100% line-coverage tests for core.audio_filter.

Tests cover:
  - denoise_loudnorm_chain: all flag combinations (denoise+dereverb, denoise-only,
    dereverb-only, neither), custom LUFS, filter ordering.
  - build_audio_cmd: arg-list type, structure, in/out paths present, -af value,
    loudnorm target, afftdn presence when denoise=True.
"""
from __future__ import annotations

import core.audio_filter as af

# ---------------------------------------------------------------------------
# denoise_loudnorm_chain
# ---------------------------------------------------------------------------


class TestDenoiseLoudnormChain:
    def test_default_contains_afftdn_and_loudnorm(self) -> None:
        chain = af.denoise_loudnorm_chain()
        assert "afftdn" in chain
        assert "loudnorm" in chain

    def test_default_lufs_minus14(self) -> None:
        chain = af.denoise_loudnorm_chain()
        assert "I=-14.0" in chain

    def test_custom_lufs(self) -> None:
        chain = af.denoise_loudnorm_chain(target_lufs=-16.0)
        assert "I=-16.0" in chain
        assert "I=-14.0" not in chain

    def test_denoise_true_includes_afftdn(self) -> None:
        chain = af.denoise_loudnorm_chain(denoise=True, dereverb=False)
        assert "afftdn=nf=-25" in chain

    def test_denoise_false_no_afftdn_nf(self) -> None:
        chain = af.denoise_loudnorm_chain(denoise=False, dereverb=False)
        assert "afftdn=nf=-25" not in chain

    def test_dereverb_true_includes_dereverb_afftdn(self) -> None:
        chain = af.denoise_loudnorm_chain(denoise=False, dereverb=True)
        assert "afftdn=nr=10" in chain

    def test_dereverb_false_no_dereverb_afftdn(self) -> None:
        chain = af.denoise_loudnorm_chain(denoise=True, dereverb=False)
        assert "afftdn=nr=10" not in chain

    def test_denoise_and_dereverb_both_true(self) -> None:
        chain = af.denoise_loudnorm_chain(denoise=True, dereverb=True)
        assert "afftdn=nf=-25" in chain
        assert "afftdn=nr=10" in chain
        assert "loudnorm" in chain

    def test_neither_denoise_nor_dereverb(self) -> None:
        chain = af.denoise_loudnorm_chain(denoise=False, dereverb=False)
        # Should be loudnorm only
        assert chain.startswith("loudnorm=")
        assert "afftdn" not in chain

    def test_loudnorm_is_last_filter(self) -> None:
        """loudnorm must come after any afftdn passes."""
        chain = af.denoise_loudnorm_chain(denoise=True, dereverb=True)
        parts = chain.split(",")
        assert parts[-1].startswith("loudnorm=")

    def test_filters_comma_separated_string(self) -> None:
        chain = af.denoise_loudnorm_chain(denoise=True, dereverb=True)
        # Comma-separated, not a list
        assert isinstance(chain, str)
        assert "," in chain

    def test_lra_and_tp_present(self) -> None:
        chain = af.denoise_loudnorm_chain()
        assert "LRA=11" in chain
        assert "TP=-1.5" in chain


# ---------------------------------------------------------------------------
# build_audio_cmd
# ---------------------------------------------------------------------------


class TestBuildAudioCmd:
    def test_returns_list(self) -> None:
        cmd = af.build_audio_cmd("in.mp4", "out.m4a")
        assert isinstance(cmd, list)

    def test_all_elements_are_strings(self) -> None:
        cmd = af.build_audio_cmd("in.mp4", "out.m4a")
        assert all(isinstance(x, str) for x in cmd)

    def test_in_path_present(self) -> None:
        cmd = af.build_audio_cmd("/tmp/src.mp4", "/tmp/dst.m4a")
        assert "/tmp/src.mp4" in cmd

    def test_out_path_present(self) -> None:
        cmd = af.build_audio_cmd("/tmp/src.mp4", "/tmp/dst.m4a")
        assert "/tmp/dst.m4a" in cmd

    def test_out_path_is_last_element(self) -> None:
        cmd = af.build_audio_cmd("in.mp4", "out.m4a")
        assert cmd[-1] == "out.m4a"

    def test_overwrite_flag(self) -> None:
        cmd = af.build_audio_cmd("in.mp4", "out.m4a")
        assert "-y" in cmd

    def test_af_flag_present(self) -> None:
        cmd = af.build_audio_cmd("in.mp4", "out.m4a")
        assert "-af" in cmd

    def test_af_value_contains_loudnorm(self) -> None:
        cmd = af.build_audio_cmd("in.mp4", "out.m4a")
        idx = cmd.index("-af")
        af_value = cmd[idx + 1]
        assert "loudnorm" in af_value

    def test_af_value_contains_afftdn_when_denoise(self) -> None:
        cmd = af.build_audio_cmd("in.mp4", "out.m4a", denoise=True)
        idx = cmd.index("-af")
        af_value = cmd[idx + 1]
        assert "afftdn" in af_value

    def test_af_value_no_afftdn_when_denoise_false(self) -> None:
        cmd = af.build_audio_cmd("in.mp4", "out.m4a", denoise=False, dereverb=False)
        idx = cmd.index("-af")
        af_value = cmd[idx + 1]
        assert "afftdn" not in af_value

    def test_custom_lufs_reflected_in_af(self) -> None:
        cmd = af.build_audio_cmd("in.mp4", "out.m4a", target_lufs=-23.0)
        idx = cmd.index("-af")
        af_value = cmd[idx + 1]
        assert "I=-23.0" in af_value

    def test_vn_flag_drops_video_stream(self) -> None:
        cmd = af.build_audio_cmd("in.mp4", "out.m4a")
        assert "-vn" in cmd

    def test_no_shell_string(self) -> None:
        """Confirm the command is a list, not a shell string — no injection surface."""
        cmd = af.build_audio_cmd("in.mp4 && rm -rf /", "out.m4a")
        # The dangerous string must appear as a single token (not parsed by shell)
        assert "in.mp4 && rm -rf /" in cmd

    def test_dereverb_reflected_in_af(self) -> None:
        cmd = af.build_audio_cmd("in.mp4", "out.m4a", denoise=False, dereverb=True)
        idx = cmd.index("-af")
        af_value = cmd[idx + 1]
        assert "afftdn=nr=10" in af_value

    def test_input_flag_before_in_path(self) -> None:
        cmd = af.build_audio_cmd("in.mp4", "out.m4a")
        i_idx = cmd.index("-i")
        assert cmd[i_idx + 1] == "in.mp4"
