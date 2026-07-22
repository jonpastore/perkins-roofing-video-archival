"""Tests for core/article_plan.py — 100% coverage target."""

from __future__ import annotations

import pytest

from core.article_plan import _capitalize, _cluster_score, _slugify, _topic_match, build_plan

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _kw(keyword: str, intent: str = "informational", topic: str = "roofing") -> dict:
    return {"keyword": keyword, "intent": intent, "topic": topic, "difficulty": "medium"}


def _serp_with_paa(paa_count: int = 3, template: str = "educational") -> dict:
    """Build a minimal SERP fixture."""
    return {
        "organic": [
            {"title": f"Result {i}", "link": f"https://example.com/{i}", "snippet": ""}
            for i in range(5)
        ],
        "peopleAlsoAsk": [{"question": f"Q{i}?"} for i in range(paa_count)],
        "answerBox": None,
        "knowledgeGraph": None,
        "relatedSearches": [],
    }


# Canned keywords — always ≥4 informational candidates
KEYWORDS = [
    _kw("roofing guide complete", intent="informational", topic="roofing"),
    _kw("roof leak repair tips", intent="informational", topic="roofing"),
    _kw("how to fix roof shingles", intent="informational", topic="roofing"),
    _kw("roof replacement cost", intent="commercial", topic="roofing"),
    _kw("emergency roof repair", intent="informational", topic="roofing"),
    _kw("metal roof vs asphalt", intent="commercial", topic="roofing"),
]

# SERP data keyed by keyword string
SERPS = {
    "roofing guide complete": _serp_with_paa(paa_count=8, template="educational"),
    "roof leak repair tips": _serp_with_paa(paa_count=5, template="faq"),
    "how to fix roof shingles": _serp_with_paa(paa_count=3, template="how_to"),
    "roof replacement cost": _serp_with_paa(paa_count=2, template="service_page"),
    "emergency roof repair": _serp_with_paa(paa_count=4, template="faq"),
    "metal roof vs asphalt": _serp_with_paa(paa_count=1, template="comparison"),
}


# ---------------------------------------------------------------------------
# build_plan — happy path
# ---------------------------------------------------------------------------

class TestBuildPlanHappyPath:
    def test_returns_required_keys(self):
        plan = build_plan(KEYWORDS, SERPS)
        assert "topic" in plan
        assert "pillar" in plan
        assert "clusters" in plan
        assert "internal_link_map" in plan

    def test_pillar_has_required_fields(self):
        plan = build_plan(KEYWORDS, SERPS)
        pillar = plan["pillar"]
        for field in ("keyword", "title", "slug", "intent", "angle", "outline", "target_words"):
            assert field in pillar, f"Missing pillar field: {field}"

    def test_clusters_each_have_required_fields(self):
        plan = build_plan(KEYWORDS, SERPS)
        for cluster in plan["clusters"]:
            for field in ("keyword", "title", "slug", "intent", "angle", "outline", "target_words"):
                assert field in cluster, f"Missing cluster field: {field}"

    def test_pillar_is_highest_paa_density(self):
        # "roofing guide complete" has paa_count=8, the highest
        plan = build_plan(KEYWORDS, SERPS)
        assert plan["pillar"]["keyword"] == "roofing guide complete"

    def test_internal_link_map_maps_clusters_to_pillar(self):
        plan = build_plan(KEYWORDS, SERPS)
        pillar_slug = plan["pillar"]["slug"]
        for cluster in plan["clusters"]:
            slug = cluster["slug"]
            assert plan["internal_link_map"][slug] == pillar_slug

    def test_pillar_not_in_clusters(self):
        plan = build_plan(KEYWORDS, SERPS)
        pillar_kw = plan["pillar"]["keyword"]
        cluster_kws = [c["keyword"] for c in plan["clusters"]]
        assert pillar_kw not in cluster_kws

    def test_pillar_target_words_is_1500(self):
        plan = build_plan(KEYWORDS, SERPS)
        assert plan["pillar"]["target_words"] == 1500

    def test_cluster_target_words_is_1000(self):
        plan = build_plan(KEYWORDS, SERPS)
        for cluster in plan["clusters"]:
            assert cluster["target_words"] == 1000

    def test_pillar_slug_is_kebab_case(self):
        plan = build_plan(KEYWORDS, SERPS)
        slug = plan["pillar"]["slug"]
        assert slug == slug.lower()
        assert " " not in slug

    def test_cluster_slugs_unique(self):
        plan = build_plan(KEYWORDS, SERPS)
        slugs = [c["slug"] for c in plan["clusters"]]
        assert len(slugs) == len(set(slugs))

    def test_clusters_capped_at_12(self):
        # Provide 15 informational keywords — plan must not return >12 clusters
        kws = [_kw(f"roofing topic keyword number {i}", intent="informational") for i in range(16)]
        # First keyword gets most PAA (8) → pillar; rest get 0
        serps_large = {kws[0]["keyword"]: _serp_with_paa(paa_count=8)}
        plan = build_plan(kws, serps_large)
        assert len(plan["clusters"]) <= 12

    def test_pillar_angle_mentions_pillar(self):
        plan = build_plan(KEYWORDS, SERPS)
        assert "PILLAR" in plan["pillar"]["angle"]

    def test_cluster_angle_mentions_cluster(self):
        plan = build_plan(KEYWORDS, SERPS)
        for cluster in plan["clusters"]:
            assert "CLUSTER" in cluster["angle"]

    def test_topic_inferred_from_keywords(self):
        plan = build_plan(KEYWORDS, SERPS)
        # All keywords have topic="roofing"
        assert plan["topic"] == "roofing"

    def test_pillar_outline_is_list_of_strings(self):
        plan = build_plan(KEYWORDS, SERPS)
        outline = plan["pillar"]["outline"]
        assert isinstance(outline, list)
        assert all(isinstance(s, str) for s in outline)

    def test_cluster_outline_is_list_of_strings(self):
        plan = build_plan(KEYWORDS, SERPS)
        for cluster in plan["clusters"]:
            assert isinstance(cluster["outline"], list)


