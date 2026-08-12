"""100% line-coverage tests for core.audio_enhance (Item 10).

Covers:
- build_enhance_filter: all flag combinations, custom LUFS, filter ordering,
  afftdn/acompressor/loudnorm presence, comma-separation.
- build_enhance_cmd: arg-list structure, -af value, -c:v copy, out path last,
  no shell string, custom LUFS, flag combinations.
"""
from __future__ import annotations

import pytest

import core.audio_enhance as ae


# ---------------------------------------------------------------------------
# build_enhance_filter
# ---------------------------------------------------------------------------


class TestBuildEnhanceFilter:
    def test_returns_string(self) -> None:
        assert isinstance(ae.build_enhance_filter(), str)

    def test_default_contains_afftdn(self) -> None:
        f = ae.build_enhance_filter()
        assert "afftdn" in f

    def test_default_contains_acompressor(self) -> None:
        f = ae.build_enhance_filter()
        assert "acompressor" in f

    def test_default_contains_loudnorm(self) -> None:
        f = ae.build_enhance_filter()
        assert "loudnorm" in f

    def test_loudnorm_is_last_filter(self) -> None:
        f = ae.build_enhance_filter()
        parts = f.split(",")
        assert parts[-1].startswith("loudnorm=")

    def test_default_lufs_minus14(self) -> None:
        f = ae.build_enhance_filter()
        assert "I=-14.0" in f

    def test_custom_lufs(self) -> None:
        f = ae.build_enhance_filter(target_lufs=-23.0)
        assert "I=-23.0" in f
        assert "I=-14.0" not in f

    def test_denoise_false_no_afftdn(self) -> None:
        f = ae.build_enhance_filter(denoise=False, compress=True)
        assert "afftdn" not in f
        assert "acompressor" in f
        assert "loudnorm" in f

    def test_compress_false_no_acompressor(self) -> None:
        f = ae.build_enhance_filter(denoise=True, compress=False)
        assert "afftdn" in f
        assert "acompressor" not in f
        assert "loudnorm" in f

    def test_both_false_loudnorm_only(self) -> None:
        f = ae.build_enhance_filter(denoise=False, compress=False)
        assert f.startswith("loudnorm=")
        assert "afftdn" not in f
        assert "acompressor" not in f

    def test_lra_present(self) -> None:
        f = ae.build_enhance_filter()
        assert "LRA=11" in f

    def test_tp_present(self) -> None:
        f = ae.build_enhance_filter()
        assert "TP=-1.5" in f

    def test_afftdn_nf_value(self) -> None:
        f = ae.build_enhance_filter()
        assert "afftdn=nf=-25" in f

    def test_acompressor_threshold(self) -> None:
        f = ae.build_enhance_filter()
        assert "threshold=-18dB" in f

    def test_filter_order_afftdn_before_acompressor(self) -> None:
        f = ae.build_enhance_filter(denoise=True, compress=True)
        assert f.index("afftdn") < f.index("acompressor")

    def test_filter_order_acompressor_before_loudnorm(self) -> None:
        f = ae.build_enhance_filter(denoise=True, compress=True)
        assert f.index("acompressor") < f.index("loudnorm")

    def test_comma_separated(self) -> None:
        f = ae.build_enhance_filter(denoise=True, compress=True)
        assert "," in f
        assert isinstance(f, str)

    def test_lufs_out_of_range_positive_raises(self) -> None:
        with pytest.raises(ValueError, match="target_lufs"):
            ae.build_enhance_filter(target_lufs=1.0)

    def test_lufs_out_of_range_too_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="target_lufs"):
            ae.build_enhance_filter(target_lufs=-71.0)

    def test_lufs_boundary_zero_ok(self) -> None:
        f = ae.build_enhance_filter(target_lufs=0.0)
        assert "I=0.0" in f

    def test_lufs_boundary_minus70_ok(self) -> None:
        f = ae.build_enhance_filter(target_lufs=-70.0)
        assert "I=-70.0" in f


# ---------------------------------------------------------------------------
# build_enhance_cmd
# ---------------------------------------------------------------------------


