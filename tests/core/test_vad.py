from core.vad import should_transcribe


def test_below_threshold_skips():
    assert should_transcribe(0.05) is False


def test_at_threshold_transcribes():
    assert should_transcribe(0.15) is True


def test_above_threshold_transcribes():
    assert should_transcribe(0.8) is True


def test_custom_threshold():
    assert should_transcribe(0.3, min_ratio=0.5) is False
