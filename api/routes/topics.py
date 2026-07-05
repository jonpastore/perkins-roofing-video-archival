"""Topics routes — pre-mined topic explorer and cluster-article generation.

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto the
main app in api/app.py with ``app.include_router(router)``.

Role requirements (from core.authz):
  - article_read    → sales or admin  (GET /topics)
  - manage_articles → admin only      (POST /topics/generate-article)
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from typing import Optional

from api.auth import require_role
from app.models import Article, GraphNode, SessionLocal

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
def list_topics(claims=Depends(require_role("article_read"))):
    """Return the top 150 mined topics from content_graph, grouped by normalized label.

    Each entry includes:
      - label: the most common casing of this topic label
      - count: number of distinct videos that mention it
      - sample: {video_id, t} for a jump-to-timecode link
    """
    with SessionLocal() as db:
        # Fetch all topic rows (kind='topics') — group in Python for SQLite compat
        rows = (
            db.query(GraphNode)
            .filter(GraphNode.kind == "topics")
            .all()
        )

        # Group by normalized label
        groups: dict[str, dict] = {}
        for row in rows:
            if not row.label:
                continue
            key = _normalize_label(row.label)
            if key not in groups:
                groups[key] = {
                    "label": row.label,         # keep first-seen casing
                    "video_ids": set(),
                    "sample": {"video_id": row.video_id, "t": int(row.start or 0)},
                }
            groups[key]["video_ids"].add(row.video_id)

        # Sort by distinct-video count desc, cap at 150
        result = sorted(
            [
                {
                    "label": g["label"],
                    "count": len(g["video_ids"]),
                    "sample": g["sample"],
                }
                for g in groups.values()
            ],
            key=lambda x: x["count"],
            reverse=True,
        )[:150]

        return result


@router.post("/generate-article", status_code=201)
def generate_cluster_article(
    body: GenerateArticleRequest,
    claims=Depends(require_role("manage_articles")),
):
    """Generate a cluster article draft for a pre-mined topic.

    Approach: synchronous seeded-draft (not the full SERP+LLM pipeline).
    Running the full generate_article() pipeline synchronously in a request
    would require live Vertex AI + WordPress adapters and could take 30–60 s.
    Instead, we create a real Article row (role='cluster', status='draft')
    with a generated outline as content_md — a working draft that the editor
    can enrich or that a background job can fill in with the full pipeline.
    The slug is derived from the topic string.
    """
    topic = body.topic.strip()
    if not topic:
        raise HTTPException(status_code=422, detail="topic must not be empty")

    slug = _slugify(topic)
    pillar_slug = body.pillar_slug or None

    # Build a minimal outline-style draft so the article has real content
    outline_md = _build_outline(topic, pillar_slug)

    with SessionLocal() as db:
        existing = db.get(Article, slug)
        if existing is not None:
            # Return the existing draft rather than erroring — idempotent
            return {
                "slug": existing.slug,
                "title": existing.title,
                "role": existing.role,
                "status": existing.status,
            }

        article = Article(
            slug=slug,
            title=_title_case(topic),
            meta=f"Expert roofing advice on {topic} from Perkins Roofing.",
            content_md=outline_md,
            faq_json=None,
            jsonld_json=None,
            role="cluster",
            pillar_slug=pillar_slug,
            wp_post_id=None,
            status="draft",
            publish_at=None,
        )
        db.add(article)
        db.commit()
        db.refresh(article)

        return {
            "slug": article.slug,
            "title": article.title,
            "role": article.role,
            "status": article.status,
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _title_case(s: str) -> str:
    return " ".join(w.capitalize() for w in s.split())


def _build_outline(topic: str, pillar_slug: Optional[str]) -> str:
    """Return a markdown outline scaffold for a cluster article on *topic*."""
    pillar_link = (
        f"\n\nFor the complete guide, see [our overview](blog/{pillar_slug}).\n"
        if pillar_slug
        else ""
    )
    return (
        f"# {_title_case(topic)}\n"
        f"{pillar_link}\n"
        "## What You Need to Know\n\n"
        "<!-- TODO: Answer the searcher's question directly in 2-3 sentences. -->\n\n"
        "## Key Points\n\n"
        "- <!-- Point 1 -->\n"
        "- <!-- Point 2 -->\n"
        "- <!-- Point 3 -->\n\n"
        "## Detailed Explanation\n\n"
        "<!-- TODO: Go deep on this specific aspect. Reference Tim's videos with timecodes. -->\n\n"
        "## Common Questions\n\n"
        "<!-- TODO: FAQ section (4-6 Q&As). -->\n\n"
        "## Next Steps\n\n"
        "<!-- TODO: CTA paragraph. -->\n"
    )
