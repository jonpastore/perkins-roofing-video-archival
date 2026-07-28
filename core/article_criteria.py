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

from core.brand_identity import YOUTUBE_CHANNEL_URL, YOUTUBE_CHANNEL_URL_LEGACY
from core.internal_links import BASE_URL, matching_service_links
from core.seo import aio_signals, check_tier, rank_math_checks

_YT_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/)|youtu\.be/|img\.youtube\.com/vi/|i\.ytimg\.com/vi/)"
    r"([A-Za-z0-9_-]{11})", re.IGNORECASE)
_HREF_RE = re.compile(r'href="([^"]*)"', re.IGNORECASE)
_IMG_SRC_RE = re.compile(r'<img\b[^>]*\bsrc="([^"]+)"', re.IGNORECASE)
_TITLE_CARD_RE = re.compile(r"/(?:hqdefault|maxresdefault|mqdefault|sddefault|default)\.jpg", re.IGNORECASE)
_VIDEO_EMBED_RE = re.compile(
    r"<iframe\b[^>]*\bsrc=[\"'][^\"']*(?:youtube\.com|youtu\.be)", re.IGNORECASE)
_DEAD_HOST_RE = re.compile(r'(?:href|src)="https?://[^"]*(?:myftpupload\.com|jhk\.14f)', re.IGNORECASE)
# Wendy's 2026-07-28 review. These MUST stay in lockstep with the deterministic ensures in
# jobs.article_job (_strip_toc / _ensure_learn_more_links / _ensure_table_borders) — the gate and
# the fix have to agree on the same shape or the loop can never converge.
_TOC_BLOCK_RE = re.compile(r'<div class="toc">.*?</div>', re.IGNORECASE | re.DOTALL)
_LEARN_MORE_P_RE = re.compile(r"<p>\s*Learn more:.*?</p>", re.IGNORECASE | re.DOTALL)
_BARE_TABLE_RE = re.compile(r"<table(?![^>]*\bclass=)[^>]*>", re.IGNORECASE)
_RELATED_BLOCK_RE = re.compile(r'<p class="related-links">.*?</p>', re.IGNORECASE | re.DOTALL)
# Derived from the canonical constant so the two can't drift; www. is optional because both
# forms resolve to the same channel and the LLM writes it either way.
_HANDLE_RE = re.compile(
    re.escape(YOUTUBE_CHANNEL_URL).replace(r"https://www\.", r"https://(?:www\.)?"),
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
    # Google grants VideoObject only to video that is PLAYABLE on the page. Wendy, 2026-07-28:
    # "Google says we can only have video object schema for embedded videos, not links to
    # videos." The 26-gauge post shipped 6 VideoObject nodes against 1 iframe, because the
    # schema builder counted every watch-link and every i.ytimg thumbnail as an "embed".
    n_vo = sum(1 for j in (jsonld or []) if j.get("@type") == "VideoObject")
    n_embeds = len(_VIDEO_EMBED_RE.findall(c))
    add("videoobject_only_embedded", "One VideoObject per EMBEDDED video (never for links)",
        n_vo <= n_embeds, True,
        f"{n_vo} VideoObject vs {n_embeds} embedded player(s)" if n_vo > n_embeds else "")
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
    # Wendy, 2026-07-28: "There is duplication on the related links." Two different keywords can
    # match the SAME service page, and the builder only checked the existing body, so both were
    # appended — /metal-roofing-company/ and /tile-roofing-company/ each shipped twice.
    rl = _RELATED_BLOCK_RE.search(c)
    rl_hrefs = [h.rstrip("/").lower() for h in _HREF_RE.findall(rl.group(0))] if rl else []
    rl_dupes = {h for h in rl_hrefs if rl_hrefs.count(h) > 1}
    add("related_links_unique", "No duplicate links in the related-links block",
        not rl_dupes, True, f"duplicated: {sorted(rl_dupes)}" if rl_dupes else "")

    # ── Structure ─────────────────────────────────────────────────────────
    # REVERSED 2026-07-28. This used to REQUIRE an anchor TOC in the body. Wendy: "The Table of
    # Contents should not be added to the content area, as we have it automated in the side bar.
    # We will only pick up the H2s for the sidebar." Ours duplicated theirs. The <h2 id> anchors
    # stay (their sidebar links to them); only the visible block is banned.
    add("no_toc_block", "No in-content TOC block (the theme sidebar builds it)",
        not _TOC_BLOCK_RE.search(c), True,
        "in-content TOC block found" if _TOC_BLOCK_RE.search(c) else "")

    unlinked_lm = [s for s in _LEARN_MORE_P_RE.findall(c) if "<a " not in s.lower()]
    add("learn_more_linked", "Every 'Learn more:' pointer is an actual link",
        not unlinked_lm, True,
        f"{len(unlinked_lm)} unlinked 'Learn more:' paragraph(s)" if unlinked_lm else "")

    bare_tables = _BARE_TABLE_RE.findall(c)
    add("table_bordered", "Tables carry a visible border", not bare_tables, True,
        f"{len(bare_tables)} table(s) with no class/border" if bare_tables else "")
    add("answer_first", "Answer-first lede (direct declarative sentence in the intro)",
        _has_answer_first_lede(c), True)
    add("meta_len", "Meta description 120–160 chars", 120 <= len(meta or "") <= 160, True,
        f"meta is {len(meta or '')} chars")
    # Must be the @handle, and must NOT still carry the retired channel-ID URL. Wendy,
    # 2026-07-28: "We've updated on live the URL for their YouTube channel. It is now
    # https://www.youtube.com/@perkinsroofingcorp". The old regex also accepted the bare word
    # "subscribe", so an article with no channel link at all passed.
    has_handle = bool(_HANDLE_RE.search(c))          # www. optional — same channel either way
    has_legacy = YOUTUBE_CHANNEL_URL_LEGACY in c or "UChJZpBYXOuR0j1EHJugv5hg" in c
    add("subscribe_cta", "YouTube subscribe CTA links the @perkinsroofingcorp handle",
        has_handle and not has_legacy, True,
        "retired channel/UC... URL present" if has_legacy
        else ("" if has_handle else "no @perkinsroofingcorp channel link"))

    # ── AIO: one gated signal ─────────────────────────────────────────────
    # `aio_question_headings` is the ONE aio_* signal promoted from advisory to gated, because
    # unlike per-section answer-first it is deterministically satisfiable: the FAQ this article
    # already carries (faq_ge4) supplies real question headings, and _ensure_faq_headings
    # renders them as <h3> instead of a <dl>. Every other aio_* signal stays advisory —
    # see core.seo.aio_signals.
    q_heads = [s for s in aio_signals(c) if s["key"] == "aio_question_headings"]
    add("question_heading", "≥1 question-phrased heading (AI/Rank Math extract these)",
        q_heads[0]["pass"] if q_heads else True, True,
        q_heads[0].get("detail", "") if q_heads else "")

    # ── SEO ranking tier (Rank Math) — every ranking-relevant check must pass ─
    rm = rank_math_checks(ctx.get("title", "") or keyword, meta or "",
                          ctx.get("slug", "") or "", c, keyword or "")
    ranking_fails = [x["key"] for x in rm if not x["pass"] and check_tier(x["key"]) == "ranking"]
    add("seo_ranking", "All ranking-tier Rank Math checks pass", not ranking_fails, True,
        f"failing: {ranking_fails}" if ranking_fails else "")
    return out


def _plain(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "")


_ANSWER_FIRST_LEDE_RE = re.compile(r"\w{4,}.*?\.", re.DOTALL)


def _has_answer_first_lede(content: str) -> bool:
    """The first ~200 plain-text chars contain a complete declarative sentence — the exact
    guarantee `jobs.article_job._ensure_answer_first` provides, so the gate criterion matches
    its own label ("answer-first LEDE") and its deterministic ensure. The stricter
    per-section `aio_answer_first` (≥70% of H2s open with 30+ words) stays an ADVISORY signal
    in `core.seo.aio_signals`, consistent with "AIO signals are advisory, never a gate"
    (core.seo) — gating on it made answer_first flake because no ensure (and not even the LLM
    re-refine within the cap) can reliably restructure every section."""
    head = re.sub(r"[#*>`_~\[\]]", " ", re.sub(r"<[^>]+>", " ", content or ""))
    # 300, not 200: a normal declarative opening sentence runs 15-40 words (~250 chars); a tight
    # 200-char window put the terminating period at 201 and missed it, so the ensure kept
    # prepending a duplicate lede. Must match _ensure_answer_first's window.
    head = re.sub(r"\s+", " ", head).strip()[:300]
    return bool(_ANSWER_FIRST_LEDE_RE.search(head))


def failing(criteria: list[Criterion]) -> list[Criterion]:
    return [x for x in criteria if not x.ok]


def is_compliant(criteria: list[Criterion]) -> bool:
    return not failing(criteria)
