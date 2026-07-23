"""THE single source of truth for article compliance — every criterion Wendy
raised, in one place, checked deterministically.

`check_compliance(...)` returns one Criterion per rule with pass/fixable/detail.
The generative loop calls this after applying its deterministic ensures + repair
and MUST NOT emit an article until every criterion passes. Same function backs
the batch validator and the pipeline test, so "compliant" means one thing
everywhere and can't drift.

Pure: regex + reuse of core.seo / core.internal_links. No I/O, no LLM.
"""
import re
from dataclasses import dataclass

from core.internal_links import BASE_URL, matching_service_links
from core.seo import aio_signals, check_tier, rank_math_checks

_YT_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/)|youtu\.be/|img\.youtube\.com/vi/|i\.ytimg\.com/vi/)"
    r"([A-Za-z0-9_-]{11})", re.IGNORECASE)
_HREF_RE = re.compile(r'href="([^"]*)"', re.IGNORECASE)
_H2_RE = re.compile(r"<h2\b", re.IGNORECASE)
_ANCHOR_LINK_RE = re.compile(r'href="#', re.IGNORECASE)
_IMG_SRC_RE = re.compile(r'<img\b[^>]*\bsrc="([^"]+)"', re.IGNORECASE)
_TITLE_CARD_RE = re.compile(r"/(?:hqdefault|maxresdefault|mqdefault|sddefault|default)\.jpg", re.IGNORECASE)
_VIDEO_EMBED_RE = re.compile(
    r"<iframe\b[^>]*\bsrc=[\"'][^\"']*(?:youtube\.com|youtu\.be)", re.IGNORECASE)
_DEAD_HOST_RE = re.compile(r'(?:href|src)="https?://[^"]*(?:myftpupload\.com|jhk\.14f)', re.IGNORECASE)
_SUBSCRIBE_RE = re.compile(r"youtube\.com/@perkinsroofingcorp|UChJZpBYXOuR0j1EHJugv5hg|subscribe",
                           re.IGNORECASE)


@dataclass
class Criterion:
    key: str
    label: str
    ok: bool
    fixable: bool          # True = the loop's deterministic ensures should guarantee it
    detail: str = ""


def _types(jsonld) -> set:
    return {j.get("@type") for j in (jsonld or [])}


def check_compliance(
    content: str,
    meta: str,
    jsonld: list,
    faq: list,
    ctx: dict,
    keyword: str,
    known_video_ids: set,
) -> list[Criterion]:
    """Every Wendy criterion. Order = roughly the order the reader/Wendy cares about."""
    c = content or ""
    hrefs = _HREF_RE.findall(c)
    types = _types(jsonld)
    vids = [v for v in _YT_ID_RE.findall(c)]
    has_known_video = any(v in known_video_ids for v in vids)
    h2_count = len(_H2_RE.findall(c))
    img_srcs = _IMG_SRC_RE.findall(c)
    role = (ctx or {}).get("role")

    out: list[Criterion] = []
    def add(key, label, ok, fixable, detail=""):
        out.append(Criterion(key, label, bool(ok), fixable, detail))

    # ── Schema ────────────────────────────────────────────────────────────
    add("faq_ge4", "FAQ has ≥4 Q&A pairs", len(faq or []) >= 4, True)
    add("faqpage_schema", "FAQPage JSON-LD present", "FAQPage" in types, True)
    add("videoobject_schema", "VideoObject JSON-LD for the source video",
        ("VideoObject" in types) if has_known_video else True, True,
        "" if has_known_video else "no grounded video embedded — N/A")
    stray = types - {"FAQPage", "VideoObject"}
    add("schema_scoped", "Only FAQPage+VideoObject (no Rank Math dup)", not stray, True,
        f"stray schema types: {stray}" if stray else "")

    # ── Video ─────────────────────────────────────────────────────────────
    add("video_embed", "Embedded YouTube player", bool(_VIDEO_EMBED_RE.search(c)),
        True if has_known_video else False,
        "" if vids else "no video to embed (ungrounded)")
    add("valid_video_ids", "All embedded video ids are real/grounded",
        all(v in known_video_ids for v in vids) if vids else True, False,
        f"unknown ids: {[v for v in vids if v not in known_video_ids]}" if vids else "")

    # ── Image (curated, not the title card) ───────────────────────────────
    add("curated_image", "Article image is a real frame, not the title card",
        bool(img_srcs) and not any(_TITLE_CARD_RE.search(s) for s in img_srcs), True,
        "title-card image found" if any(_TITLE_CARD_RE.search(s) for s in img_srcs)
        else ("" if img_srcs else "no image"))

    # ── Internal links ────────────────────────────────────────────────────
    want_services = matching_service_links(f"{keyword} {_plain(c)}")
    have_service = any(BASE_URL in h and "/wp-content/" not in h for h in hrefs) \
        or 'class="related-links"' in c
    add("service_links", "Internal links to relevant service pages",
        have_service if want_services else True, True,
        "no related-links block" if (want_services and not have_service) else "")
    if role == "cluster" and (ctx or {}).get("pillar_slug"):
        pslug = ctx["pillar_slug"]
        add("pillar_link", "Cluster links up to its pillar",
            any(pslug in h for h in hrefs), True)
    add("no_blog", "No /blog/ in any URL (top-level permalinks)",
        not any("/blog/" in h for h in hrefs), True,
        "/blog/ found in a link" if any("/blog/" in h for h in hrefs) else "")
    add("no_dead_hosts", "No dead staging/host links",
        not _DEAD_HOST_RE.search(c), False,
        "staging host link present" if _DEAD_HOST_RE.search(c) else "")

    # ── Structure ─────────────────────────────────────────────────────────
    toc_ok = True if h2_count < 3 else bool(_ANCHOR_LINK_RE.search(c))
    add("toc", "Anchor TOC when ≥3 sections (H2-only)", toc_ok, True,
        "≥3 H2 sections but no anchor TOC" if not toc_ok else "")
    aio = {s["key"]: s["pass"] for s in aio_signals(c)}
    add("answer_first", "Answer-first lede (direct sentence early)",
        aio.get("aio_answer_first", aio.get("answer_first", False)), True)
    add("meta_len", "Meta description 120–160 chars", 120 <= len(meta or "") <= 160, True,
        f"meta is {len(meta or '')} chars")
    add("subscribe_cta", "YouTube subscribe CTA + channel link",
        bool(_SUBSCRIBE_RE.search(c)), True)

    # ── SEO ranking tier (Rank Math) — every ranking-relevant check must pass ─
    rm = rank_math_checks(ctx.get("title", "") or keyword, meta or "",
                          ctx.get("slug", "") or "", c, keyword or "")
    ranking_fails = [x["key"] for x in rm if not x["pass"] and check_tier(x["key"]) == "ranking"]
    add("seo_ranking", "All ranking-tier Rank Math checks pass", not ranking_fails, True,
        f"failing: {ranking_fails}" if ranking_fails else "")
    return out


def _plain(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "")


def failing(criteria: list[Criterion]) -> list[Criterion]:
    return [x for x in criteria if not x.ok]


def is_compliant(criteria: list[Criterion]) -> bool:
    return not failing(criteria)