# ---------------------------------------------------------------------------
# build_plan — topic inference
# ---------------------------------------------------------------------------

class TestBuildPlanTopicInference:
    def test_topic_from_most_common_topic_field(self):
        kws = [
            _kw("metal roofing benefits", topic="metal roofing"),
            _kw("metal roof installation", topic="metal roofing"),
            _kw("metal roof cost", intent="commercial", topic="metal roofing"),
            _kw("metal roof vs shingles", intent="commercial", topic="metal roofing"),
        ]
        plan = build_plan(kws, {})
        assert plan["topic"] == "metal roofing"

    def test_topic_fallback_when_no_topic_field(self):
        kws = [
            {"keyword": "skylight installation", "intent": "informational", "difficulty": "easy"},
            {"keyword": "skylight cost", "intent": "commercial", "difficulty": "medium"},
            {"keyword": "skylight repair tips", "intent": "informational", "difficulty": "easy"},
            {"keyword": "velux skylight review", "intent": "commercial", "difficulty": "medium"},
        ]
        plan = build_plan(kws, {})
        # Should not crash; topic defaults to first keyword
        assert plan["topic"] == "skylight installation"


# ---------------------------------------------------------------------------
# build_plan — error conditions
# ---------------------------------------------------------------------------

class TestBuildPlanErrors:
    def test_raises_when_fewer_than_4_candidates(self):
        kws = [
            _kw("roof repair", intent="informational"),
            _kw("roof install", intent="informational"),
            _kw("buy shingles", intent="transactional"),  # excluded from candidates
        ]
        with pytest.raises(ValueError, match="Insufficient keyword candidates"):
            build_plan(kws, {})

    def test_raises_with_only_transactional_keywords(self):
        kws = [
            _kw("buy roofing materials", intent="transactional"),
            _kw("order shingles online", intent="transactional"),
            _kw("purchase roof tiles", intent="transactional"),
            _kw("get roofing quote", intent="transactional"),
        ]
        with pytest.raises(ValueError):
            build_plan(kws, {})

    def test_raises_with_empty_keywords(self):
        with pytest.raises((ValueError, IndexError)):
            build_plan([], {})


# ---------------------------------------------------------------------------
# build_plan — missing / empty SERP data
# ---------------------------------------------------------------------------

class TestBuildPlanMissingSerps:
    def test_works_with_empty_serps_dict(self):
        # When no SERP data available, paa_count=0 for all keywords,
        # tie broken by keyword length
        kws = [
            _kw("roofing guide comprehensive overview", intent="informational"),
            _kw("roof leak repair", intent="informational"),
            _kw("roof shingle fix", intent="informational"),
            _kw("metal roofing cost", intent="commercial"),
        ]
        plan = build_plan(kws, {})
        assert "pillar" in plan
        assert len(plan["clusters"]) >= 3

    def test_pillar_selected_by_keyword_length_when_paa_tied(self):
        # With empty serps, all paa_count=0 — tie-break is keyword length
        kws = [
            _kw("roofing a very long keyword string here", intent="informational"),
            _kw("short roof", intent="informational"),
            _kw("medium roof repair", intent="informational"),
            _kw("roof cost estimate", intent="commercial"),
        ]
        plan = build_plan(kws, {})
        # Longest keyword should win the pillar slot
        assert plan["pillar"]["keyword"] == "roofing a very long keyword string here"


