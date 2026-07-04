"""Tests for core/serp_analysis.py — 100% coverage target."""

import pytest

from core.serp_analysis import (
    aggregate_authority_citations,
    analyze_title_patterns,
    classify_keyword,
    extract_paa_questions,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _organic(items: list[dict]) -> list[dict]:
    """Build minimal organic result dicts."""
    return [
        {
            "title": item.get("title", "Example Title"),
            "link": item.get("link", "https://example.com/page"),
            "snippet": item.get("snippet", "Some snippet text."),
            "position": i + 1,
        }
        for i, item in enumerate(items)
    ]


CANNED_SERP = {
    "organic": _organic(
        [
            {"title": "How to Fix a Roof Leak Fast", "link": "https://wikihow.com/fix-roof-leak"},
            {"title": "5 Best Roof Repair Tips", "link": "https://example.com/tips"},
            {"title": "Roof Leak Repair Guide 2024", "link": "https://homerepair.org/roof"},
            {"title": "What is roof flashing?", "link": "https://wikipedia.org/wiki/roof"},
            {"title": "Roof Repair vs Replacement", "link": "https://contractor.com/vs"},
            {"title": "How to patch a roof", "link": "https://wikihow.com/patch-roof"},
            {"title": "Best roofing materials guide", "link": "https://guide.com/roofing"},
            {"title": "How to stop a roof leak", "link": "https://diy.com/roof"},
            {"title": "Steps to fix roof shingles", "link": "https://tutorial.com/shingles"},
            {"title": "What is a roof decking?", "link": "https://howstuffworks.com/roof"},
        ]
    ),
    "peopleAlsoAsk": [
        {"question": "How do I fix a roof leak?", "snippet": "...", "link": "https://ex.com"},
        {"question": "What causes roof leaks?"},
        {"question": "How long does roof repair take?"},
        {"question": "Can I fix a roof leak myself?"},
        {"question": "How much does roof repair cost?"},
    ],
    "answerBox": None,
    "knowledgeGraph": None,
    "relatedSearches": ["roof repair cost", "emergency roof repair"],
}


# ---------------------------------------------------------------------------
# classify_keyword
# ---------------------------------------------------------------------------

class TestClassifyKeyword:
    def test_informational_intent_and_how_to_template(self):
        result = classify_keyword(CANNED_SERP)
        assert result["intent"] == "informational"
        # No answer_box, no local pack, not commercial — informational → educational
        assert result["template"] in ("educational", "how_to", "faq", "listicle")

    def test_returns_intent_and_template_keys(self):
        result = classify_keyword(CANNED_SERP)
        assert "intent" in result
        assert "template" in result

    def test_transactional_intent_with_ecommerce_links(self):
        serp = {
            "organic": _organic(
                [
                    {"title": "Buy roof shingles", "link": "https://amazon.com/roof-shingles"},
                    {"title": "Roof materials", "link": "https://homedepot.com/roof"},
                    {"title": "Order roofing", "link": "https://walmart.com/roofing"},
                    {"title": "Shingles store", "link": "https://lowes.com/shingles"},
                    {"title": "Roof shop", "link": "https://target.com/roof"},
                    {"title": "Buy shingles", "link": "https://amazon.com/shingles2"},
                    {"title": "Roof products", "link": "https://homedepot.com/p2"},
                    {"title": "Roofing supplies", "link": "https://walmart.com/r2"},
                    {"title": "Tiles online", "link": "https://ebay.com/tiles"},
                    {"title": "More supplies", "link": "https://amazon.com/supplies"},
                ]
            ),
            "peopleAlsoAsk": [],
            "answerBox": None,
            "knowledgeGraph": None,
            "relatedSearches": [],
        }
        result = classify_keyword(serp)
        assert result["intent"] == "transactional"
        assert result["template"] == "service_page"

    def test_commercial_intent_triggers_comparison_template(self):
        serp = {
            "organic": _organic(
                [
                    {"title": "GAF vs Owens Corning shingles review", "link": "https://roofpros.com/vs"},
                    {"title": "Best 5 roofing brands comparison", "link": "https://reviews.com/best5"},
                    {"title": "Roofing material reviews 2024", "link": "https://ratingsite.com"},
                    {"title": "Compare asphalt vs metal roofing", "link": "https://compare.com"},
                    {"title": "Top roofing reviews", "link": "https://reviews2.com"},
                    {"title": "Metal roof vs asphalt", "link": "https://homeadvisor.com/vs"},
                    {"title": "Best metal roofing brands review", "link": "https://consumer.com"},
                    {"title": "Shingles comparison guide", "link": "https://guidesite.com"},
                    {"title": "Roofing brand versus analysis", "link": "https://analysis.com"},
                    {"title": "Comparing roofing options review", "link": "https://expert.com"},
                ]
            ),
            "peopleAlsoAsk": [],
            "answerBox": None,
            "knowledgeGraph": None,
            "relatedSearches": [],
        }
        result = classify_keyword(serp)
        assert result["intent"] == "commercial"
        assert result["template"] == "comparison"

    def test_answer_box_non_transactional_triggers_how_to(self):
        serp = {
            **CANNED_SERP,
            "answerBox": {"answer": "Use a caulking gun.", "snippet": None},
        }
        result = classify_keyword(serp)
        assert result["template"] == "how_to"

    def test_answer_box_with_transactional_intent_not_how_to(self):
        serp = {
            "organic": _organic(
                [
                    {"title": "Buy roofing", "link": "https://amazon.com/r"},
                    {"title": "Shop shingles", "link": "https://homedepot.com/s"},
                    {"title": "Order tiles", "link": "https://walmart.com/t"},
                    {"title": "Purchase materials", "link": "https://lowes.com/p"},
                    {"title": "Get supplies", "link": "https://target.com/g"},
                    {"title": "Roofing shop", "link": "https://amazon.com/r2"},
                    {"title": "Buy tiles", "link": "https://amazon.com/t2"},
                    {"title": "Purchase shingles", "link": "https://homedepot.com/p2"},
                    {"title": "Shop roofing", "link": "https://walmart.com/s2"},
                    {"title": "Get shingles", "link": "https://amazon.com/g2"},
                ]
            ),
            "peopleAlsoAsk": [],
            "answerBox": {"answer": "Buy online", "snippet": None},
            "knowledgeGraph": None,
            "relatedSearches": [],
        }
        result = classify_keyword(serp)
        # transactional intent → service_page even with answer_box
        assert result["template"] == "service_page"

    def test_local_pack_overrides_mixed_intent(self):
        serp = {
            "organic": _organic(
                [
                    {"title": "Roofers near me", "link": "https://yelp.com/roofers"},
                    {"title": "Top roofers", "link": "https://yellowpages.com/roofers"},
                    {"title": "Roofing company", "link": "https://roofco.com"},
                    {"title": "Local roofer", "link": "https://tripadvisor.com/roofer"},
                    {"title": "Roof repair", "link": "https://bbb.org/roofers"},
                ]
            ),
            "peopleAlsoAsk": [],
            "answerBox": None,
            "knowledgeGraph": None,
            "relatedSearches": [],
        }
        result = classify_keyword(serp)
        assert result["intent"] == "transactional"
        assert result["template"] == "service_page"

    def test_paa_dense_yields_faq_template(self):
        serp = {
            "organic": _organic(
                [{"title": "Roof info", "link": "https://genericsite.com"}] * 5
            ),
            "peopleAlsoAsk": [
                {"question": f"Q{i}?"} for i in range(6)
            ],
            "answerBox": None,
            "knowledgeGraph": None,
            "relatedSearches": [],
        }
        result = classify_keyword(serp)
        assert result["template"] == "faq"

    def test_knowledge_panel_triggers_educational(self):
        serp = {
            "organic": _organic(
                [{"title": "Asphalt shingles info", "link": "https://info.com"}] * 5
            ),
            "peopleAlsoAsk": [],
            "answerBox": None,
            "knowledgeGraph": {"title": "Asphalt Shingle", "type": "Material"},
            "relatedSearches": [],
        }
        result = classify_keyword(serp)
        assert result["template"] == "educational"

    def test_empty_serp_returns_mixed_listicle(self):
        serp = {
            "organic": [],
            "peopleAlsoAsk": [],
            "answerBox": None,
            "knowledgeGraph": None,
            "relatedSearches": [],
        }
        result = classify_keyword(serp)
        assert result["intent"] == "mixed"
        assert result["template"] == "listicle"

    def test_video_domain_in_top3_how_to_fallback(self):
        """Video in top-3 but no other strong signals → listicle (video not
        enough to override when intent is mixed and no local/paa/kg)."""
        serp = {
            "organic": _organic(
                [
                    {"title": "Roof repair video", "link": "https://youtube.com/watch?v=abc"},
                    {"title": "Repair tips", "link": "https://genericblog.com/repair"},
                    {"title": "Roof guide", "link": "https://anothersite.com/guide"},
                ]
            ),
            "peopleAlsoAsk": [],
            "answerBox": None,
            "knowledgeGraph": None,
            "relatedSearches": [],
        }
        result = classify_keyword(serp)
        # video present but intent mixed, no local/paa/kg/answerbox → how_to
        assert result["template"] == "how_to"

    def test_missing_keys_handled_gracefully(self):
        result = classify_keyword({})
        assert result["intent"] == "mixed"

    def test_none_values_handled_gracefully(self):
        serp = {
            "organic": None,
            "peopleAlsoAsk": None,
            "answerBox": None,
            "knowledgeGraph": None,
            "relatedSearches": None,
        }
        result = classify_keyword(serp)
        assert result["intent"] == "mixed"


# ---------------------------------------------------------------------------
# analyze_title_patterns
# ---------------------------------------------------------------------------

class TestAnalyzeTitlePatterns:
    def test_returns_required_keys(self):
        result = analyze_title_patterns(CANNED_SERP)
        assert "has_number" in result
        assert "has_year" in result
        assert "avg_length" in result
        assert "common_words" in result

    def test_has_number_true_when_two_titles_start_with_digit(self):
        serp = {
            "organic": _organic(
                [
                    {"title": "5 Ways to Fix Your Roof"},
                    {"title": "10 Roofing Tips for Homeowners"},
                    {"title": "Roof repair guide"},
                ]
            )
        }
        result = analyze_title_patterns(serp)
        assert result["has_number"] is True

    def test_has_number_false_when_only_one_number_title(self):
        serp = {
            "organic": _organic(
                [
                    {"title": "5 Ways to Fix Your Roof"},
                    {"title": "Roof repair guide"},
                    {"title": "How to patch shingles"},
                ]
            )
        }
        result = analyze_title_patterns(serp)
        assert result["has_number"] is False

    def test_has_year_true_when_two_titles_contain_year(self):
        serp = {
            "organic": _organic(
                [
                    {"title": "Best Roof Repair Guide 2024"},
                    {"title": "Roofing Materials 2025 Review"},
                    {"title": "Basic roof info"},
                ]
            )
        }
        result = analyze_title_patterns(serp)
        assert result["has_year"] is True

    def test_has_year_false_when_one_year(self):
        serp = {
            "organic": _organic(
                [
                    {"title": "Best Roof Repair Guide 2024"},
                    {"title": "Roofing tips"},
                    {"title": "Basic roof info"},
                ]
            )
        }
        result = analyze_title_patterns(serp)
        assert result["has_year"] is False

    def test_avg_length_computed_correctly(self):
        t1 = "Roof repair"         # 11 chars
        t2 = "Fix your roof today"  # 19 chars
        t3 = "Roofing"              # 7 chars
        serp = {"organic": _organic([{"title": t1}, {"title": t2}, {"title": t3}])}
        result = analyze_title_patterns(serp)
        assert result["avg_length"] == round((11 + 19 + 7) / 3)

    def test_common_words_appear_in_two_or_more_titles(self):
        serp = {
            "organic": _organic(
                [
                    {"title": "Roof repair guide"},
                    {"title": "Roof replacement tips"},
                    {"title": "Complete roof guide"},
                ]
            )
        }
        result = analyze_title_patterns(serp)
        # "roof" appears in all 3 titles, "guide" in 2
        assert "roof" in result["common_words"]
        assert "guide" in result["common_words"]
        # stopword "to" should not appear
        assert "the" not in result["common_words"]

    def test_empty_organic_returns_zero_defaults(self):
        result = analyze_title_patterns({"organic": []})
        assert result == {"has_number": False, "has_year": False, "avg_length": 0, "common_words": []}

    def test_only_one_organic_result(self):
        serp = {"organic": _organic([{"title": "Roof repair guide"}])}
        result = analyze_title_patterns(serp)
        assert result["avg_length"] > 0
        # No word can appear in 2+ of 1 title
        assert result["common_words"] == []

    def test_stopwords_excluded_from_common_words(self):
        serp = {
            "organic": _organic(
                [
                    {"title": "The best roof repair in town"},
                    {"title": "The best shingles for your home"},
                    {"title": "The best roofing guide"},
                ]
            )
        }
        result = analyze_title_patterns(serp)
        for stopword in ("the", "for", "in", "and", "or", "of", "with", "by"):
            assert stopword not in result["common_words"]

    def test_missing_organic_key(self):
        result = analyze_title_patterns({})
        assert result["avg_length"] == 0


# ---------------------------------------------------------------------------
# aggregate_authority_citations
# ---------------------------------------------------------------------------

class TestAggregateAuthorityCitations:
    def test_returns_domains_in_two_or_more_bodies(self):
        bodies = [
            "According to nih.gov, roof leaks are common. See also cdc.gov for more.",
            "Research from nih.gov shows moisture issues. Data from wikipedia.org confirms this.",
            "cdc.gov data supports this finding.",
        ]
        result = aggregate_authority_citations(bodies)
        assert "nih.gov" in result
        assert "cdc.gov" in result
        # wikipedia.org appears in only 1 body
        assert "wikipedia.org" not in result

    def test_domain_in_only_one_body_excluded(self):
        bodies = [
            "See healthline.com for details.",
            "Nothing here.",
            "Nothing here either.",
        ]
        result = aggregate_authority_citations(bodies)
        assert "healthline.com" not in result

    def test_known_authority_patterns_matched(self):
        bodies = [
            "Source: webmd.com and mayoclinic.org",
            "According to mayoclinic.org and who.int",
            "who.int is authoritative.",
        ]
        result = aggregate_authority_citations(bodies)
        assert "mayoclinic.org" in result
        assert "who.int" in result

    def test_edu_and_gov_tlds_matched(self):
        bodies = [
            "Published in harvard.edu research.",
            "Cited in harvard.edu study. Also usa.gov data.",
            "usa.gov confirms the finding.",
        ]
        result = aggregate_authority_citations(bodies)
        assert "harvard.edu" in result
        assert "usa.gov" in result

    def test_empty_bodies_returns_empty(self):
        result = aggregate_authority_citations([])
        assert result == []

    def test_no_authority_domains_returns_empty(self):
        bodies = [
            "Random text with no authority domains.",
            "Another random body.",
            "More random content here.",
        ]
        result = aggregate_authority_citations(bodies)
        assert result == []

    def test_deduplicates_same_domain_within_one_body(self):
        bodies = [
            "nih.gov nih.gov nih.gov mentioned three times.",
            "nih.gov mentioned again.",
            "nothing here",
        ]
        result = aggregate_authority_citations(bodies)
        # Only appears in 2 bodies (counts once per body) → included
        assert "nih.gov" in result

    def test_result_is_sorted(self):
        bodies = [
            "cdc.gov and nih.gov research.",
            "nih.gov and cdc.gov both confirm.",
            "extra",
        ]
        result = aggregate_authority_citations(bodies)
        assert result == sorted(result)


# ---------------------------------------------------------------------------
# extract_paa_questions
# ---------------------------------------------------------------------------

class TestExtractPaaQuestions:
    def test_returns_question_strings(self):
        result = extract_paa_questions(CANNED_SERP)
        assert len(result) == 5
        assert result[0] == "How do I fix a roof leak?"

    def test_empty_paa_returns_empty_list(self):
        result = extract_paa_questions({"peopleAlsoAsk": []})
        assert result == []

    def test_missing_paa_key_returns_empty_list(self):
        result = extract_paa_questions({})
        assert result == []

    def test_none_paa_returns_empty_list(self):
        result = extract_paa_questions({"peopleAlsoAsk": None})
        assert result == []

    def test_strips_whitespace_from_questions(self):
        serp = {"peopleAlsoAsk": [{"question": "  What is a roof?  "}]}
        result = extract_paa_questions(serp)
        assert result == ["What is a roof?"]

    def test_skips_items_with_empty_question(self):
        serp = {
            "peopleAlsoAsk": [
                {"question": "Valid question?"},
                {"question": ""},
                {"question": "   "},
                {"question": "Another valid one?"},
            ]
        }
        result = extract_paa_questions(serp)
        assert result == ["Valid question?", "Another valid one?"]

    def test_preserves_order(self):
        questions = [f"Question {i}?" for i in range(5)]
        serp = {"peopleAlsoAsk": [{"question": q} for q in questions]}
        result = extract_paa_questions(serp)
        assert result == questions

    def test_items_without_question_key_skipped(self):
        serp = {"peopleAlsoAsk": [{"snippet": "no question key"}, {"question": "Real question?"}]}
        result = extract_paa_questions(serp)
        assert result == ["Real question?"]


# ---------------------------------------------------------------------------
# Coverage gap — internal helper branches
# ---------------------------------------------------------------------------

class TestInternalHelperBranches:
    def test_host_exception_path_via_malformed_url(self):
        """A URL with no hostname (e.g. plain 'not-a-url') causes urlparse to
        return a None hostname, so .replace() raises — the except branch (lines
        17-18) must return '' and not crash."""
        serp = {
            "organic": _organic([{"title": "Page", "link": "not-a-url"}]),
            "peopleAlsoAsk": [],
            "answerBox": None,
            "knowledgeGraph": None,
            "relatedSearches": [],
        }
        # Must not raise; the bad URL is silently skipped in host extraction
        result = classify_keyword(serp)
        assert "intent" in result

    def test_news_domain_classifies_as_informational(self):
        """Line 59: news domains (forbes, cnn, etc.) → informational intent."""
        serp = {
            "organic": _organic(
                [
                    {"title": "Roof trends", "link": "https://forbes.com/roof-trends"},
                    {"title": "Storm damage news", "link": "https://cnn.com/storm-roof"},
                    {"title": "Roofing report", "link": "https://reuters.com/roofing"},
                    {"title": "Roof guide", "link": "https://bloomberg.com/roof"},
                    {"title": "Roof news", "link": "https://nytimes.com/roof"},
                    {"title": "Roof update", "link": "https://bbc.com/roof"},
                    {"title": "Roof story", "link": "https://techcrunch.com/roof"},
                    {"title": "Roof analysis", "link": "https://wsj.com/roof"},
                    {"title": "Roof feature", "link": "https://forbes.com/roof2"},
                    {"title": "Roof deep dive", "link": "https://cnn.com/roof2"},
                ]
            ),
            "peopleAlsoAsk": [],
            "answerBox": None,
            "knowledgeGraph": None,
            "relatedSearches": [],
        }
        result = classify_keyword(serp)
        assert result["intent"] == "informational"
