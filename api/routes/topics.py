"""Topics routes — pre-mined topic explorer and cluster-article generation.

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto the
main app in api/app.py with ``app.include_router(router)``.

Role requirements (from core.authz):
  - article_read    → sales or admin  (GET /topics)
  - manage_articles → admin only      (POST /topics/generate-article)
"""
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.auth import require_role
from app.models import AggregatedTopic, Article, GraphNode, ScheduledContent, SessionLocal, Video

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/topics", tags=["topics"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    s = text.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s[:80]


def _normalize_label(label: str) -> str:
    """Lowercase + strip for grouping duplicate labels."""
    return label.strip().lower()


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class GenerateArticleRequest(BaseModel):
    topic: str
    pillar_slug: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
def list_topics(
    sort: str = "videos",
    limit: Optional[int] = None,
    offset: int = 0,
    claims=Depends(require_role("article_read")),
):
    """Return distilled topic list — aggregated by semantic similarity when pre-computed.

    When aggregated_topics is populated (run jobs/aggregate_topics.py offline),
    returns the full aggregated set with pagination.  Falls back to live exact-match
    grouping from content_graph when the table is empty (pre-priming safety net).

    Query params:
      - sort:   "videos" (default) | "length" | "alpha"
      - limit:  page size (omit for all)
      - offset: skip first N results (default 0)

    Response:
      {
        "total": int,
        "items": [{label, count, num_videos, total_content_length, sample}]
      }

    The shape of each item is backwards-compatible with the previous flat list so
    the SPA continues to work without changes.
    """
    with SessionLocal() as db:
        # ---- Try aggregated path first ----------------------------------
        agg_count = db.query(AggregatedTopic).count()
        if agg_count > 0:
            return _list_topics_aggregated(db, sort=sort, limit=limit, offset=offset)

        # ---- Fallback: live grouping from content_graph -----------------
        return _list_topics_live(db, sort=sort, limit=limit, offset=offset)


def _sort_key(sort: str):
    if sort == "length":
        return lambda x: x["total_content_length"]
    if sort == "alpha":
        return lambda x: x["label"].lower()
    return lambda x: x["num_videos"]


def _paginate(items: list, limit: Optional[int], offset: int) -> dict:
    total = len(items)
    sliced = items[offset:] if limit is None else items[offset: offset + limit]
    return {"total": total, "items": sliced}


def _list_topics_aggregated(db, sort: str, limit: Optional[int], offset: int) -> dict:
    """Build response from aggregated_topics rows.

    Sorts first, then resolves sample clips for ONLY the requested page — one batched
    GraphNode query instead of one-per-topic (was an N+1 over ~2k rows, the main cause
    of the slow Search-topics load).
    """
    rows = db.query(AggregatedTopic).all()

    items = [
        {
            "label": row.canonical_label,
            "count": row.num_videos,            # backwards-compat alias
            "num_videos": row.num_videos,
            "total_content_length": row.total_seconds,
            "sample": {"video_id": "", "t": 0},
            "_first_node_id": row.node_ids[0] if row.node_ids else None,
            "_first_video_id": row.video_ids[0] if row.video_ids else None,
        }
        for row in rows
    ]

    reverse = sort != "alpha"
    items.sort(key=_sort_key(sort), reverse=reverse)
    page = items[offset:] if limit is None else items[offset: offset + limit]

    # Batch-resolve sample clips for the current page only.
    node_ids = [it["_first_node_id"] for it in page if it["_first_node_id"] is not None]
    node_map = {}
    if node_ids:
        node_map = {
            n.id: n
            for n in db.query(GraphNode).filter(GraphNode.id.in_(node_ids)).all()
        }
    for it in page:
        node = node_map.get(it["_first_node_id"])
        if node:
            it["sample"] = {"video_id": node.video_id, "t": int(node.start or 0)}
        elif it["_first_video_id"]:
            it["sample"] = {"video_id": it["_first_video_id"], "t": 0}
        del it["_first_node_id"]
        del it["_first_video_id"]

    return {"total": len(items), "items": page}


