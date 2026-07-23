"""Content-hub placement: given the existing pillar/cluster structure, decide for
each candidate topic whether it JOINS an existing pillar (as a new cluster) or
SEEDS a new pillar — so new generation extends the hub instead of minting
duplicate or orphan pillars.

Pure logic. Callers supply embeddings (any model) + a cosine function; nothing
here does I/O. See scripts/build_topic_plan.py for the Vertex-embedding wiring.
"""


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def place_topics(
    existing_pillars: list[dict],
    candidates: list[dict],
    *,
    threshold: float = 0.72,
    max_clusters_per_pillar: int = 8,
    sim=cosine,
) -> dict:
    """Assign candidates to existing pillars or group them into new pillars.

    Args:
        existing_pillars: [{"slug", "keyword", "vec"}] — the current hub pillars.
        candidates:       [{"keyword", "vec"}] — new topics to place (already
                          deduped against existing article keywords by the caller).
        threshold:        min cosine to an existing pillar to count as "same hub".
                          A new-pillar seed also absorbs neighbor seeds at this bar.
        max_clusters_per_pillar: cap so one pillar doesn't swallow everything
                          (existing clusters count toward the cap via "load").

    Returns:
        {
          "add_to_existing": [{"pillar_slug", "pillar_keyword", "clusters": [kw,...]}],
          "new_pillars":     [{"pillar", "clusters": [kw,...]}],
          "unplaced":        [kw, ...]   # seeds with no home and no neighbors
        }
    """
    add: dict[str, dict] = {}
    load = {p["slug"]: int(p.get("existing_clusters", 0)) for p in existing_pillars}
    seeds: list[dict] = []

    for cand in candidates:
        best_slug, best_sim = None, -1.0
        for p in existing_pillars:
            s = sim(cand["vec"], p["vec"])
            if s > best_sim:
                best_sim, best_slug = s, p["slug"]
        if best_slug is not None and best_sim >= threshold \
                and load.get(best_slug, 0) < max_clusters_per_pillar:
            pk = next(p for p in existing_pillars if p["slug"] == best_slug)
            entry = add.setdefault(best_slug, {
                "pillar_slug": best_slug, "pillar_keyword": pk["keyword"], "clusters": []})
            entry["clusters"].append(cand["keyword"])
            load[best_slug] = load.get(best_slug, 0) + 1
        else:
            seeds.append(cand)

    new_pillars, unplaced = _group_new_pillars(
        seeds, threshold=threshold, max_clusters_per_pillar=max_clusters_per_pillar, sim=sim)
    return {
        "add_to_existing": list(add.values()),
        "new_pillars": new_pillars,
        "unplaced": unplaced,
    }


def _group_new_pillars(seeds, *, threshold, max_clusters_per_pillar, sim):
    """Greedy: the seed with the most above-threshold neighbors becomes a pillar and
    absorbs its nearest unassigned neighbors as clusters; repeat until seeds run out.
    A seed with no neighbors becomes a solo pillar (no clusters yet) — better a new
    hub than a dropped topic."""
    remaining = list(seeds)
    new_pillars, unplaced = [], []
    while remaining:
        # neighbor count for each remaining seed
        def neighbors(s):
            return sorted(
                ((sim(s["vec"], o["vec"]), o) for o in remaining if o is not s),
                key=lambda t: t[0], reverse=True)

        pillar = max(remaining, key=lambda s: sum(1 for sc, _ in neighbors(s) if sc >= threshold))
        remaining.remove(pillar)
        near = [o for sc, o in neighbors(pillar) if sc >= threshold][:max_clusters_per_pillar]
        for o in near:
            remaining.remove(o)
        if near:
            new_pillars.append({"pillar": pillar["keyword"], "clusters": [o["keyword"] for o in near]})
        else:
            # lonely seed — still a valid new hub, just clusterless for now
            new_pillars.append({"pillar": pillar["keyword"], "clusters": []})
    return new_pillars, unplaced
