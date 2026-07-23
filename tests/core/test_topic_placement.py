"""core.topic_placement — content-hub placement (join existing pillar vs new pillar)."""

from core.topic_placement import cosine, place_topics


def _v(*xs):
    return list(xs)


def test_candidate_near_existing_pillar_becomes_its_cluster():
    pillars = [{"slug": "metal-roofing", "keyword": "metal roofing", "vec": _v(1, 0, 0)},
               {"slug": "tile-roof", "keyword": "tile roof", "vec": _v(0, 1, 0)}]
    cands = [{"keyword": "metal roof coating", "vec": _v(0.95, 0.05, 0)}]  # ~metal
    out = place_topics(pillars, cands, threshold=0.72)
    assert out["add_to_existing"] == [
        {"pillar_slug": "metal-roofing", "pillar_keyword": "metal roofing",
         "clusters": ["metal roof coating"]}]
    assert out["new_pillars"] == []


def test_distant_candidate_seeds_a_new_pillar():
    pillars = [{"slug": "metal-roofing", "keyword": "metal roofing", "vec": _v(1, 0, 0)}]
    cands = [{"keyword": "gutter cleaning", "vec": _v(0, 0, 1)}]  # unrelated
    out = place_topics(pillars, cands, threshold=0.72)
    assert out["add_to_existing"] == []
    assert out["new_pillars"] == [{"pillar": "gutter cleaning", "clusters": []}]


def test_new_pillar_absorbs_its_near_neighbors_as_clusters():
    pillars = [{"slug": "metal-roofing", "keyword": "metal roofing", "vec": _v(1, 0, 0)}]
    # three mutually-close unrelated-to-metal seeds -> one new pillar + 2 clusters
    cands = [
        {"keyword": "gutter cleaning", "vec": _v(0, 0.1, 1)},
        {"keyword": "gutter guards", "vec": _v(0, 0.05, 1)},
        {"keyword": "downspout repair", "vec": _v(0, 0.12, 0.99)},
    ]
    out = place_topics(pillars, cands, threshold=0.72)
    assert out["add_to_existing"] == []
    assert len(out["new_pillars"]) == 1
    grp = out["new_pillars"][0]
    assert len({grp["pillar"], *grp["clusters"]}) == 3  # all three placed, no dup


def test_pillar_cap_pushes_overflow_to_a_new_pillar():
    pillars = [{"slug": "roofing", "keyword": "roofing", "vec": _v(1, 0, 0),
                "existing_clusters": 1}]
    cands = [{"keyword": f"roofing topic {i}", "vec": _v(1, 0.01 * i, 0)} for i in range(3)]
    out = place_topics(pillars, cands, threshold=0.72, max_clusters_per_pillar=2)
    # cap=2, one already loaded -> only 1 more joins; the other two seed a new pillar
    joined = sum(len(e["clusters"]) for e in out["add_to_existing"])
    assert joined == 1
    assert sum(1 + len(p["clusters"]) for p in out["new_pillars"]) == 2


def test_cosine_basic():
    assert cosine(_v(1, 0), _v(1, 0)) == 1.0
    assert abs(cosine(_v(1, 0), _v(0, 1))) < 1e-9
    assert cosine(_v(0, 0), _v(1, 1)) == 0.0  # zero vector guard
