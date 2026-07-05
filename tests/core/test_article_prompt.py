"""Tests for core/article_prompt.py — 100% coverage target."""

from __future__ import annotations

import pytest

from core.article_prompt import system_prompt, template_prompt


# ---------------------------------------------------------------------------
# system_prompt
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    def test_returns_string(self):
        result = system_prompt()
        assert isinstance(result, str)

    def test_contains_eeat(self):
        result = system_prompt()
        assert "E-E-A-T" in result

    def test_contains_aeo(self):
        result = system_prompt()
        assert "AEO" in result

    def test_answer_first_format(self):
        result = system_prompt()
        assert "answer" in result.lower()
        assert "first" in result.lower()

    def test_no_ai_cliches_in_banned_list(self):
        result = system_prompt()
        # Check the banned word list is present
        assert "delve" in result
        assert "leverage" in result
        assert "seamless" in result

    def test_faq_section_requirement(self):
        result = system_prompt()
        assert "FAQ" in result

    def test_fact_density(self):
        result = system_prompt()
        assert "Fact density" in result or "fact density" in result.lower()

    def test_no_anthropic_specific_wording(self):
        result = system_prompt()
        # Port requirement: strip Anthropic-specific wording
        assert "Anthropic" not in result
        assert "Claude" not in result

    def test_publishing_context_present(self):
        result = system_prompt()
        assert "PUBLISHING CONTEXT" in result

    def test_short_paragraphs_requirement(self):
        result = system_prompt()
        assert "Short paragraphs" in result or "short paragraphs" in result.lower()

    def test_structured_lists_requirement(self):
        result = system_prompt()
        assert "Structured lists" in result or "structured lists" in result.lower()

    def test_idempotent(self):
        # Pure function — same output every call
        assert system_prompt() == system_prompt()


# ---------------------------------------------------------------------------
# template_prompt — minimal ctx
# ---------------------------------------------------------------------------

class TestTemplatePromptMinimal:
    def _minimal_ctx(self, **overrides) -> dict:
        base = {"keyword": "roof repair Dallas", "role": "standalone", "target_words": 1800}
        base.update(overrides)
        return base

    def test_returns_string(self):
        result = template_prompt(self._minimal_ctx())
        assert isinstance(result, str)

    def test_keyword_appears_in_prompt(self):
        result = template_prompt(self._minimal_ctx())
        assert "roof repair Dallas" in result

    def test_word_count_bounds_present(self):
        ctx = self._minimal_ctx(target_words=1800)
        result = template_prompt(ctx)
        lo = round(1800 * 0.9)
        hi = round(1800 * 1.1)
        assert str(lo) in result
        assert str(hi) in result

    def test_callout_boxes_section_present(self):
        result = template_prompt(self._minimal_ctx())
        assert "CALLOUT BOXES" in result
        # callouts are now emitted as clean HTML <aside>, not [!TIP] markdown admonitions
        assert "<aside" in result
        for cls in ('class="tip"', 'class="warning"', 'class="note"', 'class="key"'):
            assert cls in result

    def test_json_schema_present(self):
        result = template_prompt(self._minimal_ctx())
        assert '"title"' in result
        assert '"slug"' in result
        assert '"metaDescription"' in result
        assert '"faq"' in result

    def test_meta_description_char_limit_mentioned(self):
        result = template_prompt(self._minimal_ctx())
        assert "155" in result

    def test_no_internal_links_placeholder(self):
        result = template_prompt(self._minimal_ctx())
        assert "internalLinks can be an empty array" in result

    def test_default_template_is_educational(self):
        result = template_prompt(self._minimal_ctx())
        assert "EDUCATIONAL ARTICLE" in result

    def test_unknown_template_falls_back_to_educational(self):
        result = template_prompt(self._minimal_ctx(template="nonexistent-template"))
        assert "EDUCATIONAL ARTICLE" in result


# ---------------------------------------------------------------------------
# template_prompt — PAA injection
# ---------------------------------------------------------------------------

