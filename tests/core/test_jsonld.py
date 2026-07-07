"""Unit tests for core/jsonld.py — 100% coverage target."""

import pytest

from core.jsonld import build_article, build_faq_page, build_video_object


# ---------------------------------------------------------------------------
# build_video_object
# ---------------------------------------------------------------------------

class TestBuildVideoObject:
    def _make(self, **overrides):
        defaults = dict(
            title="How to Fix a Leaky Roof",
            description="Tim explains the most common causes of roof leaks.",
            thumbnail_url="https://i.ytimg.com/vi/abc123/hqdefault.jpg",
            upload_date="2024-03-15",
            content_url="https://www.youtube.com/watch?v=abc123",
            embed_url="https://www.youtube.com/embed/abc123",
            duration_iso="PT4M30S",
        )
        defaults.update(overrides)
        return build_video_object(**defaults)

    def test_context_is_schema_org(self):
        obj = self._make()
        assert obj["@context"] == "https://schema.org"

    def test_type_is_video_object(self):
        obj = self._make()
        assert obj["@type"] == "VideoObject"

    def test_name_field(self):
        obj = self._make(title="My Video")
        assert obj["name"] == "My Video"

    def test_description_field(self):
        obj = self._make(description="A short description.")
        assert obj["description"] == "A short description."

    def test_thumbnail_url(self):
        url = "https://example.com/thumb.jpg"
        obj = self._make(thumbnail_url=url)
        assert obj["thumbnailUrl"] == url

    def test_upload_date(self):
        obj = self._make(upload_date="2023-01-01")
        assert obj["uploadDate"] == "2023-01-01"

    def test_content_url(self):
        url = "https://www.youtube.com/watch?v=xyz"
        obj = self._make(content_url=url)
        assert obj["contentUrl"] == url

    def test_embed_url(self):
        url = "https://www.youtube.com/embed/xyz"
        obj = self._make(embed_url=url)
        assert obj["embedUrl"] == url

    def test_duration_iso(self):
        obj = self._make(duration_iso="PT1H2M3S")
        assert obj["duration"] == "PT1H2M3S"

    def test_returns_plain_dict(self):
        obj = self._make()
        assert isinstance(obj, dict)

    def test_exact_keys(self):
        obj = self._make()
        assert set(obj.keys()) == {
            "@context", "@type", "name", "description",
            "thumbnailUrl", "uploadDate", "contentUrl", "embedUrl", "duration",
        }

    def test_deterministic(self):
        """Same inputs always produce identical output."""
        a = self._make()
        b = self._make()
        assert a == b

    def test_youtube_deeplink_preserved(self):
        """YouTube ?t= deep-links are passed through unchanged — highest-leverage AIO field."""
        url = "https://www.youtube.com/watch?v=abc123&t=90"
        obj = self._make(content_url=url)
        assert obj["contentUrl"] == url


# ---------------------------------------------------------------------------
# build_faq_page
# ---------------------------------------------------------------------------

class TestBuildFaqPage:
    _faq = [
        {"q": "How long does a roof last?", "a": "20-30 years with proper maintenance."},
        {"q": "What causes roof leaks?", "a": "Damaged flashing and worn shingles."},
    ]

    def test_context_is_schema_org(self):
        obj = build_faq_page(self._faq)
        assert obj["@context"] == "https://schema.org"

    def test_type_is_faq_page(self):
        obj = build_faq_page(self._faq)
        assert obj["@type"] == "FAQPage"

    def test_main_entity_is_list(self):
        obj = build_faq_page(self._faq)
        assert isinstance(obj["mainEntity"], list)

    def test_main_entity_length_matches_input(self):
        obj = build_faq_page(self._faq)
        assert len(obj["mainEntity"]) == len(self._faq)

    def test_question_type(self):
        obj = build_faq_page(self._faq)
        for item in obj["mainEntity"]:
            assert item["@type"] == "Question"

    def test_question_name_field(self):
        obj = build_faq_page(self._faq)
        assert obj["mainEntity"][0]["name"] == "How long does a roof last?"
        assert obj["mainEntity"][1]["name"] == "What causes roof leaks?"

    def test_accepted_answer_type(self):
        obj = build_faq_page(self._faq)
        for item in obj["mainEntity"]:
            assert item["acceptedAnswer"]["@type"] == "Answer"

    def test_accepted_answer_text(self):
        obj = build_faq_page(self._faq)
        assert obj["mainEntity"][0]["acceptedAnswer"]["text"] == "20-30 years with proper maintenance."
        assert obj["mainEntity"][1]["acceptedAnswer"]["text"] == "Damaged flashing and worn shingles."

    def test_empty_faq_list(self):
        obj = build_faq_page([])
        assert obj["@type"] == "FAQPage"
        assert obj["mainEntity"] == []

    def test_single_item(self):
        obj = build_faq_page([{"q": "Q1", "a": "A1"}])
        assert len(obj["mainEntity"]) == 1
        assert obj["mainEntity"][0]["name"] == "Q1"
        assert obj["mainEntity"][0]["acceptedAnswer"]["text"] == "A1"

    def test_returns_plain_dict(self):
        obj = build_faq_page(self._faq)
        assert isinstance(obj, dict)

    def test_exact_top_level_keys(self):
        obj = build_faq_page(self._faq)
        assert set(obj.keys()) == {"@context", "@type", "mainEntity"}

    def test_deterministic(self):
        a = build_faq_page(self._faq)
        b = build_faq_page(self._faq)
        assert a == b

    def test_does_not_mutate_input(self):
        faq = [{"q": "Q", "a": "A"}]
        original = [{"q": "Q", "a": "A"}]
        build_faq_page(faq)
        assert faq == original


