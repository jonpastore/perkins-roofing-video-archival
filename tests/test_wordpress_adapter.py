import os

import adapters.wordpress as wp


class _Resp:
    url = "https://1205166.us6.myftpupload.com/wp-json/"

    def raise_for_status(self):
        return None


def test_wp_api_url_uses_redirected_rest_host(monkeypatch):
    calls = []

    def fake_get(url, timeout, allow_redirects):
        calls.append((url, timeout, allow_redirects))
        return _Resp()

    wp._rest_base_url.cache_clear()
    monkeypatch.setenv("WP_URL", "https://jhk.14f.myftpupload.com")
    monkeypatch.setattr(wp.requests, "get", fake_get)

    assert wp._wp_api_url("/wp-json/wp/v2/posts/123") == (
        "https://1205166.us6.myftpupload.com/wp-json/wp/v2/posts/123"
    )
    assert calls == [("https://jhk.14f.myftpupload.com/wp-json/", 10, True)]


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
