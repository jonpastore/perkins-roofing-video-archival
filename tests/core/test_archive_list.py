"""Unit tests for core.archive_list."""
import time

from core.archive_list import (
    TtlCache,
    article_counts_for,
    article_refers_to_video,
    filter_key,
    keep_generated,
    list_cache_key,
    page_slice,
)


def test_article_counts_empty_ids():
    assert article_counts_for([], [(["a"], "a")]) == {}


def test_article_counts_prefers_source_video_ids():
    articles = [
        (["vid_a", "vid_b"], "mentions vid_c only in markdown"),
        (["vid_a"], None),
        (["vid_a", "vid_a"], None),
    ]
    counts = article_counts_for(["vid_a", "vid_b", "vid_c"], articles)
    assert counts == {"vid_a": 3, "vid_b": 1, "vid_c": 0}


def test_article_counts_falls_back_to_content_when_source_missing():
    articles = [
        (None, "This article references vid_art in the text."),
        ([], "empty list falls back: vid_art"),
        (None, None),
        ("vid_solo", "title-as-string"),
    ]
    counts = article_counts_for(["vid_art", "vid_solo", "other"], articles)
    assert counts["vid_art"] == 2
    assert counts["vid_solo"] == 1
    assert counts["other"] == 0


def test_article_refers_to_video_matches_counts():
    assert article_refers_to_video(["vid_a"], "mentions vid_b", "vid_a") is True
    assert article_refers_to_video(["vid_a"], "mentions vid_b", "vid_b") is False
    assert article_refers_to_video(None, "mentions vid_b", "vid_b") is True
    assert article_refers_to_video([], "mentions vid_b", "vid_b") is True


def test_article_counts_ignores_unusable_source_type():
    articles = [
        (123, "mentions vid_x"),
        ({"id": "vid_x"}, "mentions vid_x"),
    ]
    counts = article_counts_for(["vid_x"], articles)
    assert counts == {"vid_x": 2}


def test_keep_generated_tri_state():
    assert keep_generated("all", True) is True
    assert keep_generated("all", False) is True
    assert keep_generated("yes", True) is True
    assert keep_generated("yes", False) is False
    assert keep_generated("no", True) is False
    assert keep_generated("no", False) is True


def test_page_slice_none_limit_is_the_rest():
    items = [1, 2, 3, 4]
    page, total = page_slice(items, None, 1)
    assert page == [2, 3, 4]
    assert total == 4


def test_page_slice_clamps_negative_and_zero():
    items = [1, 2, 3]
    page, total = page_slice(items, 2, -5)
    assert page == [1, 2]
    assert total == 3
    empty, total2 = page_slice(items, 0, 0)
    assert empty == []
    assert total2 == 3
    past, _ = page_slice(items, 10, 99)
    assert past == []


def test_ttl_cache_hit_miss_expire_clear():
    cache = TtlCache(ttl_seconds=0.05)
    assert cache.get("k") is None
    cache.set("k", [1, 2])
    assert cache.get("k") == [1, 2]
    cache.set("n", 7)
    assert cache.get("n") == 7
    time.sleep(0.07)
    assert cache.get("k") is None
    cache.set("k", "x")
    cache.clear()
    assert cache.get("k") is None


def test_filter_key_is_stable():
    a = filter_key({"q": "roof", "clips": "all"})
    b = filter_key({"clips": "all", "q": "roof"})
    assert a == b
    assert a != filter_key({"q": "gutter", "clips": "all"})


def test_list_cache_key_is_tenant_scoped():
    parts = {"q": "", "clips": "all"}
    assert list_cache_key(1, parts) != list_cache_key(2, parts)
    assert list_cache_key(1, parts) != list_cache_key(None, parts)


def test_ttl_cache_get_returns_a_list_copy():
    cache = TtlCache(ttl_seconds=30)
    original = [{"id": "a"}]
    cache.set("k", original)
    got = cache.get("k")
    got.append({"id": "mutated"})
    assert cache.get("k") == original
