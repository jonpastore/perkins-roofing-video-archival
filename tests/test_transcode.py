"""Per-platform conform primitives."""
from core.platform_specs import PLATFORM_SPECS
from core.transcode import conform_cmd, needs_conform, variants_for


def test_no_conform_for_short_clip():
    spec = PLATFORM_SPECS["instagram"]
    meta = {"duration_seconds": 30, "codec_video": "h264", "codec_audio": "aac"}
    assert needs_conform(meta, spec) is False
    assert conform_cmd("src.mp4", "out.mp4", spec, 30) is None


def test_conform_trims_overlong_clip_to_cap():
    spec = PLATFORM_SPECS["instagram"]  # 90s cap
    cmd = conform_cmd("src.mp4", "out.mp4", spec, 120)
    assert cmd is not None
    assert cmd[cmd.index("-t") + 1] == "90"
    assert "libx264" in cmd and "aac" in cmd


def test_needs_conform_on_codec_mismatch():
    spec = PLATFORM_SPECS["instagram"]
    assert needs_conform({"duration_seconds": 30, "codec_video": "hevc", "codec_audio": "aac"}, spec) is True


def test_variants_group_shared_output():
    d = variants_for(["instagram", "tiktok", "bogus"], 30)
    assert d == {"instagram": "30s", "tiktok": "30s"}  # unknown dropped, shared key
