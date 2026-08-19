from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "web" / "src"


def test_opportunities_is_scored_inbox():
    src = (ROOT / "pages" / "Opportunities.tsx").read_text()
    assert "/topic-graph?kind=articles&published=no" in src
    assert "This week — articles to write" in src
    assert "Generate cluster articles" not in src or "Generate cluster" in src
    assert "do not" in src.lower() or "not yet in an article" in src.lower() or "ground an under-served" in src


def test_search_ask_does_not_generate_articles():
    src = (ROOT / "pages" / "SearchAsk.tsx").read_text()
    assert "generate-article" not in src
    assert "/topic-graph/genres" in src
    assert '{mo === "ask" ? "Ask a question" : "Search"}' in src


def test_archive_has_genre_filter_and_thumb():
    src = (ROOT / "pages" / "Archive.tsx").read_text()
    assert 'params.set("genre"' in src
    assert "i.ytimg.com" in src
    assert "All genres" in src


def test_articles_and_faq_mount_topic_graph():
    articles = (ROOT / "pages" / "Articles.tsx").read_text()
    faq = (ROOT / "pages" / "Faq.tsx").read_text()
    graph = (ROOT / "pages" / "TopicGraph.tsx").read_text()
    assert "Topic Graph" in articles
    assert "TopicGraphPanel" in articles
    assert 'kind="articles"' in articles
    assert "FAQ Graph" in faq
    assert 'kind="faqs"' in faq
    assert "/topic-graph" in graph
    assert "Icicle" in graph
    assert "GenreTable" in graph
    assert "Published" in graph
    assert "Not published" in graph
    assert "Evenness" in graph


def test_scheduling_defaults_to_unpublished_next_up():
    src = (ROOT / "pages" / "Scheduling.tsx").read_text()
    assert 'useState<string>("unpublished")' in src
    assert "Unpublished (next up first)" in src
    assert "Published (newest first)" in src


def test_portfolio_preview_from_list():
    src = (ROOT / "pages" / "Portfolio.tsx").read_text()
    assert "Preview" in src
    assert "preview_html" in src
    assert "This is the HTML that Publish to WordPress will push" in src
    assert "DataSources" not in src