class TestTemplatePaaSection:
    def test_paa_questions_injected(self):
        ctx = {
            "keyword": "roof leak repair",
            "role": "standalone",
            "target_words": 1500,
            "paa": [
                "How do I find a roof leak?",
                "Can I fix a roof leak myself?",
                "How much does roof repair cost?",
            ],
        }
        result = template_prompt(ctx)
        assert "PEOPLE ALSO ASK" in result
        assert "How do I find a roof leak?" in result
        assert "Can I fix a roof leak myself?" in result
        assert "How much does roof repair cost?" in result

    def test_paa_capped_at_eight(self):
        ctx = {
            "keyword": "roof repair",
            "role": "standalone",
            "target_words": 1500,
            "paa": [f"Question {i}?" for i in range(12)],
        }
        result = template_prompt(ctx)
        # Only first 8 should appear
        assert "Question 7?" in result
        assert "Question 8?" not in result

    def test_empty_paa_no_paa_section(self):
        ctx = {"keyword": "roof repair", "role": "standalone", "target_words": 1500, "paa": []}
        result = template_prompt(ctx)
        assert "PEOPLE ALSO ASK" not in result

    def test_missing_paa_key_no_section(self):
        ctx = {"keyword": "roof repair", "role": "standalone", "target_words": 1500}
        result = template_prompt(ctx)
        assert "PEOPLE ALSO ASK" not in result


# ---------------------------------------------------------------------------
# template_prompt — answer-box / featured snippet
# ---------------------------------------------------------------------------

class TestTemplateAnswerBox:
    def test_answer_box_section_injected(self):
        ctx = {
            "keyword": "how to patch a roof",
            "role": "standalone",
            "target_words": 1500,
            "answer_box": {
                "answer": "Apply roofing cement to the damaged area.",
                "link": "https://example.com/roof",
                "title": "Roof Patch Guide",
            },
        }
        result = template_prompt(ctx)
        assert "FEATURED SNIPPET" in result
        assert "Apply roofing cement" in result
        assert "https://example.com/roof" in result

    def test_answer_box_truncated_at_400_chars(self):
        long_answer = "A" * 500
        ctx = {
            "keyword": "roof",
            "role": "standalone",
            "target_words": 1500,
            "answer_box": {"answer": long_answer},
        }
        result = template_prompt(ctx)
        # 400 A's should be in the result, but not 500
        assert "A" * 400 in result
        assert "A" * 401 not in result

    def test_no_answer_box_no_snippet_section(self):
        ctx = {"keyword": "roof repair", "role": "standalone", "target_words": 1500, "answer_box": None}
        result = template_prompt(ctx)
        assert "FEATURED SNIPPET" not in result

    def test_answer_box_empty_answer_and_snippet_no_section(self):
        ctx = {
            "keyword": "roof repair",
            "role": "standalone",
            "target_words": 1500,
            "answer_box": {"answer": "", "snippet": "", "link": "https://x.com"},
        }
        result = template_prompt(ctx)
        assert "FEATURED SNIPPET" not in result

    def test_snippet_key_used_when_no_answer(self):
        ctx = {
            "keyword": "roof types",
            "role": "standalone",
            "target_words": 1500,
            "answer_box": {"snippet": "Asphalt shingles are the most common.", "link": "https://x.com"},
        }
        result = template_prompt(ctx)
        assert "FEATURED SNIPPET" in result
        assert "Asphalt shingles" in result


# ---------------------------------------------------------------------------
# template_prompt — related searches
# ---------------------------------------------------------------------------

