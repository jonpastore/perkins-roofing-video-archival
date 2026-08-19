"""Genre taxonomy, coverage, SEO/AIO scoring, density — pure, no I/O."""
from __future__ import annotations

from types import SimpleNamespace

from core.topic_graph import (
    aio_boost,
    article_covered,
    build_article_graph,
    build_faq_graph,
    classify_label,
    color_for,
    coverage_from_articles,
    density_flag,
    diversity_weight,
    engagement_score,
    genre_catalog,
    herfindahl,
    opportunity,
    pick_next_label,
    shannon_evenness,
    slugify,
    video_genre,
)


def test_genre_catalog_and_video_genre():
    cats = genre_catalog()
    assert {c["id"] for c in cats} >= {"tile", "metal", "internal"}
    assert video_genre("Tile foam method")["id"] == "tile"
    assert video_genre("Business Leadership")["publishable"] is False


def test_slugify_collapses_punctuation():
    assert slugify("Snap-lock metal panels") == slugify("Snap Lock Metal Panels")


def test_classify_empty_falls_through_to_other():
    assert classify_label("")[0] == "other"
    assert classify_label("???")[0] == "other"


def test_coverage_from_article_objects_and_short_tuples():
    obj = SimpleNamespace(slug="a", pillar_slug="p", title="A Title", focus_keyword="kw")
    cov = coverage_from_articles([obj, ("only-slug",), (), ("x", "pillar-x", None, None)])
    assert "a" in cov["slugs"]
    assert "p" in cov["pillars"]
    assert "a title" in cov["titles"]
    assert "kw" in cov["keywords"]
    assert "only-slug" in cov["slugs"]
    assert "pillar-x" in cov["pillars"]


def test_herfindahl_empty_is_zero():
    assert herfindahl([]) == 0.0
    assert herfindahl([0, 0]) == 0.0


def test_build_skips_blank_topic_and_faq_labels():
    g = build_article_graph(
        [{"label": "  ", "video_id": "v", "duration": 1, "views": 1, "likes": 0, "comments": 0}],
        [],
    )
    assert g["totals"]["items"] == 0 or all(
        s["label"].strip() for gen in g["genres"] for s in gen["subjects"]
    )
    f = build_faq_graph(
        [{"question": "", "status": "mined", "video_id": "v", "has_answer": False,
          "views": 0, "likes": 0, "comments": 0, "duration": 0}],
        [{"question": "   ", "video_id": "v", "views": 0, "likes": 0, "comments": 0, "duration": 0}],
    )
    assert f["kind"] == "faqs"


def test_pick_next_label_skips_internal_covered_and_blank():
    cov = {"slugs": {"tile-foam-method"}, "pillars": set(), "titles": set(), "keywords": set()}
    picked = pick_next_label(
        [
            {"label": "", "total_seconds": 999, "views": 0, "likes": 0, "comments": 0},
            {"label": "Business Leadership", "total_seconds": 9000, "views": 0, "likes": 0, "comments": 0},
            {"label": "Tile foam method", "total_seconds": 500, "views": 0, "likes": 0, "comments": 0},
            {"label": "Gooseneck vents", "total_seconds": 80, "views": 10, "likes": 2, "comments": 1},
        ],
        cov,
        {"vents": 0},
    )
    assert picked is not None
    assert picked["label"] == "Gooseneck vents"
    assert pick_next_label([], cov) is None


def test_classify_internal_before_materials():
    assert classify_label("Business Leadership")[0] == "internal"
    assert classify_label("Roofing franchise opportunities")[0] == "internal"
    assert classify_label("Work in Progress Accounting")[0] == "internal"


def test_classify_windows_and_tile_and_code():
    assert classify_label("Impact windows and doors")[0] == "windows"
    assert classify_label("Tile foam method Miami-Dade")[0] == "tile"
    assert classify_label("HVHZ roofing codes")[0] == "code"
    assert classify_label("Standing seam metal roofing")[0] == "metal"
    assert classify_label("60-mil TPO flat roofs")[0] == "flat"
    assert classify_label("Hurricane prep for tile roofs")[0] == "weather"


def test_comparisons_win_over_material_when_vs_present():
    assert classify_label("Shingle vs Tile vs Metal")[0] == "comparisons"


def test_article_covered_by_keyword_even_when_slug_differs():
    cov = {
        "slugs": {"impact-windows-and-doors-florida-guide"},
        "pillars": set(),
        "titles": {"impact windows and doors: essential guide for florida homeowners"},
        "keywords": {"impact windows and doors"},
    }
    assert article_covered("Impact windows and doors", cov) is True
    assert article_covered("Gooseneck vents", cov) is False


def test_article_covered_by_slugify_of_label_matching_slug():
    cov = {
        "slugs": {"tile-underlayment"},
        "pillars": set(),
        "titles": set(),
        "keywords": set(),
    }
    assert article_covered("Tile underlayment", cov) is True


def test_article_covered_by_pillar_slug():
    cov = {
        "slugs": {"some-cluster"},
        "pillars": {"metal-roofing"},
        "titles": set(),
        "keywords": set(),
    }
    assert article_covered("Metal roofing", cov) is True


def test_engagement_prefers_comments_over_raw_views():
    viral_dead = engagement_score(views=958_114, likes=18, comments=0)
    how_to = engagement_score(views=157_096, likes=1566, comments=337)
    assert how_to > viral_dead


