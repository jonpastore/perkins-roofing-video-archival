"""scene_boundaries finds cut points at speech gaps."""
from core.scene_detect import scene_boundaries


def _w(*starts):
    return [{"word": "x", "start": s} for s in starts]


def test_empty_returns_empty():
    assert scene_boundaries([]) == []


def test_first_word_is_always_a_boundary():
    assert scene_boundaries(_w(0.0, 0.3, 0.6)) == [0.0]  # no gaps


def test_gap_starts_new_scene():
    # 0.0..1.0 speech, 2.0s pause, resume at 3.0
    b = scene_boundaries(_w(0.0, 0.5, 1.0, 3.0, 3.5), gap_threshold=1.2, min_scene=2.5)
    assert b == [0.0, 3.0]


def test_min_scene_suppresses_close_boundaries():
    # a big gap at 1.5 but < min_scene from the start -> dropped
    assert scene_boundaries(_w(0.0, 1.5, 3.0), gap_threshold=1.0, min_scene=2.5) == [0.0, 3.0]


def test_unordered_input_sorted():
    assert scene_boundaries(_w(3.0, 0.0, 0.5), gap_threshold=1.2, min_scene=2.5) == [0.0, 3.0]