class TestTemplateRelated:
    def test_related_searches_injected(self):
        ctx = {
            "keyword": "roof repair",
            "role": "standalone",
            "target_words": 1500,
            "related": ["roof repair cost", "emergency roof repair", "flat roof repair"],
        }
        result = template_prompt(ctx)
        assert "RELATED SEARCHES" in result
        assert "roof repair cost" in result

    def test_related_capped_at_six(self):
        ctx = {
            "keyword": "roof",
            "role": "standalone",
            "target_words": 1500,
            "related": [f"search {i}" for i in range(10)],
        }
        result = template_prompt(ctx)
        assert "search 5" in result
        assert "search 6" not in result

    def test_empty_related_no_section(self):
        ctx = {"keyword": "roof", "role": "standalone", "target_words": 1500, "related": []}
        result = template_prompt(ctx)
        assert "RELATED SEARCHES" not in result


# ---------------------------------------------------------------------------
# template_prompt — pillar role
# ---------------------------------------------------------------------------

class TestTemplatePillarRole:
    def test_pillar_role_guidance_injected(self):
        ctx = {
            "keyword": "roofing",
            "role": "pillar",
            "target_words": 2500,
            "topic": "roofing",
        }
        result = template_prompt(ctx)
        assert "PILLAR PAGE" in result
        assert "PILLAR" in result

    def test_pillar_mentions_table_of_contents(self):
        ctx = {"keyword": "roofing", "role": "pillar", "target_words": 2500}
        result = template_prompt(ctx)
        assert "Table of Contents" in result

    def test_pillar_mentions_target_words(self):
        ctx = {"keyword": "roofing", "role": "pillar", "target_words": 2500}
        result = template_prompt(ctx)
        assert "2500" in result


# ---------------------------------------------------------------------------
# template_prompt — cluster role
# ---------------------------------------------------------------------------

class TestTemplateClusterRole:
    def test_cluster_role_guidance_injected(self):
        ctx = {
            "keyword": "roof leak repair cost",
            "role": "cluster",
            "target_words": 1800,
            "pillar_slug": "roofing-guide",
            "topic": "roofing",
        }
        result = template_prompt(ctx)
        assert "CLUSTER ARTICLE" in result

    def test_cluster_pillar_slug_referenced(self):
        ctx = {
            "keyword": "roof leak repair cost",
            "role": "cluster",
            "target_words": 1800,
            "pillar_slug": "roofing-guide",
        }
        result = template_prompt(ctx)
        assert "roofing-guide" in result

    def test_cluster_internal_link_critical_note(self):
        ctx = {
            "keyword": "roof leak cost",
            "role": "cluster",
            "target_words": 1800,
            "pillar_slug": "roofing-guide",
        }
        result = template_prompt(ctx)
        assert "roofing-guide" in result

    def test_cluster_with_internal_links_list(self):
        ctx = {
            "keyword": "roof shingle repair",
            "role": "cluster",
            "target_words": 1800,
            "pillar_slug": "roofing-guide",
            "internal_links": ["emergency-roof-repair", "roof-replacement-cost"],
        }
        result = template_prompt(ctx)
        assert "emergency-roof-repair" in result
        assert "CRITICAL" in result


# ---------------------------------------------------------------------------
# template_prompt — author E-E-A-T
# ---------------------------------------------------------------------------

class TestTemplateAuthor:
    def test_author_section_injected(self):
        ctx = {
            "keyword": "roof repair",
            "role": "standalone",
            "target_words": 1500,
            "author": {
                "name": "John Smith",
                "credentials": "Licensed Roofing Contractor",
                "bio": "20 years in the industry.",
                "linkedin": "https://linkedin.com/in/johnsmith",
            },
        }
        result = template_prompt(ctx)
        assert "ARTICLE AUTHOR" in result
        assert "John Smith" in result
        assert "Licensed Roofing Contractor" in result
        assert "https://linkedin.com/in/johnsmith" in result

    def test_author_without_optional_fields(self):
        ctx = {
            "keyword": "roof repair",
            "role": "standalone",
            "target_words": 1500,
            "author": {"name": "Jane Doe"},
        }
        result = template_prompt(ctx)
        assert "ARTICLE AUTHOR" in result
        assert "Jane Doe" in result

    def test_no_author_no_section(self):
        ctx = {"keyword": "roof repair", "role": "standalone", "target_words": 1500}
        result = template_prompt(ctx)
        assert "ARTICLE AUTHOR" not in result

    def test_author_none_no_section(self):
        ctx = {"keyword": "roof repair", "role": "standalone", "target_words": 1500, "author": None}
        result = template_prompt(ctx)
        assert "ARTICLE AUTHOR" not in result

    def test_author_empty_dict_no_section(self):
        ctx = {"keyword": "roof repair", "role": "standalone", "target_words": 1500, "author": {}}
        result = template_prompt(ctx)
        assert "ARTICLE AUTHOR" not in result


