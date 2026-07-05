"""Behavioral tests for POST /articles/{slug}/reprocess and jobs/reprocess_articles.py.

- Verifies sanitize_article_html converts markdown artifacts to clean HTML.
- Verifies the API endpoint sanitizes and persists content.
- Verifies WordPress update is called when wp_post_id is set and creds are present.
- Verifies WP update is skipped when creds are absent.
- Verifies no [! markers or pipe-tables survive in reprocessed output.
- Verifies role guard (admin only).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.routes.articles import router
from app.models import Article, SessionLocal, init_db


def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def _admin_client():
    set_verifier(lambda token: {"uid": "u1", "email": "admin@x.com", "role": "admin"})
    return TestClient(_make_app())


def _sales_client():
    set_verifier(lambda token: {"uid": "u2", "email": "sales@x.com", "role": "sales"})
    return TestClient(_make_app())


AUTH = {"Authorization": "Bearer tok"}

# Markdown content with all the artifact types we need to sanitize
_DIRTY_CONTENT = (
    "# My Article Title\n\n"
    "Some intro paragraph.\n\n"
    "> [!TIP]\n"
    "> Use a rubber mallet for tight fits.\n\n"
    "## Cost Comparison\n\n"
    "Here is a table:\n\n"
    "| Material | Cost |\n"
    "|----------|------|\n"
    "| Asphalt  | $150 |\n"
    "| Metal    | $300 |\n\n"
    "> [!NOTE]\n"
    "> Always check local building codes.\n\n"
    "**Important:** Do not skip underlayment.\n\n"
    "### Installation Steps\n\n"
    "Follow these steps."
)

# Expected: no [! markers, no pipe tables, headings as HTML
_CLEAN_MARKERS = [
    '[!',           # admonition markers must be gone
    '> [!',         # blockquote admonition syntax must be gone
    '|-------',     # table separator rows must be gone
]
_PRESENT_MARKERS = [
    '<aside',       # callouts converted to aside elements
    '<h2>',         # ## headings converted
    '<h3>',         # ### headings converted
    '<table>',      # pipe table converted
    '<strong>',     # **bold** converted
]


def setup_module(module):
    init_db()


# ---------------------------------------------------------------------------
# sanitize_article_html unit tests
# ---------------------------------------------------------------------------

class TestSanitizeArticleHtml:
    def test_admonition_tip_converted(self):
        from jobs.article_job import sanitize_article_html
        content = "> [!TIP]\n> Use a rubber mallet.\n"
        result = sanitize_article_html(content)
        assert "[!" not in result
        assert '<aside class="tip">' in result
        assert "rubber mallet" in result

    def test_admonition_warning_converted(self):
        from jobs.article_job import sanitize_article_html
        content = "> [!WARNING]\n> Watch out for loose nails.\n"
        result = sanitize_article_html(content)
        assert "[!" not in result
        assert '<aside class="warning">' in result

    def test_admonition_note_converted(self):
        from jobs.article_job import sanitize_article_html
        content = "> [!NOTE]\n> Check local building codes.\n"
        result = sanitize_article_html(content)
        assert "[!" not in result
        assert '<aside class="note">' in result

    def test_admonition_key_converted(self):
        from jobs.article_job import sanitize_article_html
        content = "> [!KEY]\n> This is the key insight.\n"
        result = sanitize_article_html(content)
        assert "[!" not in result
        assert '<aside class="key">' in result

    def test_admonition_caution_maps_to_warning(self):
        from jobs.article_job import sanitize_article_html
        content = "> [!CAUTION]\n> Be careful with moisture.\n"
        result = sanitize_article_html(content)
        assert '[!' not in result
        assert '<aside class="warning">' in result

    def test_bare_admonition_marker_stripped(self):
        from jobs.article_job import sanitize_article_html
        content = "Some text [!TIP] more text"
        result = sanitize_article_html(content)
        assert "[!" not in result

    def test_markdown_h2_converted(self):
        from jobs.article_job import sanitize_article_html
        result = sanitize_article_html("## Cost Guide\n\nSome text.")
        assert "<h2>Cost Guide</h2>" in result
        assert "##" not in result

    def test_markdown_h3_converted(self):
        from jobs.article_job import sanitize_article_html
        result = sanitize_article_html("### Installation Steps\n\nText.")
        assert "<h3>Installation Steps</h3>" in result

    def test_markdown_h1_converted(self):
        from jobs.article_job import sanitize_article_html
        result = sanitize_article_html("# Main Title\n\nText.")
        assert "<h1>Main Title</h1>" in result

    def test_markdown_bold_converted(self):
        from jobs.article_job import sanitize_article_html
        result = sanitize_article_html("**Important:** Do this first.")
        assert "<strong>Important:</strong>" in result
        assert "**" not in result

    def test_pipe_table_converted_to_html(self):
        from jobs.article_job import sanitize_article_html
        content = "| Material | Cost |\n|----------|------|\n| Asphalt  | $150 |\n"
        result = sanitize_article_html(content)
        assert "<table>" in result
        assert "<th>Material</th>" in result
        assert "<td>Asphalt</td>" in result
        assert "|-------" not in result

    def test_empty_content_returns_empty(self):
        from jobs.article_job import sanitize_article_html
        assert sanitize_article_html("") == ""
        assert sanitize_article_html(None) is None  # type: ignore[arg-type]

    def test_already_clean_html_unchanged(self):
        from jobs.article_job import sanitize_article_html
        content = '<h2>Cost</h2>\n<p>Some <strong>text</strong>.</p>\n<aside class="tip"><p>Tip.</p></aside>'
        result = sanitize_article_html(content)
        # Should pass through without double-converting
        assert "<h2>Cost</h2>" in result
        assert '<aside class="tip">' in result

    def test_dirty_content_has_no_admonition_markers(self):
        from jobs.article_job import sanitize_article_html
        result = sanitize_article_html(_DIRTY_CONTENT)
        assert "[!" not in result

    def test_dirty_content_has_no_pipe_tables(self):
        from jobs.article_job import sanitize_article_html
        result = sanitize_article_html(_DIRTY_CONTENT)
        assert "|-------" not in result
        assert "<table>" in result

    def test_dirty_content_has_html_headings(self):
        from jobs.article_job import sanitize_article_html
        result = sanitize_article_html(_DIRTY_CONTENT)
        assert "<h2>" in result
        assert "<h3>" in result

    def test_dirty_content_has_aside_callouts(self):
        from jobs.article_job import sanitize_article_html
        result = sanitize_article_html(_DIRTY_CONTENT)
        assert "<aside" in result


# ---------------------------------------------------------------------------
# POST /articles/{slug}/reprocess API tests
# ---------------------------------------------------------------------------

class TestReprocessEndpoint:
    def _create_article(self, slug: str, content: str, wp_post_id: int | None = None):
        """Insert an Article row directly for test setup."""
        with SessionLocal() as db:
            existing = db.get(Article, slug)
            if existing is not None:
                db.delete(existing)
                db.commit()
            a = Article(
                slug=slug,
                title=f"Test Article {slug}",
                meta="test meta",
                content_md=content,
                faq_json=None,
                jsonld_json=None,
                role="standalone",
                pillar_slug=None,
                wp_post_id=wp_post_id,
                status="draft",
                publish_at=None,
            )
            db.add(a)
            db.commit()

    def test_reprocess_sanitizes_content(self, monkeypatch):
        """POST /articles/{slug}/reprocess returns clean HTML with no [! markers."""
        monkeypatch.delenv("WP_URL", raising=False)
        monkeypatch.delenv("WP_USER", raising=False)
        monkeypatch.delenv("WP_APP_PWD", raising=False)

        self._create_article("reprocess-test-1", _DIRTY_CONTENT)
        c = _admin_client()
        r = c.post("/articles/reprocess-test-1/reprocess", headers=AUTH)
        assert r.status_code == 200, r.text
        data = r.json()
        content = data["content_md"]
        assert "[!" not in content
        assert "|-------" not in content
        assert "<h2>" in content

    def test_reprocess_persists_to_db(self, monkeypatch):
        """After reprocess the DB row has sanitized content."""
        monkeypatch.delenv("WP_URL", raising=False)
        monkeypatch.delenv("WP_USER", raising=False)
        monkeypatch.delenv("WP_APP_PWD", raising=False)

        self._create_article("reprocess-test-persist", _DIRTY_CONTENT)
        c = _admin_client()
        c.post("/articles/reprocess-test-persist/reprocess", headers=AUTH)

        with SessionLocal() as db:
            a = db.get(Article, "reprocess-test-persist")
            assert a is not None
            assert "[!" not in (a.content_md or "")

    def test_reprocess_calls_wp_update_when_wp_post_id_set(self, monkeypatch):
        """WP update is called when wp_post_id is set and creds present."""
        monkeypatch.setenv("WP_URL", "https://perkinsroofing.net")
        monkeypatch.setenv("WP_USER", "admin")
        monkeypatch.setenv("WP_APP_PWD", "test-pwd")

        wp_update_calls = []

        def _fake_update(post_id, *, title, html, meta_description, jsonld, status):
            wp_update_calls.append({"post_id": post_id, "title": title})

        monkeypatch.setattr("adapters.wordpress.update", _fake_update)

        self._create_article("reprocess-test-wp", _DIRTY_CONTENT, wp_post_id=99)
        c = _admin_client()
        r = c.post("/articles/reprocess-test-wp/reprocess", headers=AUTH)
        assert r.status_code == 200, r.text
        assert len(wp_update_calls) == 1
        assert wp_update_calls[0]["post_id"] == 99

    def test_reprocess_skips_wp_when_no_wp_post_id(self, monkeypatch):
        """WP update is NOT called when wp_post_id is None."""
        monkeypatch.setenv("WP_URL", "https://perkinsroofing.net")
        monkeypatch.setenv("WP_USER", "admin")
        monkeypatch.setenv("WP_APP_PWD", "test-pwd")

        wp_update_calls = []

        def _fake_update(post_id, *, title, html, meta_description, jsonld, status):
            wp_update_calls.append(post_id)

        monkeypatch.setattr("adapters.wordpress.update", _fake_update)

        self._create_article("reprocess-test-no-wp-id", _DIRTY_CONTENT, wp_post_id=None)
        c = _admin_client()
        r = c.post("/articles/reprocess-test-no-wp-id/reprocess", headers=AUTH)
        assert r.status_code == 200, r.text
        assert len(wp_update_calls) == 0

    def test_reprocess_skips_wp_when_creds_absent(self, monkeypatch):
        """WP update is NOT called when env creds are absent."""
        monkeypatch.delenv("WP_URL", raising=False)
        monkeypatch.delenv("WP_USER", raising=False)
        monkeypatch.delenv("WP_APP_PWD", raising=False)

        wp_update_calls = []

        def _fake_update(post_id, *, title, html, meta_description, jsonld, status):
            wp_update_calls.append(post_id)

        monkeypatch.setattr("adapters.wordpress.update", _fake_update)

        self._create_article("reprocess-test-no-creds", _DIRTY_CONTENT, wp_post_id=77)
        c = _admin_client()
        r = c.post("/articles/reprocess-test-no-creds/reprocess", headers=AUTH)
        assert r.status_code == 200, r.text
        assert len(wp_update_calls) == 0

    def test_reprocess_404_on_missing(self):
        c = _admin_client()
        r = c.post("/articles/slug-that-does-not-exist-xyz/reprocess", headers=AUTH)
        assert r.status_code == 404, r.text

    def test_reprocess_requires_admin(self, monkeypatch):
        monkeypatch.delenv("WP_URL", raising=False)
        self._create_article("reprocess-auth-test", "# Title\n\nContent.", wp_post_id=None)
        c = _sales_client()
        r = c.post("/articles/reprocess-auth-test/reprocess", headers=AUTH)
        assert r.status_code == 403, r.text

    def test_reprocess_returns_full_article_shape(self, monkeypatch):
        """Response includes all expected article fields."""
        monkeypatch.delenv("WP_URL", raising=False)
        monkeypatch.delenv("WP_USER", raising=False)
        monkeypatch.delenv("WP_APP_PWD", raising=False)

        self._create_article("reprocess-shape-test", "## Section\n\nText.")
        c = _admin_client()
        r = c.post("/articles/reprocess-shape-test/reprocess", headers=AUTH)
        assert r.status_code == 200, r.text
        data = r.json()
        for key in ("slug", "title", "content_md", "meta", "faq_json", "status", "wp_post_id"):
            assert key in data, f"missing key: {key}"


# ---------------------------------------------------------------------------
# jobs/reprocess_articles.run() unit tests
# ---------------------------------------------------------------------------

class TestReprocessJob:
    def _insert_article(self, slug: str, content: str, wp_post_id: int | None = None):
        with SessionLocal() as db:
            existing = db.get(Article, slug)
            if existing is not None:
                db.delete(existing)
                db.commit()
            a = Article(
                slug=slug,
                title=f"Job Test {slug}",
                meta="",
                content_md=content,
                faq_json=None,
                jsonld_json=None,
                role="standalone",
                pillar_slug=None,
                wp_post_id=wp_post_id,
                status="draft",
                publish_at=None,
            )
            db.add(a)
            db.commit()

    def test_run_all_articles(self, monkeypatch):
        monkeypatch.delenv("WP_URL", raising=False)
        monkeypatch.delenv("WP_USER", raising=False)
        monkeypatch.delenv("WP_APP_PWD", raising=False)

        self._insert_article("job-test-all-1", _DIRTY_CONTENT)
        self._insert_article("job-test-all-2", _DIRTY_CONTENT)

        from jobs.reprocess_articles import run
        result = run()
        assert result["processed"] >= 2
        assert result["errors"] == []

    def test_run_specific_slugs(self, monkeypatch):
        monkeypatch.delenv("WP_URL", raising=False)
        monkeypatch.delenv("WP_USER", raising=False)
        monkeypatch.delenv("WP_APP_PWD", raising=False)

        self._insert_article("job-slug-1", _DIRTY_CONTENT)
        self._insert_article("job-slug-2", _DIRTY_CONTENT)

        from jobs.reprocess_articles import run
        result = run(["job-slug-1"])
        assert result["processed"] == 1
        assert result["errors"] == []

    def test_run_sanitizes_content_in_db(self, monkeypatch):
        monkeypatch.delenv("WP_URL", raising=False)
        monkeypatch.delenv("WP_USER", raising=False)
        monkeypatch.delenv("WP_APP_PWD", raising=False)

        self._insert_article("job-sanitize-check", _DIRTY_CONTENT)

        from jobs.reprocess_articles import run
        run(["job-sanitize-check"])

        with SessionLocal() as db:
            a = db.get(Article, "job-sanitize-check")
            assert "[!" not in (a.content_md or "")
            assert "|-------" not in (a.content_md or "")

    def test_run_calls_wp_update_when_post_id_and_creds(self, monkeypatch):
        monkeypatch.setenv("WP_URL", "https://perkinsroofing.net")
        monkeypatch.setenv("WP_USER", "admin")
        monkeypatch.setenv("WP_APP_PWD", "pwd")

        wp_calls = []

        def _fake_update(post_id, *, title, html, meta_description, jsonld, status):
            wp_calls.append(post_id)

        monkeypatch.setattr("adapters.wordpress.update", _fake_update)

        self._insert_article("job-wp-sync", _DIRTY_CONTENT, wp_post_id=55)
        from jobs.reprocess_articles import run
        result = run(["job-wp-sync"])
        assert result["wp_synced"] == 1
        assert 55 in wp_calls

    def test_run_no_wp_when_creds_absent(self, monkeypatch):
        monkeypatch.delenv("WP_URL", raising=False)
        monkeypatch.delenv("WP_USER", raising=False)
        monkeypatch.delenv("WP_APP_PWD", raising=False)

        self._insert_article("job-no-creds", _DIRTY_CONTENT, wp_post_id=66)
        from jobs.reprocess_articles import run
        result = run(["job-no-creds"])
        assert result["wp_synced"] == 0
        assert result["errors"] == []

    def test_run_result_shape(self, monkeypatch):
        monkeypatch.delenv("WP_URL", raising=False)
        monkeypatch.delenv("WP_USER", raising=False)
        monkeypatch.delenv("WP_APP_PWD", raising=False)

        self._insert_article("job-shape", "## H2\n\nText.", wp_post_id=None)
        from jobs.reprocess_articles import run
        result = run(["job-shape"])
        assert "processed" in result
        assert "updated" in result
        assert "wp_synced" in result
        assert "errors" in result
        assert isinstance(result["errors"], list)

    def test_run_missing_slug_ignored(self, monkeypatch):
        """A slug that doesn't exist in DB is silently skipped."""
        monkeypatch.delenv("WP_URL", raising=False)
        from jobs.reprocess_articles import run
        result = run(["slug-does-not-exist-at-all-xyz"])
        assert result["processed"] == 0
        assert result["errors"] == []
