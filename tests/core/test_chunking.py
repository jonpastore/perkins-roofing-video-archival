from dataclasses import dataclass

from core.chunking import chunk_segments


@dataclass
class Seg:
    text: str
    start: float
    end: float


def _segs(n):
    return [Seg(f"s{i}", float(i), float(i) + 0.5) for i in range(n)]


def test_exact_multiple():
    out = chunk_segments(_segs(4), 2)
    assert len(out) == 2
    assert out[0] == ("s0 s1", 0.0, 1.5)
    assert out[1] == ("s2 s3", 2.0, 3.5)


def test_remainder_forms_final_short_chunk():
    out = chunk_segments(_segs(5), 2)
    assert len(out) == 3
    assert out[2] == ("s4", 4.0, 4.5)


def test_single_segment():
    out = chunk_segments(_segs(1), 6)
    assert out == [("s0", 0.0, 0.5)]


def test_empty():
    assert chunk_segments([], 6) == []


def test_zero_chunk_size_does_not_crash():
    # CHUNK_SIZE is operator-editable; 0/negative must be clamped, not raise ValueError
    out = chunk_segments(_segs(3), 0)
    assert len(out) == 3          # clamped to 1 → one window per segment
    out2 = chunk_segments(_segs(3), -5)
    assert len(out2) == 3