# ---------------------------------------------------------------------------
# template_prompt — internal links
# ---------------------------------------------------------------------------

class TestTemplateInternalLinks:
    def test_internal_links_guidance_injected(self):
        ctx = {
            "keyword": "roof repair",
            "role": "standalone",
            "target_words": 1500,
            "internal_links": ["emergency-repairs", "roof-inspection-guide"],
        }
        result = template_prompt(ctx)
        assert "emergency-repairs" in result
        assert "ANCHOR TEXT VARIATION" in result

    def test_internal_links_capped_at_twenty(self):
        ctx = {
            "keyword": "roof",
            "role": "standalone",
            "target_words": 1500,
            "internal_links": [f"article-{i}" for i in range(25)],
        }
        result = template_prompt(ctx)
        # Only first 20 slugs should appear in the list
        assert "article-19" in result
        assert "article-20" not in result

    def test_no_internal_links_shows_empty_array_note(self):
        ctx = {"keyword": "roof", "role": "standalone", "target_words": 1500, "internal_links": []}
        result = template_prompt(ctx)
        assert "internalLinks can be an empty array" in result


# ---------------------------------------------------------------------------
# template_prompt — all template types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template_key,expected_fragment", [
    ("how-to-guide", "HOW-TO GUIDE"),
    ("faq-article", "FAQ-STYLE"),
    ("educational-article", "EDUCATIONAL ARTICLE"),
    ("service-page", "SERVICE PAGE"),
    ("local-service-page", "LOCAL SERVICE PAGE"),
    ("buying-guide", "BUYING GUIDE"),
    ("comparison", "COMPARISON"),
    ("listicle", "LISTICLE"),
])
def test_template_types(template_key, expected_fragment):
    ctx = {
        "keyword": "roof repair",
        "role": "standalone",
        "target_words": 1500,
        "template": template_key,
        "location": "Dallas, TX",
    }
    result = template_prompt(ctx)
    assert expected_fragment in result


# ---------------------------------------------------------------------------
# template_prompt — angle guidance
# ---------------------------------------------------------------------------

class TestTemplateAngle:
    def test_angle_injected(self):
        ctx = {
            "keyword": "roof repair",
            "role": "standalone",
            "target_words": 1500,
            "angle": "Focus on hail damage specifically — most guides skip it.",
        }
        result = template_prompt(ctx)
        assert "UNIQUE ANGLE" in result
        assert "hail damage specifically" in result

    def test_no_angle_no_section(self):
        ctx = {"keyword": "roof repair", "role": "standalone", "target_words": 1500}
        result = template_prompt(ctx)
        assert "UNIQUE ANGLE" not in result


# ---------------------------------------------------------------------------
# template_prompt — planned title
# ---------------------------------------------------------------------------

class TestTemplatePlannedTitle:
    def test_title_guidance_injected(self):
        ctx = {
            "keyword": "roof repair",
            "role": "standalone",
            "target_words": 1500,
            "title": "The Ultimate Roof Repair Guide for Dallas Homeowners",
        }
        result = template_prompt(ctx)
        assert "PLANNED TITLE" in result
        assert "The Ultimate Roof Repair Guide for Dallas Homeowners" in result

    def test_no_title_no_section(self):
        ctx = {"keyword": "roof repair", "role": "standalone", "target_words": 1500}
        result = template_prompt(ctx)
        assert "PLANNED TITLE" not in result
