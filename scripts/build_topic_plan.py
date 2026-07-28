"""Build a batch topic plan (N pillars + M clusters each) from the best-grounded
aggregated_topics, skipping topics that already have an article. Emits JSON for
jobs.batch_article_job.

  python scripts/build_topic_plan.py --pillars 100 --clusters 2 --out plan.json
"""
import argparse
import json
import re
import sys

sys.path.insert(0, "/home/jon/projects/perkins-roofing/video-archival")
from sqlalchemy import text  # noqa: E402

from jobs.article_job import _stamped_session  # noqa: E402


def _kw(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip().lower())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pillars", type=int, default=100)
    ap.add_argument("--clusters", type=int, default=2)
    ap.add_argument("--out", default="/tmp/topic_plan.json")
    args = ap.parse_args()

    need = args.pillars * (1 + args.clusters)
    with _stamped_session(1) as db:
        existing = {(_kw(r[0]) if r[0] else "") for r in
                    db.execute(text("SELECT focus_keyword FROM articles"))}
        existing |= {r[0] for r in db.execute(text("SELECT slug FROM articles"))}
        # Best-grounded first; ≥2 videos so clusters have real distinct sourcing.
        rows = db.execute(text(
            "SELECT canonical_label, num_videos FROM aggregated_topics "
            "WHERE num_videos >= 2 ORDER BY num_videos DESC, canonical_label")).fetchall()

    topics, seen = [], set()
    for label, _ in rows:
        k = _kw(label)
        slug = re.sub(r"[^a-z0-9]+", "-", k).strip("-")
        if not k or k in seen or k in existing or slug in existing:
            continue
        seen.add(k)
        topics.append(k)
        if len(topics) >= need:
            break

    if len(topics) < need:
        print(f"WARNING: only {len(topics)} groundable topics available, need {need}. "
              f"Reducing plan.", file=sys.stderr)

    # Pair each pillar with the topics that actually SUPPORT it, by shared significant terms.
    # The old sequential slice (topics[i] pillar, topics[i+1:] clusters) paired alphabetical
    # neighbours — "ac unit roof damage" got "approval process for roofing products" as a
    # supporting article. Topics come back ordered by num_videos DESC, so taking pillars in order
    # still gives the best-grounded topic the pillar role; only the pairing changes.
    stop = {"the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "with", "vs",
            "roof", "roofing", "roofs"}          # too common here to signal relatedness

    def terms(t: str) -> set:
        return {w for w in re.findall(r"[a-z0-9]+", t) if w not in stop and len(w) > 2}

    campaigns = []
    unused = list(topics)
    while unused and len(campaigns) < args.pillars:
        pillar = unused.pop(0)
        pt = terms(pillar)
        scored = sorted(
            ((len(pt & terms(t)), -i, t) for i, t in enumerate(unused)), reverse=True)
        picked = [t for score, _, t in scored[:args.clusters] if score > 0]
        # Not enough related topics left — fall back to the next best-grounded ones so the plan
        # still hits its count, rather than silently emitting a short campaign.
        for t in unused:
            if len(picked) >= args.clusters:
                break
            if t not in picked:
                picked.append(t)
        for t in picked:
            unused.remove(t)
        campaigns.append({"pillar": pillar, "clusters": picked})

    plan = {"campaigns": campaigns}
    with open(args.out, "w") as f:
        json.dump(plan, f, indent=1)
    total = sum(1 + len(c["clusters"]) for c in campaigns)
    print(f"plan: {len(campaigns)} campaigns / {total} articles -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