class TestBuildEnhanceCmd:
    def test_returns_list(self) -> None:
        cmd = ae.build_enhance_cmd("in.mp4", "out.mp4")
        assert isinstance(cmd, list)

    def test_all_elements_strings(self) -> None:
        cmd = ae.build_enhance_cmd("in.mp4", "out.mp4")
        assert all(isinstance(x, str) for x in cmd)

    def test_overwrite_flag(self) -> None:
        cmd = ae.build_enhance_cmd("in.mp4", "out.mp4")
        assert "-y" in cmd

    def test_input_flag_before_path(self) -> None:
        cmd = ae.build_enhance_cmd("/a/b.mp4", "out.mp4")
        i = cmd.index("-i")
        assert cmd[i + 1] == "/a/b.mp4"

    def test_out_path_is_last(self) -> None:
        cmd = ae.build_enhance_cmd("in.mp4", "/tmp/out.mp4")
        assert cmd[-1] == "/tmp/out.mp4"

    def test_af_flag_present(self) -> None:
        cmd = ae.build_enhance_cmd("in.mp4", "out.mp4")
        assert "-af" in cmd

    def test_af_value_contains_loudnorm(self) -> None:
        cmd = ae.build_enhance_cmd("in.mp4", "out.mp4")
        idx = cmd.index("-af")
        assert "loudnorm" in cmd[idx + 1]

    def test_af_value_contains_afftdn_when_denoise(self) -> None:
        cmd = ae.build_enhance_cmd("in.mp4", "out.mp4", denoise=True)
        idx = cmd.index("-af")
        assert "afftdn" in cmd[idx + 1]

    def test_af_value_no_afftdn_when_denoise_false(self) -> None:
        cmd = ae.build_enhance_cmd("in.mp4", "out.mp4", denoise=False, compress=False)
        idx = cmd.index("-af")
        assert "afftdn" not in cmd[idx + 1]

    def test_video_copy_flag(self) -> None:
        cmd = ae.build_enhance_cmd("in.mp4", "out.mp4")
        assert "-c:v" in cmd
        i = cmd.index("-c:v")
        assert cmd[i + 1] == "copy"

    def test_custom_lufs_reflected(self) -> None:
        cmd = ae.build_enhance_cmd("in.mp4", "out.mp4", target_lufs=-16.0)
        idx = cmd.index("-af")
        assert "I=-16.0" in cmd[idx + 1]

    def test_no_shell_string(self) -> None:
        cmd = ae.build_enhance_cmd("in.mp4 && evil", "out.mp4")
        assert "in.mp4 && evil" in cmd

    def test_acompressor_when_compress_true(self) -> None:
        cmd = ae.build_enhance_cmd("in.mp4", "out.mp4", compress=True)
        idx = cmd.index("-af")
        assert "acompressor" in cmd[idx + 1]

    def test_no_acompressor_when_compress_false(self) -> None:
        cmd = ae.build_enhance_cmd("in.mp4", "out.mp4", compress=False)
        idx = cmd.index("-af")
        assert "acompressor" not in cmd[idx + 1]

    def test_invalid_lufs_propagates(self) -> None:
        with pytest.raises(ValueError, match="target_lufs"):
            ae.build_enhance_cmd("in.mp4", "out.mp4", target_lufs=5.0)


# ---------------------------------------------------------------------------
# Wind / outdoor profile
# ---------------------------------------------------------------------------
# core/audio_enhance.py's afftdn=-25 is tuned by its own comment for "HVAC/room
# noise" — indoor and stationary. Tim shoots outdoors on a phone, where the
# dominant noise is wind: low-frequency and non-stationary, which afftdn chases
# rather than subtracts, and which nothing in the default chain high-passes.

class TestWindProfile:
    def test_default_chain_is_byte_identical(self):
        """THE regression pin. This filter runs on every enhanced render, so a
        silent change here alters output for clips already approved. If the wind
        work ever leaks into the default path, this fails."""
        from core.audio_enhance import build_enhance_filter

        assert build_enhance_filter() == (
            "afftdn=nf=-25,"
            "acompressor=threshold=-18dB:ratio=4:attack=10:release=150:makeup=2dB,"
            "loudnorm=I=-14.0:LRA=11:TP=-1.5"
        )

    def test_wind_prepends_a_highpass(self):
        """The high-pass does the real work: wind energy sits below ~100 Hz, under
        the fundamental of adult speech, so it comes out without touching voice."""
        from core.audio_enhance import build_enhance_filter

        out = build_enhance_filter(wind=True)
        assert out.startswith("highpass=f=90,"), out

    def test_wind_softens_the_denoiser(self):
        """Gentler than indoor: over-denoising outdoor audio produces watery
        artefacting that sounds worse than the wind it removed."""
        from core.audio_enhance import build_enhance_filter

        assert "afftdn=nf=-20" in build_enhance_filter(wind=True)
        assert "afftdn=nf=-25" in build_enhance_filter(wind=False)

    def test_highpass_comes_before_the_denoiser(self):
        """Order is load-bearing. Denoising first makes afftdn build its noise
        profile from the rumble we are about to discard."""
        from core.audio_enhance import build_enhance_filter

        out = build_enhance_filter(wind=True)
        assert out.index("highpass") < out.index("afftdn")

    def test_wind_still_high_passes_with_denoise_off(self):
        """The two are independent knobs — turning the denoiser off must not
        silently drop the wind treatment."""
        from core.audio_enhance import build_enhance_filter

        out = build_enhance_filter(wind=True, denoise=False)
        assert "highpass=f=90" in out
        assert "afftdn" not in out

    def test_wind_reaches_the_command(self):
        """Grep the READER, not the key — a flag the command builder ignores is
        this repo's most-repeated defect."""
        from core.audio_enhance import build_enhance_cmd

        cmd = build_enhance_cmd("in.mp4", "out.mp4", wind=True)
        assert "highpass=f=90" in cmd[cmd.index("-af") + 1]
        assert "-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "copy"

    def test_wind_still_validates_target_lufs(self):
        import pytest as _pytest

        from core.audio_enhance import build_enhance_filter

        with _pytest.raises(ValueError):
            build_enhance_filter(target_lufs=5.0, wind=True)
