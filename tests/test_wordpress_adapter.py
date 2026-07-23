
import adapters.wordpress as wp


class _Resp:
    url = "https://redirect-target.example.com/wp-json/"

    def raise_for_status(self):
        return None


def test_wp_api_url_uses_redirected_rest_host(monkeypatch):
    calls = []

    def fake_get(url, timeout, allow_redirects):
        calls.append((url, timeout, allow_redirects))
        return _Resp()

    wp._rest_base_url.cache_clear()
    # Admin-config WP_URL (resolved_wp_url) — env WP_URL is deliberately ignored (d1e25b5).
    monkeypatch.setattr(wp, "resolved_wp_url", lambda: "https://configured-host.example.com")
    monkeypatch.setattr(wp._session, "get", fake_get)

    assert wp._wp_api_url("/wp-json/wp/v2/posts/123") == (
        "https://redirect-target.example.com/wp-json/wp/v2/posts/123"
    )
    assert calls == [("https://configured-host.example.com/wp-json/", 10, True)]


def test_auth_strips_spaces_from_app_password(monkeypatch):
    monkeypatch.setenv("WP_USER", "jon")
    monkeypatch.setenv("WP_APP_PWD", "abcd efgh ijkl")

    assert wp._auth() == ("jon", "abcdefghijkl")


def test_post_meta_includes_rank_math_when_focus_keyword_set(monkeypatch):
    monkeypatch.delenv("WP_FOCUS_KEYWORD", raising=False)
    meta = wp._post_meta(
        title="7 Roof Tips",
        meta_description="desc",
        jsonld=[{"@type": "Article"}],
        focus_keyword="roof estimate vs inspection report",
    )
    assert meta["rank_math_focus_keyword"] == "roof estimate vs inspection report"
    assert meta["rank_math_title"] == "7 Roof Tips"
    assert meta["rank_math_description"] == "desc"
    assert "_perkins_jsonld" in meta


def test_post_meta_omits_empty_focus_keyword(monkeypatch):
    monkeypatch.delenv("WP_FOCUS_KEYWORD", raising=False)
    meta = wp._post_meta(title="t", meta_description="d", jsonld=[], focus_keyword=None)
    assert "rank_math_focus_keyword" not in meta
    assert meta["rank_math_title"] == "t"


def test_publish_sends_the_slug_so_the_permalink_matches_our_article(monkeypatch):
    # The focus keyword is derived FROM the article slug, so the WP permalink must be that same
    # slug — otherwise WordPress invents one from the title and Rank Math's kw-in-slug check
    # disagrees with core.seo's.
    sent = {}

    class _R:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": 4242}

    def fake_post(url, json=None, auth=None, timeout=None):
        sent.update(json)
        return _R()

    monkeypatch.setenv("WP_URL", "https://example.com")
    monkeypatch.setenv("WP_USER", "jon")
    monkeypatch.setenv("WP_APP_PWD", "x")
    monkeypatch.setattr(wp, "_rest_base_url", lambda b: "https://example.com")
    monkeypatch.setattr(wp, "_author_id", lambda: 1)
    monkeypatch.setattr(wp._session, "post", fake_post)

    pid = wp.publish(title="T", html="<p>x</p>", meta_description="d", jsonld=[],
                     focus_keyword="wall flashings", slug="wall-flashings")
    assert pid == 4242
    assert sent["slug"] == "wall-flashings"
    assert sent["status"] == "draft"


def test_publish_omits_slug_when_not_given(monkeypatch):
    sent = {}

    class _R:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": 1}

    monkeypatch.setenv("WP_URL", "https://example.com")
    monkeypatch.setenv("WP_USER", "jon")
    monkeypatch.setenv("WP_APP_PWD", "x")
    monkeypatch.setattr(wp, "_rest_base_url", lambda b: "https://example.com")
    monkeypatch.setattr(wp, "_author_id", lambda: 1)
    monkeypatch.setattr(wp._session, "post",
                        lambda url, json=None, auth=None, timeout=None: (sent.update(json), _R())[1])
    wp.publish(title="T", html="<p>x</p>", meta_description="d", jsonld=[])
    assert "slug" not in sent
