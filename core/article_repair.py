"""Deterministic article repair + QA pass — the generative-loop version of the
one-off 2026-07-22 correction scripts (backfill_videoobject.py, fix_images.py,
link_repair.py, fix_3ids.py, second_pass.py). PURE module: no I/O, no DB, no
network — every fact it needs (known video ids/metadata, valid slugs, the
pillar map) is passed in by the caller. jobs.article_job wires it to the DB.

Issue dicts use the same shape as jobs.article_job's qa_checks entries
(``{"name", "severity", "details"}`` — verified against the live convention,
not the older ``{"check", ...}`` some docs describe) so callers can just
``qa_checks.extend(result.issues)``.

Passes: (a) video ids, (b) images, (c) dead relative links, (d) dead staging
hosts, (e) VideoObject jsonld sync, (f) service links, (g) TOC entries must
target an <h2>, never an <h3>.

Every pass is idempotent: repair_article(repair_article(x)) == repair_article(x).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from core.internal_links import BASE_URL, matching_service_links
from core.jsonld import build_video_object

# Any YouTube id reference: watch?v=, /embed/, youtu.be/, and both thumbnail hosts.
# Deliberately NOT anchored to 11 chars — a corrupted id can be a different length
# than the real one it was typo'd from (a wrong length is always corrupt, see
# _repair_video_ids).
_YT_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/)|youtu\.be/|img\.youtube\.com/vi/|i\.ytimg\.com/vi/)"
    r"([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_IMG_SRC_RE = re.compile(r'src="([^"]+)"')
_YT_THUMB_RE = re.compile(r"(?:img\.youtube\.com|i\.ytimg\.com)/vi/([^/]+)/")

_REL_A_RE = re.compile(
    r'<a\s[^>]*href="(/[a-z0-9][a-z0-9-]*)/?(?:#[^"]*)?"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)

_MYFTP_RE = re.compile(r'(href|src)="https?://[^/"]*\.myftpupload\.com(/[^"]*)?"', re.IGNORECASE)

_VIDEO_URL_ID_RE = re.compile(r"v=([A-Za-z0-9_-]{11})")

# TOC shape built by core.seo.ensure_toc: <li><a href="#slug">text</a></li> per <h2 id="slug">.
_TOC_LI_RE = re.compile(r'<li><a href="#([^"]+)">.*?</a></li>', re.IGNORECASE | re.DOTALL)
_TOC_EMPTY_RE = re.compile(
    r'<div class="toc"><p><strong>In This Article</strong></p><ul></ul></div>\n?',
    re.IGNORECASE)
_H3_ID_RE = re.compile(r'<h3\b[^>]*\bid="([^"]+)"', re.IGNORECASE)

_FUZZY_MIN_RATIO = 0.85


@dataclass
class RepairResult:
    content_md: str
    jsonld: list[dict]
    fixes: list[str] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)


def _title_case(keyword: str) -> str:
    return " ".join(w.capitalize() for w in keyword.split())


def _iso_duration(seconds) -> str:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "PT0S"
    return f"PT{s // 60}M{s % 60}S"


def _fuzzy_match_id(vid: str, known_ids: set[str]) -> str | None:
    """Best known id for a possibly-corrupted one, or None below the ratio floor.

    Real YouTube ids are always 11 chars, so every candidate in known_ids already
    satisfies the "length 11" half of the spec — the ratio is the only live gate.
    """
    best_id, best_ratio = None, 0.0
    for kid in known_ids:
        ratio = difflib.SequenceMatcher(None, vid, kid).ratio()
        if ratio > best_ratio:
            best_ratio, best_id = ratio, kid
    return best_id if best_ratio >= _FUZZY_MIN_RATIO else None


def _strip_video_id_refs(content: str, vid: str) -> str:
    """Remove every element that cites an uncorrectable video id.

    Unwraps <a> citation links to their text, drops the iframe (and its
    video-embed wrapper div, per jobs.article_job._ensure_video_link's shape),
    drops <img> thumbnails, and drops a bare oEmbed URL line.
    """
    v = re.escape(vid)
    content = re.sub(
        rf'<a\b[^>]*href="[^"]*{v}[^"]*"[^>]*>(.*?)</a>', r"\1",
        content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(
        rf'<div class="video-embed"[^>]*>\s*<iframe\b[^>]*src="[^"]*{v}[^"]*"[^>]*>.*?</iframe>\s*</div>',
        "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(
        rf'<iframe\b[^>]*src="[^"]*{v}[^"]*"[^>]*>.*?</iframe>',
        "", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(
        rf'<img\b[^>]*src="[^"]*{v}[^"]*"[^>]*/?>', "", content, flags=re.IGNORECASE)
    content = re.sub(
        rf'^[ \t]*https?://(?:www\.)?(?:youtube\.com/(?:watch\?v=|embed/)|youtu\.be/)\S*{v}\S*[ \t]*\n?',
        "", content, flags=re.IGNORECASE | re.MULTILINE)
    return content


def _repair_video_ids(content: str, known_ids: set[str]) -> tuple[str, list[str], list[dict]]:
    fixes: list[str] = []
    issues: list[dict] = []
    for vid in dict.fromkeys(_YT_ID_RE.findall(content)):
        if vid in known_ids:
            continue
        match = _fuzzy_match_id(vid, known_ids)
        if match:
            content = content.replace(vid, match)
            fixes.append(f"corrected corrupted video id {vid!r} -> {match!r}")
        else:
            content = _strip_video_id_refs(content, vid)
            fixes.append(f"stripped unrecognized video id {vid!r}")
            issues.append({
                "name": "unknown_video_id",
                "severity": "warn",
                "details": f"video id {vid!r} not recognized and not a fuzzy match to any "
                           f"known video — stripped from content",
            })
    return content, fixes, issues


def _embedded_known_ids(content: str, known_ids: set[str]) -> list[str]:
    """Distinct known video ids still referenced in content, in first-seen order."""
    out: list[str] = []
    for vid in _YT_ID_RE.findall(content or ""):
        if vid in known_ids and vid not in out:
            out.append(vid)
    return out


def _image_allowed(src: str, known_ids: set[str]) -> bool:
    m = _YT_THUMB_RE.search(src)
    if m:
        return m.group(1) in known_ids
    return src.startswith("/wp-content/")


def _thumb_img_tag(vid: str, keyword: str) -> str:
    """Same tag shape as jobs.article_job._ensure_article_image — replicated here
    (pure) rather than imported, since this module must not import from jobs."""
    alt = _title_case(keyword) if keyword else "Perkins Roofing"
    return (f'<img src="https://img.youtube.com/vi/{vid}/hqdefault.jpg" '
            f'alt="{alt} — Perkins Roofing" loading="lazy" '
            f'style="max-width:100%;height:auto;border-radius:8px;margin:16px 0" />')


def _repair_images(content: str, known_ids: set[str], keyword: str) -> tuple[str, list[str]]:
    fixes: list[str] = []

    def _sub(m: re.Match) -> str:
        tag = m.group(0)
        s = _IMG_SRC_RE.search(tag)
        if s and not _image_allowed(s.group(1), known_ids):
            fixes.append(f"stripped invalid image src {s.group(1)!r}")
            return ""
        return tag

    out = _IMG_RE.sub(_sub, content)
    if fixes and not _IMG_RE.search(out):
        embedded = _embedded_known_ids(out, known_ids)
        if embedded:
            out = f"{_thumb_img_tag(embedded[0], keyword)}\n{out}"
            fixes.append(f"re-added real thumbnail for video {embedded[0]!r}")
    return out, fixes


def _tidy_related_links(content: str) -> str:
    content = re.sub(
        r'(<p class="related-links">Related: )(.*?)(</p>)',
        lambda m: m.group(1) + " | ".join(
            seg for seg in (s.strip() for s in m.group(2).split("|")) if "<a " in seg
        ) + m.group(3),
        content, flags=re.DOTALL)
    return re.sub(r'<p class="related-links">Related: ?</p>\n?', "", content)


def _repair_relative_links(
    content: str, valid_slugs: set[str], pillar_map: dict[str, str],
) -> tuple[str, list[str]]:
    fixes: list[str] = []

    def _sub(m: re.Match) -> str:
        path, text = m.group(1).lstrip("/"), m.group(2)
        if path in valid_slugs:
            return m.group(0)
        if path in pillar_map:
            fixes.append(f"rewrote dead link /{path} -> /{pillar_map[path]}/")
            # Prefix replace only (no trailing slash forced on): preserves whatever the
            # original href had after the slug — trailing slash, #fragment, or neither.
            return m.group(0).replace(f'"/{path}', f'"/{pillar_map[path]}')
        fixes.append(f"unwrapped dead link /{path}")
        return text

    out = _REL_A_RE.sub(_sub, content)
    out = _tidy_related_links(out)
    return out, fixes


def _repair_dead_hosts(content: str) -> tuple[str, list[str]]:
    fixes: list[str] = []

    def _sub(m: re.Match) -> str:
        path = m.group(2) or "/"
        fixes.append(f"rewrote staging host link -> {path}")
        return f'{m.group(1)}="{path}"'

    out = _MYFTP_RE.sub(_sub, content)
    return out, fixes


def _sync_video_jsonld(
    content: str,
    jsonld: list[dict],
    known_ids: set[str],
    video_meta: dict[str, dict],
    meta_description: str,
) -> tuple[list[dict], list[str], list[dict]]:
    fixes: list[str] = []
    issues: list[dict] = []

    kept = [n for n in jsonld if not (isinstance(n, dict) and n.get("@type") == "VideoObject")]
    old_ids = set()
    for n in jsonld:
        if isinstance(n, dict) and n.get("@type") == "VideoObject":
            m = _VIDEO_URL_ID_RE.search(n.get("contentUrl", "") or "")
            if m:
                old_ids.add(m.group(1))

    embedded = _embedded_known_ids(content, known_ids)
    new_nodes = []
    new_ids = set()
    for vid in embedded:
        meta = video_meta.get(vid)
        if not meta:
            issues.append({
                "name": "video_metadata_missing",
                "severity": "warn",
                "details": f"video {vid!r} is embedded but has no metadata — VideoObject not built",
            })
            continue
        new_ids.add(vid)
        new_nodes.append(build_video_object(
            title=meta.get("title") or "",
            description=(meta_description or meta.get("title") or "")[:300],
            thumbnail_url=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            upload_date=str(meta.get("upload_date") or "")[:10],
            content_url=f"https://www.youtube.com/watch?v={vid}",
            embed_url=f"https://www.youtube.com/embed/{vid}",
            duration_iso=_iso_duration(meta.get("duration")),
        ))

    if old_ids != new_ids:
        fixes.append(f"resynced VideoObject jsonld: {sorted(old_ids)} -> {sorted(new_ids)}")
    return kept + new_nodes, fixes, issues


def _repair_toc_h2_only(content: str) -> tuple[str, list[str]]:
    """A TOC entry must only ever target an <h2> id — never an <h3>.

    ensure_toc (core.seo) only ever builds entries for <h2>, but a hand-authored
    or LLM-produced TOC could target a sub-heading; drop any entry whose anchor
    resolves to an <h3> id, and the whole TOC block if that empties it out.
    """
    fixes: list[str] = []
    h3_ids = set(_H3_ID_RE.findall(content))
    if not h3_ids:
        return content, fixes

    def _sub(m: re.Match) -> str:
        if m.group(1) in h3_ids:
            fixes.append(f"dropped TOC entry targeting h3 #{m.group(1)!r}")
            return ""
        return m.group(0)

    out = _TOC_LI_RE.sub(_sub, content)
    out = _TOC_EMPTY_RE.sub("", out)
    return out, fixes


def _append_service_links(content: str, keyword: str) -> tuple[str, list[str], list[dict]]:
    fixes: list[str] = []
    issues: list[dict] = []
    if f"{BASE_URL}/" in content:
        return content, fixes, issues

    text = re.sub(r"<[^>]+>", " ", content or "")
    matches = matching_service_links(f"{keyword} {text}")
    if not matches:
        issues.append({
            "name": "service_links_no_match",
            "severity": "info",
            "details": "no perkinsroofing.net service link present and no keyword match found",
        })
        return content, fixes, issues

    links = [f'<a href="{m["url"]}">{m["anchor"]}</a>' for m in matches]
    block = f'<p class="related-links">Related: {" | ".join(links)}</p>'
    fixes.append(f"appended {len(links)} service link(s)")
    return f"{content}\n{block}", fixes, issues


def _wp_field_issues(category_id: int | None, has_featured_image: bool | None) -> list[dict]:
    """Publisher-side (wp_post, not content_md) checks — reporting only, never a fix: this
    module never writes to WordPress. None means "caller doesn't know" -> emit nothing."""
    issues: list[dict] = []
    if category_id == 1:
        issues.append({
            "name": "wp_default_category", "severity": "warn",
            "details": "post is in the default category bucket, not a real one",
        })
    if has_featured_image is False:
        issues.append({
            "name": "wp_missing_featured_image", "severity": "warn",
            "details": "post has no featured image set",
        })
    return issues


def repair_article(
    content_md: str,
    jsonld: list[dict],
    *,
    known_video_ids: set[str],
    video_meta: dict[str, dict],
    valid_slugs: set[str],
    pillar_map: dict[str, str],
    keyword: str,
    meta_description: str,
    category_id: int | None = None,
    has_featured_image: bool | None = None,
) -> RepairResult:
    """Run every repair pass, in order, over one article's content + jsonld.

    category_id/has_featured_image are optional WP-post facts a caller may pass for
    reporting only (see _wp_field_issues) — this module never touches WordPress.
    """
    content = content_md or ""
    jsonld_list = list(jsonld or [])
    fixes: list[str] = []
    issues: list[dict] = []

    content, f1, i1 = _repair_video_ids(content, known_video_ids)
    fixes += f1
    issues += i1

    content, f2 = _repair_images(content, known_video_ids, keyword)
    fixes += f2

    content, f3 = _repair_relative_links(content, valid_slugs, pillar_map)
    fixes += f3

    content, f4 = _repair_dead_hosts(content)
    fixes += f4

    jsonld_list, f5, i5 = _sync_video_jsonld(
        content, jsonld_list, known_video_ids, video_meta, meta_description)
    fixes += f5
    issues += i5

    content, f6, i6 = _append_service_links(content, keyword)
    fixes += f6
    issues += i6

    content, f7 = _repair_toc_h2_only(content)
    fixes += f7

    issues += _wp_field_issues(category_id, has_featured_image)

    return RepairResult(content_md=content, jsonld=jsonld_list, fixes=fixes, issues=issues)