# ---------------------------------------------------------------------------
# build_plan — slug deduplication
# ---------------------------------------------------------------------------

class TestBuildPlanSlugDedup:
    def test_duplicate_slugs_get_numeric_suffix(self):
        # Two keywords that would slugify to the same string
        kws = [
            _kw("roof-repair", intent="informational"),
            _kw("roof repair", intent="informational"),   # same slug after slugify
            _kw("how to fix a roof", intent="informational"),
            _kw("roof replacement guide", intent="commercial"),
            _kw("metal roofing options", intent="informational"),
        ]
        plan = build_plan(kws, {})
        slugs = [plan["pillar"]["slug"]] + [c["slug"] for c in plan["clusters"]]
        assert len(slugs) == len(set(slugs)), "Duplicate slugs found"

    def test_triple_collision_uses_while_loop(self):
        """Cover the inner while loop (line 197): -2 suffix is also taken, so -3 is assigned."""
        # Three keywords all slugify to "roof-repair"
        kws = [
            _kw("roof repair", intent="informational"),      # pillar candidate
            _kw("roof-repair", intent="informational"),      # cluster → slug=roof-repair → taken → -2
            _kw("roof  repair", intent="informational"),     # cluster → slug=roof-repair → -2 taken → -3
            _kw("roof replacement cost", intent="commercial"),
            _kw("emergency roof service", intent="informational"),
        ]
        plan = build_plan(kws, {})
        slugs = [plan["pillar"]["slug"]] + [c["slug"] for c in plan["clusters"]]
        assert len(slugs) == len(set(slugs)), "Duplicate slugs found in triple-collision case"


# ---------------------------------------------------------------------------
# build_plan — cluster template scoring
# ---------------------------------------------------------------------------

