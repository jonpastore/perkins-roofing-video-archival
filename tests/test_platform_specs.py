from core.platform_specs import PLATFORM_SPECS, validate

_CONFORMING = {
    "duration_seconds": 30, "width": 1080, "height": 1920,
    "size_mb": 50, "codec_video": "h264", "codec_audio": "aac",
}


def test_conforming_clip_passes_all():
    for platform in PLATFORM_SPECS:
        assert validate(_CONFORMING, platform) == []


def test_overlong_fails_short_cap_platforms():
    meta = {**_CONFORMING, "duration_seconds": 120}
    for p in ["instagram", "youtube_shorts", "facebook"]:
        assert validate(meta, p) != []
    for p in ["tiktok", "linkedin", "x", "pinterest"]:
        assert validate(meta, p) == []


def test_unknown_platform():
    assert validate(_CONFORMING, "unknown") == ["unknown platform 'unknown'"]