def _list_topics_live(db, sort: str, limit: Optional[int], offset: int) -> dict:
    """Live grouping from content_graph — exact-match fallback (pre-priming)."""
    rows = db.query(GraphNode).filter(GraphNode.kind == "topics").all()

    groups: dict[str, dict] = {}
    for row in rows:
        if not row.label:
            continue
        key = _normalize_label(row.label)
        if key not in groups:
            groups[key] = {
                "label": row.label,
                "video_ids": set(),
                "sample": {"video_id": row.video_id, "t": int(row.start or 0)},
            }
        groups[key]["video_ids"].add(row.video_id)

    all_video_ids = {vid for g in groups.values() for vid in g["video_ids"]}
    duration_map: dict[str, float] = {}
    if all_video_ids:
        vids = db.query(Video).filter(Video.id.in_(list(all_video_ids))).all()
        duration_map = {v.id: (v.duration or 0.0) for v in vids}

    items = [
        {
            "label": g["label"],
            "count": len(g["video_ids"]),
            "num_videos": len(g["video_ids"]),
            "total_content_length": sum(duration_map.get(v, 0.0) for v in g["video_ids"]),
            "sample": g["sample"],
        }
        for g in groups.values()
    ]

    reverse = sort != "alpha"
    items.sort(key=_sort_key(sort), reverse=reverse)
    return _paginate(items, limit, offset)


@router.get("/videos")
def list_topic_videos(label: str, claims=Depends(require_role("article_read"))):
    """Return all source videos for a given topic label.

    When aggregated_topics is populated, looks up the matching aggregate row
    (case-insensitive on canonical_label) and returns its member videos joined
    to the Video table for title + duration.

    Falls back to live content_graph scan when aggregates are absent.

    Returns [{video_id, title, duration, start}] sorted by video title.
    """
    norm = _normalize_label(label)
    with SessionLocal() as db:
        # ---- Try aggregated path ----------------------------------------
        agg_count = db.query(AggregatedTopic).count()
        if agg_count > 0:
            # Find the best-matching aggregate row by normalised canonical_label
            agg_rows = db.query(AggregatedTopic).all()
            match = next(
                (r for r in agg_rows if _normalize_label(r.canonical_label) == norm),
                None,
            )
            if match is None:
                return []

            member_video_ids: list[str] = match.video_ids or []
            if not member_video_ids:
                return []

            # Get earliest start per video_id from the member node_ids
            video_starts: dict[str, float] = {}
            if match.node_ids:
                nodes = (
                    db.query(GraphNode)
                    .filter(GraphNode.id.in_(match.node_ids))
                    .all()
                )
                for node in nodes:
                    t = float(node.start or 0)
                    if node.video_id not in video_starts or t < video_starts[node.video_id]:
                        video_starts[node.video_id] = t

            vids = db.query(Video).filter(Video.id.in_(member_video_ids)).all()
            vid_map = {v.id: v for v in vids}

            result = []
            for vid_id in member_video_ids:
                v = vid_map.get(vid_id)
                result.append({
                    "video_id": vid_id,
                    "title": v.title if v and v.title else vid_id,
                    "duration": v.duration if v and v.duration is not None else 0.0,
                    "start": video_starts.get(vid_id, 0.0),
                })
            result.sort(key=lambda x: x["title"].lower())
            return result

        # ---- Fallback: live content_graph scan --------------------------
        rows = db.query(GraphNode).filter(GraphNode.kind == "topics").all()
        video_starts: dict[str, float] = {}
        for row in rows:
            if not row.label:
                continue
            if _normalize_label(row.label) != norm:
                continue
            vid = row.video_id
            t = float(row.start or 0)
            if vid not in video_starts or t < video_starts[vid]:
                video_starts[vid] = t

        if not video_starts:
            return []

        vids = db.query(Video).filter(Video.id.in_(list(video_starts.keys()))).all()
        vid_map = {v.id: v for v in vids}

        result = []
        for vid_id, start in video_starts.items():
            v = vid_map.get(vid_id)
            result.append({
                "video_id": vid_id,
                "title": v.title if v and v.title else vid_id,
                "duration": v.duration if v and v.duration is not None else 0.0,
                "start": start,
            })
        result.sort(key=lambda x: x["title"].lower())
        return result


