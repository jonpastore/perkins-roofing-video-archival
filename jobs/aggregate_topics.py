"""Offline topic-aggregation job.

Loads all distinct content_graph topic labels, embeds them via app.llm.embed
(batched), then greedily clusters by cosine similarity (threshold 0.82) into
canonical topics.  Each cluster's canonical label is the label that appears
most frequently across all graph nodes; ties broken alphabetically.

Results are written to aggregated_topics via a clear-then-insert approach so
re-runs always produce a fresh, consistent snapshot.

Designed to run OFFLINE — set EMBED_BACKEND=ollama (or any local backend) in
the environment to avoid cloud embedding costs.

Usage:
    python -m jobs.aggregate_topics          # run and print summary JSON
    python jobs/aggregate_topics.py          # same
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_EMBED_BATCH = 64          # labels per embed() call
_SIM_THRESHOLD = 0.82      # cosine similarity to merge two labels into one cluster
_VERSION_FMT = "%Y%m%dT%H%M%SZ"


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def _embed_in_batches(texts: list[str]) -> "np.ndarray":
    """Embed *texts* in batches of _EMBED_BATCH; returns float32 ndarray (N, D)."""
    from app.llm import embed

    all_vecs: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH):
        batch = texts[i : i + _EMBED_BATCH]
        vecs = embed(batch)
        all_vecs.extend(vecs)
    arr = np.array(all_vecs, dtype=np.float32)
    # L2-normalise rows so cosine similarity == dot product
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return arr / norms


# ---------------------------------------------------------------------------
# Greedy clustering
# ---------------------------------------------------------------------------

def _greedy_cluster(
    labels: list[str],
    norm_vecs: "np.ndarray",
    threshold: float = _SIM_THRESHOLD,
) -> list[list[int]]:
    """Return a list of clusters; each cluster is a list of label indices.

    Greedy: iterate labels in original order.  If a label's embedding is
    within *threshold* cosine similarity of an existing cluster centroid,
    merge into that cluster.  Otherwise start a new cluster.

    Centroids are the mean of member normalised vectors (re-normalised after
    each merge so the dot-product comparison remains a cosine sim estimate).
    """
    n = len(labels)
    if n == 0:
        return []

    centroids: list[np.ndarray] = []   # one per cluster, unit-normalised
    clusters: list[list[int]] = []     # member label indices per cluster

    for idx in range(n):
        vec = norm_vecs[idx]  # already unit-normalised
        if not centroids:
            centroids.append(vec.copy())
            clusters.append([idx])
            continue

        # Dot products with all centroids == cosine sims (all unit-normalised)
        sims = np.array([float(c @ vec) for c in centroids])
        best = int(np.argmax(sims))
        if sims[best] >= threshold:
            clusters[best].append(idx)
            # Update centroid: mean of members, re-normalised
            member_vecs = norm_vecs[clusters[best]]
            new_centroid = member_vecs.mean(axis=0)
            norm = float(np.linalg.norm(new_centroid))
            centroids[best] = new_centroid / norm if norm > 0 else new_centroid
        else:
            centroids.append(vec.copy())
            clusters.append([idx])

    return clusters


# ---------------------------------------------------------------------------
# Main run() — the public API for this job
# ---------------------------------------------------------------------------

def run(sim_threshold: float = _SIM_THRESHOLD) -> dict[str, Any]:
    """Cluster all content_graph topic labels and upsert into aggregated_topics.

    Returns a summary dict:
        {
            "version": str,
            "num_raw_labels": int,
            "num_clusters": int,
            "clusters": [{"canonical_label": str, "num_videos": int,
                          "total_seconds": float, "video_ids": [...],
                          "node_ids": [...]}]
        }
    """
    from app.models import AggregatedTopic, GraphNode, SessionLocal, Video

    version = datetime.now(timezone.utc).strftime(_VERSION_FMT)

    with SessionLocal() as db:
        # ---- Load all topic nodes ----------------------------------------
        rows = (
            db.query(GraphNode.id, GraphNode.label, GraphNode.video_id)
            .filter(GraphNode.kind == "topics")
            .all()
        )
        if not rows:
            logger.info("aggregate_topics: no topic nodes found, clearing table")
            db.query(AggregatedTopic).delete()
            db.commit()
            return {"version": version, "num_raw_labels": 0, "num_clusters": 0, "clusters": []}

        # ---- Build label-level stats before clustering -------------------
        # label_index: distinct (lowercased) labels → list index in `distinct_labels`
        # label_counts: normalised label → frequency count across all nodes
        label_counts: dict[str, int] = defaultdict(int)
        # raw_label_for: normalised → most-frequent raw form (resolved after counting)
        raw_label_map: dict[str, list[str]] = defaultdict(list)

        # Per node: which (norm_label, video_id, node_id)
        node_data: list[tuple[str, str, int]] = []  # (norm_label, video_id, node_id)
        for node_id, label, video_id in rows:
            if not label:
                continue
            norm = label.strip().lower()
            label_counts[norm] += 1
            raw_label_map[norm].append(label.strip())
            node_data.append((norm, video_id, node_id))

        if not label_counts:
            db.query(AggregatedTopic).delete()
            db.commit()
            return {"version": version, "num_raw_labels": 0, "num_clusters": 0, "clusters": []}

        distinct_norm_labels = list(label_counts.keys())
        # Choose the most frequent raw form as canonical; ties → alphabetically first
        canonical_for: dict[str, str] = {}
        for norm, raw_list in raw_label_map.items():
            freq: dict[str, int] = defaultdict(int)
            for r in raw_list:
                freq[r] += 1
            max_freq = max(freq.values())
            candidates = sorted(r for r, c in freq.items() if c == max_freq)
            canonical_for[norm] = candidates[0]

        # ---- Embed -------------------------------------------------------
        logger.info("aggregate_topics: embedding %d distinct labels", len(distinct_norm_labels))
        norm_vecs = _embed_in_batches(distinct_norm_labels)

        # ---- Cluster -----------------------------------------------------
        clusters = _greedy_cluster(distinct_norm_labels, norm_vecs, threshold=sim_threshold)
        logger.info("aggregate_topics: %d labels → %d clusters", len(distinct_norm_labels), len(clusters))

        # ---- Build cluster metadata -------------------------------------
        # Map norm_label → cluster index for fast lookup
        norm_to_cluster: dict[str, int] = {}
        for ci, member_indices in enumerate(clusters):
            for idx in member_indices:
                norm_to_cluster[distinct_norm_labels[idx]] = ci

        # Accumulate video_ids and node_ids per cluster
        cluster_video_ids: list[set[str]] = [set() for _ in clusters]
        cluster_node_ids: list[list[int]] = [[] for _ in clusters]
        for norm, video_id, node_id in node_data:
            ci = norm_to_cluster.get(norm)
            if ci is None:
                continue
            cluster_video_ids[ci].add(video_id)
            cluster_node_ids[ci].append(node_id)

        # Choose canonical label per cluster: most frequent label among members
        cluster_canonical: list[str] = []
        for ci, member_indices in enumerate(clusters):
            best_norm = max(
                (distinct_norm_labels[idx] for idx in member_indices),
                key=lambda n: label_counts[n],
            )
            cluster_canonical.append(canonical_for[best_norm])

        # Fetch video durations in one query
        all_video_ids = {vid for s in cluster_video_ids for vid in s}
        duration_map: dict[str, float] = {}
        if all_video_ids:
            vids = db.query(Video).filter(Video.id.in_(list(all_video_ids))).all()
            duration_map = {v.id: float(v.duration or 0.0) for v in vids}

        # ---- Upsert: clear + insert -------------------------------------
        db.query(AggregatedTopic).delete()
        result_clusters = []
        for ci in range(len(clusters)):
            vid_list = sorted(cluster_video_ids[ci])
            nid_list = sorted(cluster_node_ids[ci])
            total_sec = sum(duration_map.get(v, 0.0) for v in vid_list)
            rec = AggregatedTopic(
                canonical_label=cluster_canonical[ci],
                num_videos=len(vid_list),
                total_seconds=total_sec,
                video_ids=vid_list,
                node_ids=nid_list,
                version=version,
            )
            db.add(rec)
            result_clusters.append({
                "canonical_label": cluster_canonical[ci],
                "num_videos": len(vid_list),
                "total_seconds": total_sec,
                "video_ids": vid_list,
                "node_ids": nid_list,
            })

        db.commit()

    return {
        "version": version,
        "num_raw_labels": len(distinct_norm_labels),
        "num_clusters": len(clusters),
        "clusters": result_clusters,
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    print(json.dumps(run()))
