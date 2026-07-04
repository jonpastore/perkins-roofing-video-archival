from dataclasses import dataclass

from core.retrieval import link, rank


@dataclass
class Ch:
    id: int
    video_id: str


def test_link_builds_timecoded_youtube_url():
    assert link("abc123", 95.7) == "https://youtu.be/abc123?t=95"


def test_rank_vector_only_preserves_order():
    a, b = Ch(1, "v1"), Ch(2, "v2")
    out = rank([(a, 0.9), (b, 0.4)], [], set())
    assert [c.id for c, _ in out] == [1, 2]


def test_rank_lexical_boost_on_existing_reorders():
    a, b = Ch(1, "v1"), Ch(2, "v2")
    # b starts 0.05 ahead; a gets +0.15 lexical → a wins.
    out = rank([(a, 0.50), (b, 0.55)], [a], set())
    assert out[0][0].id == 1
    assert out[0][1] == 0.65


def test_rank_lexical_only_hit_gets_base_score():
    a = Ch(3, "v3")
    out = rank([], [a], set())
    assert out == [(a, 0.5)]


def test_rank_graph_boost_applies_by_video():
    a = Ch(1, "v1")
    out = rank([(a, 0.5)], [], {"v1"})
    assert out[0][1] == 0.6


def test_rank_truncates_to_k():
    hits = [(Ch(i, f"v{i}"), 1.0 - i * 0.01) for i in range(10)]
    out = rank(hits, [], set(), k=3)
    assert len(out) == 3