def test_uniqueness_zeroes_opportunity_when_covered():
    assert opportunity(demand=10, grounding=10, uniqueness=0, aio=1, diversity=1) == 0
    assert opportunity(demand=10, grounding=10, uniqueness=1, aio=1, diversity=1) > 0


def test_diversity_weight_penalizes_already_heavy_genres():
    assert diversity_weight(0) > diversity_weight(40)
    assert diversity_weight(1) > diversity_weight(8)


def test_aio_boost_named_entities_and_codes():
    assert aio_boost("Polyglass TU+ underlayment") > aio_boost("Roofing")
    assert aio_boost("HVHZ Miami-Dade tile foam") > 0
    assert aio_boost("roof") == 0


def test_shannon_evenness_is_1_when_equal_and_0_when_one_genre():
    assert shannon_evenness([10, 10, 10, 10]) == 1.0
    assert shannon_evenness([40, 0, 0, 0]) == 0.0
    assert shannon_evenness([]) == 1.0


def test_herfindahl_is_1_when_concentrated():
    assert herfindahl([40, 0, 0]) == 1.0
    assert 0.2 < herfindahl([10, 10, 10, 10]) < 0.3


def test_density_flag_over_and_under():
    assert density_flag("internal", n_published=8, published_share=0.5, subject_share=0.1) == "internal"
    assert density_flag("tile", n_published=0, published_share=0, subject_share=0.2) == "empty"
    assert density_flag("tile", n_published=40, published_share=0.4, subject_share=0.15) == "over_served"
    assert density_flag("weather", n_published=1, published_share=0.02, subject_share=0.12) == "under_served"
    assert density_flag("metal", n_published=10, published_share=0.12, subject_share=0.14) == "balanced"


def test_color_matches_the_legend():
    assert color_for("internal", n_published=2, yt_heat=10, grounding=100) == "amber"
    assert color_for("tile", n_published=0, yt_heat=50, grounding=10) == "green"
    assert color_for("weather", n_published=0, yt_heat=0, grounding=0) == "red"
    assert color_for("metal", n_published=12, yt_heat=10, grounding=10) == "navy"


def test_build_article_graph_groups_and_filters_published():
    topics = [
        {"label": "Tile foam method", "video_id": "v1", "duration": 100.0,
         "views": 1000, "likes": 10, "comments": 5},
        {"label": "Tile foam method", "video_id": "v2", "duration": 50.0,
         "views": 200, "likes": 2, "comments": 1},
        {"label": "Hurricane shutters", "video_id": "v3", "duration": 20.0,
         "views": 0, "likes": 0, "comments": 0},
        {"label": "Business Leadership", "video_id": "v4", "duration": 900.0,
         "views": 5, "likes": 0, "comments": 0},
    ]
    articles = [
        {"slug": "tile-foam-method", "title": "Tile Foam Method", "status": "published",
         "role": "pillar", "focus_keyword": "tile foam method", "pillar_slug": None},
    ]
    g = build_article_graph(topics, articles, published="all")
    ids = {x["id"] for x in g["genres"]}
    assert "tile" in ids
    assert "weather" in ids
    assert "internal" in ids
    tile = next(x for x in g["genres"] if x["id"] == "tile")
    assert tile["n_published"] >= 1
    assert tile["covered_subjects"] >= 1
    weather = next(x for x in g["genres"] if x["id"] == "weather")
    assert weather["n_published"] == 0
    assert g["diversity"]["flags"]
    pub_only = build_article_graph(topics, articles, published="yes")
    pub_ids = {x["id"] for x in pub_only["genres"] if x["n_published"] or x["n_unpublished"]}
    assert "tile" in pub_ids


def test_unpublished_filter_hides_covered_leaves():
    topics = [
        {"label": "Tile foam method", "video_id": "v1", "duration": 10.0,
         "views": 1, "likes": 0, "comments": 0},
        {"label": "Gooseneck vents", "video_id": "v2", "duration": 10.0,
         "views": 1, "likes": 0, "comments": 0},
    ]
    articles = [
        {"slug": "tile-foam-method", "title": "Tile Foam", "status": "published",
         "role": "pillar", "focus_keyword": "tile foam method", "pillar_slug": None},
    ]
    g = build_article_graph(topics, articles, published="no")
    tile = next((x for x in g["genres"] if x["id"] == "tile"), None)
    # covered subject dropped from unpublished view
    if tile:
        assert tile["n_published"] == 0
    vents = next(x for x in g["genres"] if x["id"] == "vents")
    assert vents["n_unpublished"] >= 1


def test_faq_graph_splits_answered_vs_unmined():
    faqs = [
        {"question": "How do I walk on a tile roof?", "status": "answered",
         "video_id": "v1", "has_answer": True, "views": 100, "likes": 4, "comments": 2,
         "duration": 60.0},
        {"question": "What is HVHZ?", "status": "mined",
         "video_id": "v2", "has_answer": False, "views": 10, "likes": 0, "comments": 0,
         "duration": 20.0},
    ]
    unmined = [
        {"question": "Does metal rust in salt air?", "video_id": "v3",
         "views": 50, "likes": 1, "comments": 1, "duration": 30.0},
    ]
    g = build_faq_graph(faqs, unmined, published="all")
    tile = next(x for x in g["genres"] if x["id"] == "tile")
    assert tile["n_published"] >= 1
    weather = next(x for x in g["genres"] if x["id"] == "weather")
    assert weather["n_unpublished"] >= 1
    code = next(x for x in g["genres"] if x["id"] == "code")
    assert code["n_unpublished"] >= 1
