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

import requests


def _auth() -> tuple[str, str]:
    user = os.environ["WP_USER"]
    pwd = os.environ["WP_APP_PWD"].replace(" ", "")
    return user, pwd


def _base_url() -> str:
    return os.environ["WP_URL"].rstrip("/")


def publish(
    *,
    title: str,
    html: str,
    meta_description: str,
    jsonld: list[dict],
    status: str = "draft",
) -> int:
    """Create a WordPress post and return the new post id.

    Args:
        title:            Post title.
        html:             Post body HTML (stored as post content).
        meta_description: Short excerpt / meta description.
        jsonld:           List of schema.org dicts to store as post-meta.
                          Rendered in <head> by the perkins-jsonld mu-plugin.
        status:           WP post status — "draft", "publish", "future", etc.

    Returns:
        Integer post id of the newly created post.

    Raises:
        requests.HTTPError: if the WP REST API returns a non-2xx response.
    """
    url = f"{_base_url()}/wp-json/wp/v2/posts"
    payload = {
        "title": title,
        "content": html,
        "status": status,
        "excerpt": meta_description,
        "meta": {"_perkins_jsonld": json.dumps(jsonld)},
    }
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
    url = f"{_base_url()}/wp-json/wp/v2/posts/{post_id}"
    payload = {
        "title": title,
        "content": html,
        "status": status,
        "excerpt": meta_description,
        "meta": {"_perkins_jsonld": json.dumps(jsonld)},
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
    url = f"{_base_url()}/wp-json/wp/v2/posts/{post_id}"
    resp = requests.post(url, json={"status": status}, auth=_auth(), timeout=30)
    resp.raise_for_status()


def find_page_by_title(title: str) -> int | None:
    """Search WordPress pages for one matching *title* (case-insensitive exact match).

    Returns the page id if found, or None when no match exists.

    Raises:
        requests.HTTPError: if the WP REST API returns a non-2xx response.
    """
    url = f"{_base_url()}/wp-json/wp/v2/pages"
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
    url = f"{_base_url()}/wp-json/wp/v2/pages"
    payload = {
        "title": title,
        "content": html,
        "status": status,
        "excerpt": meta_description,
        "meta": {"_perkins_jsonld": json.dumps(jsonld)},
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
    url = f"{_base_url()}/wp-json/wp/v2/pages/{page_id}"
    payload = {
        "title": title,
        "content": html,
        "status": status,
        "excerpt": meta_description,
        "meta": {"_perkins_jsonld": json.dumps(jsonld)},
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
    url = f"{_base_url()}/wp-json/wp/v2/posts/{post_id}"
    resp = requests.delete(url, auth=_auth(), timeout=30)
    resp.raise_for_status()
