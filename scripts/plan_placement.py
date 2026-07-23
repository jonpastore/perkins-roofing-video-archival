"""Content-hub-aware topic plan: embed the existing pillars + candidate topics,
place each candidate (join existing pillar as a cluster vs seed a new pillar) via
core.topic_placement, and emit both a batch plan and a human-readable summary.

  python scripts/plan_placement.py --candidates 200 --threshold 0.72 --out plan.json
"""
import argparse
import json
import re
import sys

sys.path.insert(0, "/home/jon/projects/perkins-roofing/video-archival")
from sqlalchemy import text  # noqa: E402

from adapters.llm import get_embedder  # noqa: E402
from core.topic_placement import place_topics  # noqa: E402
from jobs.article_job import _stamped_session  # noqa: E402


def _kw(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", type=int, default=200)
    ap.add_argument("--threshold", type=float, default=0.72)
    ap.add_argument("--max-clusters", type=int, default=8)
    ap.add_argument("--out", default="/tmp/placement_plan.json")
    args = ap.parse_args()

    with _stamped_session(1) as db:
        pillars = [{"slug": r[0], "keyword": _kw(r[1] or r[0]),
                    "existing_clusters": r[2]}
                   for r in db.execute(text(
                       "SELECT a.slug, a.focus_keyword, "
                       "  (SELECT count(*) FROM articles c WHERE c.pillar_slug=a.slug) "
                       "FROM articles a WHERE a.role='pillar'"))]
        existing_kw = {_kw(r[0]) for r in db.execute(text("SELECT focus_keyword FROM articles"))}
        existing_kw |= {r[0] for r in db.execute(text("SELECT slug FROM articles"))}
        rows = db.execute(text(
            "SELECT canonical_label FROM aggregated_topics WHERE num_videos>=2 "
            "ORDER BY num_videos DESC")).fetchall()

    cands, seen = [], set()
    for (label,) in rows:
        k = _kw(label)
        slug = re.sub(r"[^a-z0-9]+", "-", k).strip("-")
        if not k or k in seen or k in existing_kw or slug in existing_kw:
            continue
        seen.add(k)
        cands.append(k)
        if len(cands) >= args.candidates:
            break

    embed = get_embedder()
    # Embed pillars (use keyword text) + candidates in one batch each.
    p_vecs = embed.embed([p["keyword"] for p in pillars]) if pillars else []
    for p, v in zip(pillars, p_vecs):
        p["vec"] = v
    c_vecs = embed.embed(cands)
    candidates = [{"keyword": k, "vec": v} for k, v in zip(cands, c_vecs)]

    placed = place_topics(pillars, candidates, threshold=args.threshold,
                          max_clusters_per_pillar=args.max_clusters)

    # Batch plan: existing-pillar additions become clusters-only campaigns (pillar
    # already exists so it isn't regenerated); new pillars are full campaigns.
    campaigns = []
    for e in placed["add_to_existing"]:
        campaigns.append({"pillar": e["pillar_keyword"], "existing_pillar_slug": e["pillar_slug"],
                          "regenerate_pillar": False, "clusters": e["clusters"]})
    for np in placed["new_pillars"]:
        campaigns.append({"pillar": np["pillar"], "regenerate_pillar": True,
                          "clusters": np["clusters"]})
    json.dump({"campaigns": campaigns}, open(args.out, "w"), indent=1)

    join = sum(len(e["clusters"]) for e in placed["add_to_existing"])
    newp = len(placed["new_pillars"])
    newc = sum(len(p["clusters"]) for p in placed["new_pillars"])
    print(f"=== PLACEMENT (threshold {args.threshold}) ===")
    print(f"{len(candidates)} candidate topics placed against {len(pillars)} existing pillars:")
    print(f"  -> {join} join an EXISTING pillar as new clusters")
    print(f"  -> {newp} NEW pillars ({newc} clusters under them)")
    print("\nExisting pillars gaining clusters:")
    for e in sorted(placed["add_to_existing"], key=lambda x: -len(x["clusters"]))[:12]:
        print(f"  [{e['pillar_keyword']}] += {', '.join(e['clusters'][:4])}"
              + (" ..." if len(e["clusters"]) > 4 else ""))
    print("\nNew pillars proposed:")
    for np in placed["new_pillars"][:12]:
        print(f"  * {np['pillar']}"
              + (f"  (clusters: {', '.join(np['clusters'][:3])})" if np["clusters"] else "  (no clusters yet)"))
    print(f"\nplan -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
