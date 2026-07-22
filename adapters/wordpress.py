"""WordPress REST API adapter (I/O — coverage-omitted).

Publishes posts via HTTP Basic auth (WP Application Password).

Environment variables required:
    WP_URL      Root URL of the WordPress site, e.g. https://example.com
    WP_USER     WordPress username
    WP_APP_PWD  WordPress Application Password (spaces optional, stripped internally)

JSON-LD is stored in post-meta key ``_perkins_jsonld`` as a JSON string.
A must-use plugin (wp-mu-plugin/perkins-jsonld.php) registers the meta key
(register_post_meta with show_in_rest=True) and echoes the stored JSON-LD in
wp_head — WordPress strips <script> from post content, so the mu-plugin is
required for the JSON-LD to appear in <head>.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from urllib.parse import urljoin, urlparse

import requests


def _auth() -> tuple[str, str]:
    user = os.environ["WP_USER"]
    pwd = os.environ["WP_APP_PWD"].replace(" ", "")
    return user, pwd


def resolved_wp_url() -> str:
    """Canonical WordPress base URL — the SINGLE source of truth. The admin-config value
    (PlatformConfig WP_URL, editable in the dashboard) WINS; the WP_URL env is only a fallback for
    contexts without a DB. Lets the site URL change from Admin → Config without a redeploy — no
    reliance on .env once the admin value is set."""
    try:
        from app.models import PlatformConfig, PlatformSessionLocal  # noqa: PLC0415
        with PlatformSessionLocal() as pdb:
            pdb.info["platform_scope"] = True
            row = pdb.get(PlatformConfig, "WP_URL")
            if row and (row.value or "").strip():
                return row.value.strip().rstrip("/")
    except Exception:  # noqa: BLE001 — never break a WP call on a config lookup
        pass
    return os.environ.get("WP_URL", "").rstrip("/")


def _base_url() -> str:
    return resolved_wp_url()


@lru_cache(maxsize=8)
def _rest_base_url(configured_base: str) -> str:
    """Return the canonical base host for WordPress REST writes.

    Some GoDaddy staging URLs (for example jhk.14f.myftpupload.com) redirect to a
    different myftpupload.com host. requests intentionally strips Basic Auth on
    cross-host redirects, which makes WordPress Application Password writes fail
    with 401 even though the credential is valid. Resolve the REST root once, then
    send authenticated requests directly to the final host.
    """
    base = configured_base.rstrip("/")
    try:
        resp = requests.get(f"{base}/wp-json/", timeout=10, allow_redirects=True)
        resp.raise_for_status()
    except requests.RequestException:
        return base
    final = resp.url.rstrip("/")
    parsed = urlparse(final)
    if not parsed.scheme or not parsed.netloc:
        return base
    return f"{parsed.scheme}://{parsed.netloc}"


def _wp_api_url(path: str) -> str:
    return urljoin(f"{_rest_base_url(_base_url())}/", path.lstrip("/"))


def _author_id() -> int:
    """WordPress author id for all Perkins posts. Policy: always Tim Kanak (id 3), never the
    API-credential user. Overridable via WP_AUTHOR_ID env if the WP user id ever changes."""
    import os  # noqa: PLC0415
    try:
        return int(os.getenv("WP_AUTHOR_ID", "3"))
    except ValueError:
        return 3


def _rank_math_meta(*, title: str, meta_description: str, focus_keyword: str | None = None) -> dict[str, str]:
    """Rank Math post-meta values written via wp/v2 once registered by our plugin."""
    focus = (focus_keyword or os.getenv("WP_FOCUS_KEYWORD", "")).strip()
    return {
        "rank_math_focus_keyword": focus,
        "rank_math_title": title,
        "rank_math_description": meta_description,
    }


def _post_meta(
    *,
    title: str,
    meta_description: str,
    jsonld: list[dict],
    focus_keyword: str | None = None,
) -> dict[str, str]:
    meta = {"_perkins_jsonld": json.dumps(jsonld)}
    rm = _rank_math_meta(title=title, meta_description=meta_description, focus_keyword=focus_keyword)
    if rm["rank_math_focus_keyword"]:
        meta.update(rm)
    else:
        meta.update({k: v for k, v in rm.items() if k != "rank_math_focus_keyword"})
    return meta


def publish(
    *,
    title: str,
    html: str,
    meta_description: str,
    jsonld: list[dict],
    status: str = "draft",
    focus_keyword: str | None = None,
    slug: str | None = None,
) -> int:
    """Create a WordPress post and return the new post id.

    Args:
        title:            Post title.
        html:             Post body HTML (stored as post content).
        meta_description: Short excerpt / meta description.
        jsonld:           List of schema.org dicts to store as post-meta.
                          Rendered in <head> by the perkins-jsonld mu-plugin.
        status:           WP post status — "draft", "publish", "future", etc.
        slug:             Post permalink. Pass the article's own slug so the WP permalink
                          matches our DB key: the focus keyword is derived FROM that slug, so
                          letting WordPress invent one from the title instead is what makes
                          Rank Math's kw-in-slug judgement disagree with core.seo's.

    Returns:
        Integer post id of the newly created post.

    Raises:
        requests.HTTPError: if the WP REST API returns a non-2xx response.
    """
    url = _wp_api_url("/wp-json/wp/v2/posts")
    payload = {
        "title": title,
        "content": html,
        "status": status,
        "excerpt": meta_description,
        "author": _author_id(),  # policy: always Tim Kanak
        "meta": _post_meta(title=title, meta_description=meta_description, jsonld=jsonld, focus_keyword=focus_keyword),
    }
    if slug:
        payload["slug"] = slug
    resp = requests.post(url, json=payload, auth=_auth(), timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]


def update(
    post_id: int,
    *,
    title: str,
    html: str,
    meta_description: str,
    jsonld: list[dict],
    status: str = "draft",
    focus_keyword: str | None = None,
) -> None:
    """Update an existing WordPress post (PUT /wp-json/wp/v2/posts/{id}).

    Args:
        post_id:          Integer id of the post to update.
        title:            New post title.
        html:             New post body HTML.
        meta_description: New meta description / excerpt.
        jsonld:           Updated JSON-LD list for post-meta.
        status:           New WP post status.

    Raises:
        requests.HTTPError: if the WP REST API returns a non-2xx response.
    """
    url = _wp_api_url(f"/wp-json/wp/v2/posts/{post_id}")
    payload = {
        "title": title,
        "content": html,
        "status": status,
        "excerpt": meta_description,
        "author": _author_id(),  # policy: always Tim Kanak
        "meta": _post_meta(title=title, meta_description=meta_description, jsonld=jsonld, focus_keyword=focus_keyword),
    }
    resp = requests.post(url, json=payload, auth=_auth(), timeout=30)
    resp.raise_for_status()


def update_status(post_id: int, status: str) -> None:
    """Flip the status of an existing WordPress post.

    Used by the promote job to move scheduled drafts to "publish".

    Args:
        post_id: Integer id of the post to update.
        status:  New WP post status (e.g. "publish", "draft").

    Raises:
        requests.HTTPError: if the WP REST API returns a non-2xx response.
    """
    url = _wp_api_url(f"/wp-json/wp/v2/posts/{post_id}")
    resp = requests.post(url, json={"status": status}, auth=_auth(), timeout=30)
    resp.raise_for_status()


def find_page_by_title(title: str) -> int | None:
    """Search WordPress pages for one matching *title* (case-insensitive exact match).

    Returns the page id if found, or None when no match exists.

    Raises:
        requests.HTTPError: if the WP REST API returns a non-2xx response.
    """
    url = _wp_api_url("/wp-json/wp/v2/pages")
    params = {"search": title, "per_page": 20, "status": "any"}
    resp = requests.get(url, params=params, auth=_auth(), timeout=30)
    resp.raise_for_status()
    for page in resp.json():
        raw = page.get("title", {}).get("rendered", "")
        # Strip HTML entities / tags that WP may inject
        import html as _html
        import re as _re
        clean = _re.sub(r"<[^>]+>", "", _html.unescape(raw)).strip()
        if clean.lower() == title.lower():
            return page["id"]
    return None


def create_page(
    *,
    title: str,
    html: str,
    meta_description: str,
    jsonld: list[dict],
    status: str = "publish",
    focus_keyword: str | None = None,
) -> int:
    """Create a WordPress PAGE and return the new page id.

    Args:
        title:            Page title.
        html:             Page body HTML.
        meta_description: Short excerpt / meta description.
        jsonld:           List of schema.org dicts stored as post-meta.
        status:           WP post status — "draft", "publish", etc.

    Returns:
        Integer page id of the newly created page.

    Raises:
        requests.HTTPError: if the WP REST API returns a non-2xx response.
    """
    url = _wp_api_url("/wp-json/wp/v2/pages")
    payload = {
        "title": title,
        "content": html,
        "status": status,
        "excerpt": meta_description,
        "author": _author_id(),  # policy: always Tim Kanak
        "meta": _post_meta(title=title, meta_description=meta_description, jsonld=jsonld, focus_keyword=focus_keyword),
    }
    resp = requests.post(url, json=payload, auth=_auth(), timeout=30)
    resp.raise_for_status()
    return resp.json()["id"]


def update_page(
    page_id: int,
    *,
    title: str,
    html: str,
    meta_description: str,
    jsonld: list[dict],
    status: str = "publish",
    focus_keyword: str | None = None,
) -> None:
    """Update an existing WordPress PAGE.

    Args:
        page_id:          Integer id of the page to update.
        title:            New page title.
        html:             New page body HTML.
        meta_description: New meta description / excerpt.
        jsonld:           Updated JSON-LD list for post-meta.
        status:           New WP post status.

    Raises:
        requests.HTTPError: if the WP REST API returns a non-2xx response.
    """
    url = _wp_api_url(f"/wp-json/wp/v2/pages/{page_id}")
    payload = {
        "title": title,
        "content": html,
        "status": status,
        "excerpt": meta_description,
        "author": _author_id(),  # policy: always Tim Kanak
        "meta": _post_meta(title=title, meta_description=meta_description, jsonld=jsonld, focus_keyword=focus_keyword),
    }
    resp = requests.post(url, json=payload, auth=_auth(), timeout=30)
    resp.raise_for_status()


def trash(post_id: int) -> None:
    """Move a post to the WordPress trash (DELETE /posts/{id}).

    WordPress REST DELETE moves to Trash on the first call; a second call
    permanently deletes. This is intentional — callers (tests, cleanup
    scripts) use a single call, which is safe.

    Args:
        post_id: Integer id of the post to trash.

    Raises:
        requests.HTTPError: if the WP REST API returns a non-2xx response.
    """
    url = _wp_api_url(f"/wp-json/wp/v2/posts/{post_id}")
    resp = requests.delete(url, auth=_auth(), timeout=30)
    resp.raise_for_status()
