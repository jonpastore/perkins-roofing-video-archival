from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "web" / "src"


def test_opportunities_has_social_and_film_queues():
    src = (ROOT / "pages" / "Opportunities.tsx").read_text()
    assert "/topic-graph/social-brief" in src
    assert "this_week" in src
    assert "This week — ship these first" in src
    assert "ScoreChip" in src
    assert "Cut for social" in src
    assert "Film next" in src
    assert "/archive/${id}/edit-plan" in src or "/archive/${c.id}/edit-plan" in src


def test_comments_filters_paa_questions_and_hides_youtube_post():
    src = (ROOT / "pages" / "Comments.tsx").read_text()
    assert 'option value="paa"' in src
    assert "Questions (PAA)" in src
    assert '(item.platform || "youtube") === "youtube"' in src
    assert "SCORE_HELP.heat" in src
    assert "HelpTip" in src


def test_opportunities_scans_competitors_on_demand():
    src = (ROOT / "pages" / "Opportunities.tsx").read_text()
    assert "/topic-graph/competitor-scan" in src
    assert "Scan what others cover" in src
    assert "method: \"POST\"" in src or 'method: "POST"' in src


def test_opportunities_is_scored_inbox():
    src = (ROOT / "pages" / "Opportunities.tsx").read_text()
    assert "/topic-graph?kind=articles&published=no" in src
    assert "This week — articles to write" in src
    assert "Generate cluster articles" not in src or "Generate cluster" in src
    assert "do not" in src.lower() or "not yet in an article" in src.lower() or "ground an under-served" in src
    assert "TopicGraphPanel" in src
    assert "setShowGraph({ kind: \"articles\"" in src
    assert "initialGenreId" in src


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


def test_longform_queue_is_fifteen_minutes_and_has_analyze():
    status = (ROOT / "pages" / "Status.tsx").read_text()
    assert "min_length=900" in status
    assert "over 15 min" in status
    assert "/archive/${id}/edit-plan" in status
    assert "Analyze cut" in status
    assert "under 30 min" in status
    assert "aria-expanded" in status
    assert "LONGFORM_HELP" in status
    assert "HelpTip" in status
    assert "Open in Clip Studio" in status
    assert "ytThumb" in status
    assert "createPortal" in status
    assert "Mark chopped" in status
    assert 'variant="ghost"' in status


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
    assert "GenreBar" in graph
    assert "GenreTable" not in graph
    assert "createPortal" in graph
    assert "Published" in graph
    assert "Not published" in graph
    assert "Search subjects" in graph
    assert "HelpTip" in graph
    assert "ScoreChip" in graph
    assert "opp 0.00" not in graph


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
    assert "createPortal" in src
    assert "DataSources" not in src
