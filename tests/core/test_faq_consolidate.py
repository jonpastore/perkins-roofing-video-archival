from core.faq_consolidate import greedy_cluster, choose_canonical, links_in, merge_citations


def test_greedy_cluster_groups_similar():
    sim = [[1.0, 0.95, 0.1], [0.95, 1.0, 0.2], [0.1, 0.2, 1.0]]
    cl = greedy_cluster(sim, 0.9)
    assert sorted(map(sorted, cl)) == [[0, 1], [2]]


def test_greedy_cluster_all_distinct():
    sim = [[1.0, 0.1], [0.1, 1.0]]
    assert greedy_cluster(sim, 0.9) == [[0], [1]]


def test_choose_canonical_prefers_answered_then_longest():
    g = [
        {"question": "short?", "answer": "", "status": "mined"},
        {"question": "a bit longer question here?", "answer": "A full grounded answer.", "status": "answered"},
        {"question": "mid length question?", "answer": "", "status": "mined"},
    ]
    assert choose_canonical(g) == 1


def test_links_in_and_merge_citations():
    ans = "Yes [1].\n\nSources: [link 1](https://youtu.be/a?t=1)"
    assert links_in(ans) == ["https://youtu.be/a?t=1"]
    merged = merge_citations(ans, ["https://youtu.be/a?t=1", "https://youtu.be/b?t=2"])
    assert "link 2" in merged and "youtu.be/b?t=2" in merged
    assert merged.count("youtu.be/a?t=1") == 1  # existing not duplicated


def test_merge_citations_noop_when_nothing_new():
    ans = "X [1].\n\nSources: [link 1](https://youtu.be/a?t=1)"
    assert merge_citations(ans, ["https://youtu.be/a?t=1"]) == ans


def test_merge_citations_adds_sources_line_when_absent():
    assert "Sources:" in merge_citations("Plain answer.", ["https://youtu.be/x?t=0"])