# ---------------------------------------------------------------------------
# build_article
# ---------------------------------------------------------------------------

class TestBuildArticle:
    def _make(self, **overrides):
        defaults = dict(
            headline="5 Signs Your Roof Needs Replacement",
            description="Learn the warning signs that indicate a roof replacement is due.",
            author_name="Tim Perkins",
            date_published="2024-06-01",
            url="https://perkinsroofing.net/blog/5-signs-roof-replacement",
        )
        defaults.update(overrides)
        return build_article(**defaults)

    def test_context_is_schema_org(self):
        obj = self._make()
        assert obj["@context"] == "https://schema.org"

    def test_type_is_article(self):
        obj = self._make()
        assert obj["@type"] == "Article"

    def test_headline_field(self):
        obj = self._make(headline="My Headline")
        assert obj["headline"] == "My Headline"

    def test_description_field(self):
        obj = self._make(description="A meta description.")
        assert obj["description"] == "A meta description."

    def test_author_is_person(self):
        obj = self._make()
        assert obj["author"]["@type"] == "Person"

    def test_author_name(self):
        obj = self._make(author_name="Jon Pastore")
        assert obj["author"]["name"] == "Jon Pastore"

    def test_date_published(self):
        obj = self._make(date_published="2024-01-15")
        assert obj["datePublished"] == "2024-01-15"

    def test_url_field(self):
        url = "https://perkinsroofing.net/blog/test"
        obj = self._make(url=url)
        assert obj["url"] == url

    def test_returns_plain_dict(self):
        obj = self._make()
        assert isinstance(obj, dict)

    def test_exact_top_level_keys(self):
        obj = self._make()
        assert set(obj.keys()) == {
            "@context", "@type", "headline", "description", "author", "datePublished", "url",
        }

    def test_author_exact_keys(self):
        obj = self._make()
        assert set(obj["author"].keys()) == {"@type", "name"}

    def test_deterministic(self):
        a = self._make()
        b = self._make()
        assert a == b

    def test_all_fields_independent(self):
        """Each field is independently settable without affecting others."""
        obj = self._make(
            headline="H",
            description="D",
            author_name="A",
            date_published="2020-01-01",
            url="https://example.com",
        )
        assert obj["headline"] == "H"
        assert obj["description"] == "D"
        assert obj["author"]["name"] == "A"
        assert obj["datePublished"] == "2020-01-01"
        assert obj["url"] == "https://example.com"


class TestFaqPageDefensive:
    def test_accepts_question_answer_keys(self):
        page = build_faq_page([{"question": "Q1?", "answer": "A1"}])
        assert page["mainEntity"][0]["name"] == "Q1?"
        assert page["mainEntity"][0]["acceptedAnswer"]["text"] == "A1"

    def test_skips_items_with_no_question(self):
        page = build_faq_page([{"a": "orphan answer"}, {"q": "Q?", "a": "A"}])
        assert len(page["mainEntity"]) == 1
        assert page["mainEntity"][0]["name"] == "Q?"

    def test_standard_q_a_still_works(self):
        page = build_faq_page([{"q": "Q?", "a": "A"}])
        assert page["mainEntity"][0]["name"] == "Q?"