class TestBuildPlanClusterTemplates:
    def test_how_to_template_angle_in_cluster(self):
        """Cover the elif tmpl == 'how_to' branch (line 207)."""
        kws = [
            _kw("roofing overview complete guide", intent="informational"),  # pillar (most PAA)
            _kw("how to fix roof shingles step by step", intent="informational"),
            _kw("roof repair basics intro", intent="informational"),
            _kw("roof cost estimate info", intent="commercial"),
        ]
        how_to_serp = {
            "organic": [
                {"title": "How to fix roof", "link": "https://wikihow.com/fix", "snippet": ""}
            ] * 5,
            "peopleAlsoAsk": [{"question": f"Q{i}?"} for i in range(2)],
            "answerBox": {"answer": "Use roofing cement.", "link": "https://x.com"},
            "knowledgeGraph": None,
            "relatedSearches": [],
        }
        serps_ht = {
            "roofing overview complete guide": _serp_with_paa(paa_count=8),
            "how to fix roof shingles step by step": how_to_serp,
        }
        plan = build_plan(kws, serps_ht)
        cluster_kws = [c["keyword"] for c in plan["clusters"]]
        assert "how to fix roof shingles step by step" in cluster_kws
        cluster = next(c for c in plan["clusters"] if c["keyword"] == "how to fix roof shingles step by step")
        assert "Procedural guide" in cluster["angle"]

    def test_comparison_template_angle_in_cluster(self):
        """Cover the elif tmpl == 'comparison' branch (line 212)."""
        kws = [
            _kw("roofing overview complete guide", intent="informational"),  # pillar
            _kw("metal roof vs asphalt shingles comparison", intent="commercial"),
            _kw("roof material options info", intent="informational"),
            _kw("roof repair cost estimate", intent="commercial"),
        ]
        comparison_serp = {
            "organic": [
                {"title": "Metal vs Asphalt review", "link": "https://reviews.com/vs", "snippet": ""},
                {"title": "Asphalt versus Metal comparison", "link": "https://compare.com/vs", "snippet": ""},
                {"title": "Best 5 roofing comparison", "link": "https://best5.com", "snippet": ""},
                {"title": "Compare roofing brands", "link": "https://ratingsite.com", "snippet": ""},
                {"title": "Roofing versus guide", "link": "https://guide.com/vs", "snippet": ""},
                {"title": "Metal vs shingles review", "link": "https://review2.com", "snippet": ""},
                {"title": "Best roofing versus", "link": "https://best6.com", "snippet": ""},
                {"title": "Compare metal roofing", "link": "https://compare2.com", "snippet": ""},
                {"title": "Shingles vs metal roof", "link": "https://compare3.com", "snippet": ""},
                {"title": "Roofing comparison review", "link": "https://compare4.com", "snippet": ""},
            ],
            "peopleAlsoAsk": [{"question": "Q?"}],
            "answerBox": None,
            "knowledgeGraph": None,
            "relatedSearches": [],
        }
        serps_cmp = {
            "roofing overview complete guide": _serp_with_paa(paa_count=8),
            "metal roof vs asphalt shingles comparison": comparison_serp,
        }
        plan = build_plan(kws, serps_cmp)
        cluster_kws = [c["keyword"] for c in plan["clusters"]]
        assert "metal roof vs asphalt shingles comparison" in cluster_kws
        cluster = next(c for c in plan["clusters"] if c["keyword"] == "metal roof vs asphalt shingles comparison")
        assert "Comparison content" in cluster["angle"]

    def test_faq_template_preferred_as_cluster(self):
        # Keyword with faq template should appear before educational in clusters
        kws = [
            _kw("roofing overview", intent="informational"),  # will be pillar (most PAA)
            _kw("roof faq questions", intent="informational"),
            _kw("roof educational info", intent="informational"),
            _kw("roof comparison guide", intent="commercial"),
            _kw("how to roof a house", intent="informational"),
        ]
        faq_serp = {
            "organic": [{"title": "X", "link": "https://x.com", "snippet": ""}],
            "peopleAlsoAsk": [{"question": f"Q{i}?"} for i in range(6)],
            "answerBox": None,
            "knowledgeGraph": None,
            "relatedSearches": [],
        }
        # Override SERP for pillar candidate to have most PAA
        serps = {
            "roofing overview": _serp_with_paa(paa_count=9),
            "roof faq questions": faq_serp,
        }
        plan = build_plan(kws, serps)
        # Pillar is the one with most PAA (roofing overview, paa=9)
        assert plan["pillar"]["keyword"] == "roofing overview"
        # faq-templated keyword should appear in clusters
        cluster_kws = [c["keyword"] for c in plan["clusters"]]
        assert "roof faq questions" in cluster_kws


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

class TestSlugify:
    def test_basic_slug(self):
        assert _slugify("Roof Repair Dallas") == "roof-repair-dallas"

    def test_strips_special_chars(self):
        assert _slugify("What's the best roof?") == "whats-the-best-roof"

    def test_collapses_hyphens(self):
        assert _slugify("roof--repair") == "roof-repair"

    def test_trims_leading_trailing_hyphens(self):
        assert _slugify("-roof repair-") == "roof-repair"

    def test_truncates_at_80_chars(self):
        long = "a " * 50  # 100 chars
        result = _slugify(long)
        assert len(result) <= 80

    def test_empty_string(self):
        assert _slugify("") == ""


class TestCapitalize:
    def test_basic(self):
        assert _capitalize("roof repair dallas") == "Roof Repair Dallas"

    def test_already_capitalized(self):
        assert _capitalize("Roof Repair") == "Roof Repair"

    def test_single_word(self):
        assert _capitalize("roofing") == "Roofing"

    def test_empty(self):
        assert _capitalize("") == ""


class TestClusterScore:
    def test_faq_highest(self):
        assert _cluster_score("faq") > _cluster_score("educational")

    def test_how_to_above_comparison(self):
        assert _cluster_score("how_to") > _cluster_score("comparison")

    def test_service_page_lowest(self):
        assert _cluster_score("service_page") == 0

    def test_unknown_template_returns_1(self):
        assert _cluster_score("nonexistent") == 1


class TestTopicMatch:
    def test_keyword_contains_topic(self):
        assert _topic_match("roof repair guide", "roof", "") is True

    def test_kw_topic_field_contains_topic(self):
        assert _topic_match("random string", "roofing", "roofing materials") is True

    def test_no_match(self):
        assert _topic_match("plumbing guide", "roofing", "plumbing") is False

    def test_case_insensitive(self):
        assert _topic_match("ROOF REPAIR", "roof", "") is True
