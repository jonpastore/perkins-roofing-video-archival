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

# GoDaddy's WAF silently strips Authorization from requests with default library
# User-Agents (curl/*, python-requests/* from datacenter egress) — REST auth then
# 401s "rest_not_logged_in" while the same creds work from a browser. Observed
# 2026-07-23 from Cloud Run; same failure class as the Resend/Cloudflare-1010 UA
# block. Every call sends an explicit product UA.
_session = requests.Session()
_session.headers["User-Agent"] = "perkins-platform/1.0 (+https://perkinsroofing.net)"


def _auth() -> tuple[str, str]:
    user = os.environ["WP_USER"]
    pwd = os.environ["WP_APP_PWD"].replace(" ", "")
    return user, pwd


def resolved_wp_url() -> str:
    """Canonical WordPress base URL — the SINGLE source of truth, from the admin config
    (PlatformConfig WP_URL, editable in the dashboard). NO .env fallback: .env is only a secure
    transport for keys into the vault, never a runtime config source. Returns "" if the admin
    value is unset (callers degrade gracefully — no link / a clear failure, never a stale host)."""
    try:
        from app.models import PlatformConfig, PlatformSessionLocal  # noqa: PLC0415
        with PlatformSessionLocal() as pdb:
            pdb.info["platform_scope"] = True
            row = pdb.get(PlatformConfig, "WP_URL")
            if row and (row.value or "").strip():
                return row.value.strip().rstrip("/")
    except Exception:  # noqa: BLE001 — never break a WP call on a config lookup
        pass
    return ""


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
        resp = _session.get(f"{base}/wp-json/", timeout=10, allow_redirects=True)
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
    category_ids: list[int] | None = None,
    featured_media: int | None = None,
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
    if category_ids:
        payload["categories"] = category_ids
    if featured_media:
        payload["featured_media"] = featured_media
    resp = _session.post(url, json=payload, auth=_auth(), timeout=30)
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
    resp = _session.post(url, json=payload, auth=_auth(), timeout=30)
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
    resp = _session.post(url, json={"status": status}, auth=_auth(), timeout=30)
    resp.raise_for_status()


def find_page_by_title(title: str) -> int | None:
    """Search WordPress pages for one matching *title* (case-insensitive exact match).

    Returns the page id if found, or None when no match exists.

    Raises:
        requests.HTTPError: if the WP REST API returns a non-2xx response.
    """
    url = _wp_api_url("/wp-json/wp/v2/pages")
    params = {"search": title, "per_page": 20, "status": "any"}
    resp = _session.get(url, params=params, auth=_auth(), timeout=30)
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
    resp = _session.post(url, json=payload, auth=_auth(), timeout=30)
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
    resp = _session.post(url, json=payload, auth=_auth(), timeout=30)
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
    resp = _session.delete(url, auth=_auth(), timeout=30)
    resp.raise_for_status()