@router.post("/generate-article", status_code=201)
def generate_cluster_article(
    body: GenerateArticleRequest,
    claims=Depends(require_role("manage_articles")),
):
    """Generate a content cluster: one pillar article + 4-6 cluster articles with REAL content.

    Each article is generated via the LLM+retrieval pipeline (jobs.article_job.
    generate_article_content) so content_md is finished prose, never a TODO skeleton.
    WordPress publish is skipped — articles are persisted as status='scheduled'.  Use
    POST /articles/{slug}/publish to push any article to WordPress when ready.

    Produces 5-7 total articles (1 pillar + 4-6 clusters).  The refine pass is
    skipped during cluster generation to bound latency; use the reprocess endpoint
    to refine individual articles after the fact.  If a single generation errors,
    a short grounded intro paragraph is substituted so no article is ever left with
    a TODO placeholder.

    Returns:
        {
            "pillar_slug": str,
            "pillar": {"slug": str, "title": str},
            "clusters": [{"slug": str, "title": str}, ...],
            "count": int,
        }

    Idempotent on the pillar slug: if the pillar already exists, the existing
    cluster is returned without creating duplicates.
    """
    topic = body.topic.strip()
    if not topic:
        raise HTTPException(status_code=422, detail="topic must not be empty")

    pillar_slug = _slugify(topic)
    pillar_title = _title_case(topic)

    # Derive 4-6 subtopic titles (target 5-7 total articles including pillar)
    subtopics = _derive_subtopics(topic, pillar_slug)

    with SessionLocal() as db:
        # --- Idempotency: if pillar already exists, return existing cluster ---
        existing_pillar = db.get(Article, pillar_slug)
        if existing_pillar is not None:
            existing_clusters = (
                db.query(Article)
                .filter(
                    Article.pillar_slug == pillar_slug,
                    Article.role == "cluster",
                )
                .all()
            )
            return {
                "pillar_slug": pillar_slug,
                "pillar": {"slug": existing_pillar.slug, "title": existing_pillar.title},
                "clusters": [{"slug": c.slug, "title": c.title} for c in existing_clusters],
                "count": 1 + len(existing_clusters),
            }

        # --- Compute base publish date before generating articles ---
        base_date = _compute_base_publish_date(db)

        # --- Generate pillar content via LLM ---
        pillar_ctx = {
            "keyword": topic,
            "role": "pillar",
            "pillar_slug": pillar_slug,
            "topic": topic,
        }
        pillar_content = _generate_content_with_fallback(topic, pillar_ctx, pillar_title)

        pillar_publish_at = datetime(
            base_date.year, base_date.month, base_date.day, tzinfo=timezone.utc
        ).replace(tzinfo=None)  # store as naive UTC

        pillar_article = Article(
            slug=pillar_slug,
            title=pillar_content["title"],
            meta=pillar_content["meta"] or f"Complete guide to {topic} from Perkins Roofing.",
            content_md=pillar_content["content_md"],
            faq_json=pillar_content["faq_json"] or None,
            jsonld_json=None,
            role="pillar",
            pillar_slug=pillar_slug,
            wp_post_id=None,
            status="scheduled",
            publish_at=pillar_publish_at,
        )
        db.add(pillar_article)

        pillar_sched = ScheduledContent(
            kind="article",
            ref_id=pillar_slug,
            publish_at=pillar_publish_at,
            status="scheduled",
            target="wordpress",
        )
        db.add(pillar_sched)

        # --- Generate cluster articles ---
        created_clusters: list[Article] = []
        seen_slugs: set[str] = {pillar_slug}
        cluster_day_offset = 1  # pillar is base_date; first cluster is base_date+1
        for subtopic in subtopics:
            slug = _unique_slug(subtopic, seen_slugs)
            seen_slugs.add(slug)
            if db.get(Article, slug) is not None:
                continue

            cluster_ctx = {
                "keyword": subtopic,
                "role": "cluster",
                "pillar_slug": pillar_slug,
                "topic": topic,
            }
            cluster_content = _generate_content_with_fallback(
                subtopic, cluster_ctx, _title_case(subtopic)
            )

            cluster_date = base_date + timedelta(days=cluster_day_offset)
            cluster_publish_at = datetime(
                cluster_date.year, cluster_date.month, cluster_date.day
            )  # naive UTC

            cluster = Article(
                slug=slug,
                title=cluster_content["title"],
                meta=cluster_content["meta"] or f"Expert roofing advice on {subtopic} from Perkins Roofing.",
                content_md=cluster_content["content_md"],
                faq_json=cluster_content["faq_json"] or None,
                jsonld_json=None,
                role="cluster",
                pillar_slug=pillar_slug,
                wp_post_id=None,
                status="scheduled",
                publish_at=cluster_publish_at,
            )
            db.add(cluster)
            created_clusters.append(cluster)

            cluster_sched = ScheduledContent(
                kind="article",
                ref_id=slug,
                publish_at=cluster_publish_at,
                status="scheduled",
                target="wordpress",
            )
            db.add(cluster_sched)
            cluster_day_offset += 1

        db.commit()
        db.refresh(pillar_article)
        for c in created_clusters:
            db.refresh(c)

        return {
            "pillar_slug": pillar_slug,
            "pillar": {"slug": pillar_article.slug, "title": pillar_article.title},
            "clusters": [{"slug": c.slug, "title": c.title} for c in created_clusters],
            "count": 1 + len(created_clusters),
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _title_case(s: str) -> str:
    return " ".join(w.capitalize() for w in s.split())


def _unique_slug(text: str, seen: set[str]) -> str:
    """Return a slug for *text* that doesn't collide with *seen*."""
    base = _slugify(text)
    if base not in seen:
        return base
    n = 2
    while f"{base}-{n}" in seen and n < 20:
        n += 1
    return f"{base}-{n}"


def _derive_subtopics(topic: str, pillar_slug: str) -> list[str]:
    """Derive 4–6 cluster subtopic titles for *topic* (so total = 5–7 incl. pillar).

    Strategy:
      1. Query content_graph for topic-kind labels that contain the topic
         keyword — these are real terms from Tim's videos.
      2. Exclude the topic itself (it becomes the pillar).
      3. If fewer than 4 related labels found, first pad with domain-specific
         hard-coded fallbacks; if still fewer than 4, call the LLM once to
         generate the remaining titles so we always produce a complete cluster.
    """
    related: list[str] = []
    topic_lower = topic.lower()
    try:
        with SessionLocal() as db:
            rows = (
                db.query(GraphNode.label)
                .filter(GraphNode.kind == "topics")
                .all()
            )
            seen_norm: set[str] = {_normalize_label(topic)}
            for (label,) in rows:
                if not label:
                    continue
                norm = _normalize_label(label)
                if norm in seen_norm:
                    continue
                # Include if the label overlaps with the topic keyword
                if topic_lower in norm or any(
                    word in norm for word in topic_lower.split() if len(word) > 3
                ):
                    seen_norm.add(norm)
                    related.append(label.strip())
                if len(related) >= 6:
                    break
    except Exception:  # noqa: BLE001
        pass  # DB not available in all test contexts — fall through to fallbacks

    # Pad with hard-coded domain fallbacks first (free, deterministic)
    if len(related) < 4:
        fallbacks = _fallback_subtopics(topic)
        for fb in fallbacks:
            norm = _normalize_label(fb)
            if norm not in {_normalize_label(r) for r in related}:
                related.append(fb)
            if len(related) >= 6:
                break

    # If still fewer than 4, call the LLM once to generate remaining titles
    if len(related) < 4:
        needed = 6 - len(related)
        llm_titles = _llm_subtopics(topic, related, needed)
        seen_norm_final = {_normalize_label(r) for r in related}
        for t in llm_titles:
            norm = _normalize_label(t)
            if norm not in seen_norm_final:
                seen_norm_final.add(norm)
                related.append(t)
            if len(related) >= 6:
                break

    return related[:6]


def _llm_subtopics(topic: str, existing: list[str], needed: int) -> list[str]:
    """Ask the LLM to generate *needed* distinct cluster article titles for *topic*.

    Returns a list of title strings (may be empty on any error — caller pads with
    what it already has, so a failure here never blocks article creation).
    """
    try:
        from app.llm import chat  # noqa: PLC0415
        existing_str = "\n".join(f"- {e}" for e in existing) if existing else "(none yet)"
        prompt = (
            f"You are helping plan a roofing content cluster for a local roofing contractor.\n\n"
            f"PILLAR TOPIC: {topic}\n\n"
            f"Already have these cluster article titles:\n{existing_str}\n\n"
            f"Generate exactly {needed} additional distinct cluster article titles that cover "
            f"different specific angles of \"{topic}\" suitable for a roofing business blog. "
            f"Each title should be concrete, specific, and different from the existing titles.\n\n"
            f"Return ONLY a JSON array of {needed} title strings, no other text:\n"
            f'["Title 1", "Title 2", ...]'
        )
        result = chat(prompt, want_json=False)
        # Extract JSON array from the response
        import json as _json  # noqa: PLC0415
        a, b = result.find("["), result.rfind("]")
        if a != -1 and b != -1:
            titles = _json.loads(result[a : b + 1])
            if isinstance(titles, list):
                return [str(t).strip() for t in titles if t and str(t).strip()]
    except Exception:  # noqa: BLE001
        pass
    return []


# Hard-coded roofing-domain subtopic patterns keyed by common keywords.
# Used only when content_graph yields too few related labels.
_ROOFING_SUBTOPIC_PATTERNS: list[tuple[list[str], list[str]]] = [
    (
        ["metal", "standing seam", "steel", "aluminum"],
        [
            "{topic} cost and pricing",
            "{topic} installation process",
            "{topic} pros and cons",
            "{topic} vs shingles",
        ],
    ),
    (
        ["shingle", "asphalt", "architectural"],
        [
            "{topic} lifespan and durability",
            "{topic} installation tips",
            "{topic} repair guide",
            "how to choose {topic}",
        ],
    ),
    (
        ["flat", "tpo", "epdm", "rubber", "membrane"],
        [
            "{topic} repair options",
            "{topic} drainage requirements",
            "{topic} cost breakdown",
            "{topic} maintenance guide",
        ],
    ),
    (
        ["repair", "leak", "damage", "fix"],
        [
            "signs you need {topic}",
            "emergency {topic} steps",
            "{topic} cost guide",
            "DIY vs professional {topic}",
        ],
    ),
    (
        ["gutter", "drainage", "downspout"],
        [
            "{topic} cleaning schedule",
            "{topic} installation guide",
            "{topic} guard options",
            "signs of {topic} problems",
        ],
    ),
]

_GENERIC_SUBTOPICS = [
    "{topic} cost and pricing",
    "{topic} installation guide",
    "{topic} maintenance tips",
    "signs you need {topic} service",
]


def _fallback_subtopics(topic: str) -> list[str]:
    """Return domain-keyed fallback subtopics for *topic*."""
    topic_lower = topic.lower()
    for keywords, patterns in _ROOFING_SUBTOPIC_PATTERNS:
        if any(kw in topic_lower for kw in keywords):
            return [p.format(topic=topic) for p in patterns]
    return [p.format(topic=topic) for p in _GENERIC_SUBTOPICS]


def _generate_content_with_fallback(keyword: str, ctx: dict, display_title: str) -> dict:
    """Call generate_article_content (single pass) and return finished prose.

    The refine pass is intentionally skipped here to bound latency when generating
    5-7 articles in one request.  Refinement remains available via the reprocess
    endpoint for individual articles after the fact.

    Never returns a TODO placeholder.  The fallback is real prose derived from the
    keyword and topic so the article is at minimum a finished stub the editor can expand.
    """
    try:
        from jobs.article_job import generate_article_content, sanitize_article_html  # noqa: PLC0415
        fields = generate_article_content(keyword, ctx)
        # Sanitize so no markdown artifacts ship
        fields = dict(fields)
        fields["content_md"] = sanitize_article_html(fields.get("content_md") or "")
        return fields
    except Exception as exc:  # noqa: BLE001
        logger.warning("generate_article_content failed for %r, using fallback: %s", keyword, exc)
        topic = ctx.get("topic") or keyword
        role = ctx.get("role", "standalone")
        pillar_slug = ctx.get("pillar_slug") or ""
        if role == "cluster" and pillar_slug:
            back_link = f"\n\nFor a full overview, see [our complete guide to {topic}](/blog/{pillar_slug}).\n"
        else:
            back_link = ""
        content_md = (
            f"# {display_title}\n\n"
            f"Perkins Roofing has worked on {keyword} projects throughout the region. "
            f"This page covers what homeowners need to know about {keyword}, "
            f"including costs, timelines, and what to look for when hiring a contractor."
            f"{back_link}"
        )
        return {
            "title": display_title,
            "slug": _slugify(display_title),
            "meta": f"Expert advice on {keyword} from Perkins Roofing.",
            "content_md": content_md,
            "faq_json": [],
        }


def _compute_base_publish_date(db) -> date:
    """Compute the base publish date: day after the latest scheduled/published article.

    Priority:
      1. Day after max ScheduledContent.publish_at (any kind)
      2. Day after max Article.publish_at where status='published'
      3. Tomorrow (UTC)
    """
    from sqlalchemy import func  # noqa: PLC0415

    max_sched = db.query(func.max(ScheduledContent.publish_at)).scalar()
    if max_sched is not None:
        if isinstance(max_sched, str):
            max_sched = datetime.fromisoformat(max_sched)
        return max_sched.date() + timedelta(days=1)

    max_pub = (
        db.query(func.max(Article.publish_at))
        .filter(Article.status == "published")
        .scalar()
    )
    if max_pub is not None:
        if isinstance(max_pub, str):
            max_pub = datetime.fromisoformat(max_pub)
        return max_pub.date() + timedelta(days=1)

    return date.today() + timedelta(days=1)