def push_llms_txt(content: str) -> dict:
    """Push the llms.txt manifest to the perkins-jsonld plugin route
    (POST /wp-json/perkins/v1/llms-txt). The plugin stores it as the
    perkins_llms_txt option AND (best-effort) writes the physical
    /llms.txt file — a pre-existing static file at the webroot shadows
    the WP fallback route, so the file write is what actually updates
    what crawlers see. Returns the plugin's {ok, bytes, file_written}.

    Raises:
        requests.HTTPError: if the WP REST API returns a non-2xx response.
    """
    url = _wp_api_url("/wp-json/perkins/v1/llms-txt")
    resp = _session.post(url, json={"content": content}, auth=_auth(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def upload_media(filename: str, data: bytes, mime: str = "image/jpeg") -> dict:
    """Upload a media file (POST /wp-json/wp/v2/media). Returns the created
    attachment dict — ``source_url`` is the public URL, ``id`` the media id."""
    url = _wp_api_url("/wp-json/wp/v2/media")
    resp = _session.post(
        url,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": mime,
        },
        data=data, auth=_auth(), timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def search_media(term: str, per_page: int = 20) -> list[dict]:
    """Search the media library by filename/title (public REST read, no auth)."""
    url = _wp_api_url("/wp-json/wp/v2/media")
    resp = _session.get(url, params={"search": term, "per_page": per_page}, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Avada Portfolio (extracted from scripts/portfolio_publish.py so the admin
# API route and the CLI script share one implementation — see #384)
# ---------------------------------------------------------------------------

PORTFOLIO_TAXONOMIES = {"category": "portfolio_category", "tags": "portfolio_tags", "skills": "portfolio_skills"}


def _get_or_create_portfolio_term(taxonomy_rest: str, name: str) -> int:
    """Look up an Avada Portfolio taxonomy term by exact (case-insensitive) name,
    creating it if missing."""
    url = _wp_api_url(f"/wp-json/wp/v2/{taxonomy_rest}")
    resp = _session.get(url, auth=_auth(), params={"search": name, "per_page": 100}, timeout=20)
    resp.raise_for_status()
    for term in resp.json():
        if term["name"].strip().lower() == name.strip().lower():
            return term["id"]
    resp = _session.post(url, auth=_auth(), json={"name": name}, timeout=20)
    resp.raise_for_status()
    return resp.json()["id"]


def list_portfolio_posts() -> list[dict]:
    """All avada_portfolio posts (any status) as [{"id", "status", "title"}].
    One fetch for callers that need to match many titles — 13 sequential
    find_portfolio_post searches crawled on a slow WP."""
    url = _wp_api_url("/wp-json/wp/v2/avada_portfolio")
    resp = _session.get(url, auth=_auth(),
                        params={"status": "any", "per_page": 100}, timeout=20)
    resp.raise_for_status()
    return [{"id": p["id"], "status": p["status"],
             "title": p["title"]["rendered"].strip()} for p in resp.json()]


def find_portfolio_post(title: str) -> dict | None:
    """Find an existing avada_portfolio post (any status) by exact (case-insensitive)
    title match. Returns {"id": int, "status": str} or None."""
    url = _wp_api_url("/wp-json/wp/v2/avada_portfolio")
    resp = _session.get(url, auth=_auth(),
                         params={"search": title, "status": "any", "per_page": 100}, timeout=20)
    resp.raise_for_status()
    for post in resp.json():
        if post["title"]["rendered"].strip().lower() == title.strip().lower():
            return {"id": post["id"], "status": post["status"]}
    return None


def publish_portfolio_post(post: dict, *, dry_run: bool = False) -> dict:
    """Create an Avada Portfolio draft from a post payload
    ({title, content, status, category, tags[], skills[]}), or report the existing post if
    one with the same title already exists (idempotent — never creates a duplicate).
    Creates the 3 taxonomy terms (portfolio_category/portfolio_tags/portfolio_skills) on
    first use if missing.
    """
    existing = find_portfolio_post(post["title"])
    if existing:
        return {"title": post["title"], "status": "skipped-exists", "post_id": existing["id"]}

    if dry_run:
        return {"title": post["title"], "status": "dry-run", "category": post["category"],
                 "tags": post["tags"], "skills": post["skills"]}

    term_ids = {"portfolio_category": [
        _get_or_create_portfolio_term(PORTFOLIO_TAXONOMIES["category"], post["category"])
    ]}
    if post["tags"]:
        term_ids["portfolio_tags"] = [
            _get_or_create_portfolio_term(PORTFOLIO_TAXONOMIES["tags"], t) for t in post["tags"]
        ]
    if post["skills"]:
        term_ids["portfolio_skills"] = [
            _get_or_create_portfolio_term(PORTFOLIO_TAXONOMIES["skills"], s) for s in post["skills"]
        ]

    payload = {"title": post["title"], "content": post["content"], "status": post["status"], **term_ids}
    url = _wp_api_url("/wp-json/wp/v2/avada_portfolio")
    resp = _session.post(url, json=payload, auth=_auth(), timeout=30)
    resp.raise_for_status()
    return {"title": post["title"], "status": "created", "post_id": resp.json()["id"]}


@lru_cache(maxsize=1)
def _category_index() -> dict:
    """name(lowercased) -> term id for all post categories (cached per process)."""
    url = _wp_api_url("/wp-json/wp/v2/categories")
    resp = _session.get(url, params={"per_page": 100, "_fields": "id,name"}, timeout=30)
    resp.raise_for_status()
    import html as _html
    return {_html.unescape(c["name"]).strip().lower(): c["id"] for c in resp.json()}


def category_id_for_name(name: str) -> int | None:
    """Resolve a category NAME (core.wp_category output) to its WP term id."""
    return _category_index().get(name.strip().lower())


def featured_media_from_url(image_url: str, filename: str) -> int | None:
    """Download an image (a curated in-video frame) and upload it to the WP media
    library so it can be set as a post's featured image. Returns the media id, or
    None on any failure (a missing featured image must never block publishing)."""
    try:
        r = _session.get(image_url, timeout=30)
        r.raise_for_status()
        media = upload_media(filename, r.content, mime=r.headers.get("Content-Type", "image/jpeg"))
        return media.get("id")
    except Exception:  # noqa: BLE001 — featured image is best-effort
        return None
