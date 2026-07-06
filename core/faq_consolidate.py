"""Pure FAQ consolidation logic — cluster near-duplicate questions, pick a canonical,
and merge citation links. No I/O (embeddings + DB live in jobs/consolidate_faqs.py).
"""
from __future__ import annotations

import re

_LINK_RE = re.compile(r"\((https?://[^)\s]+)\)")


def greedy_cluster(sim: list[list[float]], threshold: float) -> list[list[int]]:
    """Greedy single-pass clustering over a cosine-similarity matrix.

    Walks items in order; each still-unassigned item seeds a cluster and pulls in every
    other unassigned item with similarity >= threshold. Returns a list of clusters
    (each a list of row indices); every index appears exactly once.
    """
    n = len(sim)
    assigned = [False] * n
    clusters: list[list[int]] = []
    for i in range(n):
        if assigned[i]:
            continue
        members = [i]
        assigned[i] = True
        row = sim[i]
        for j in range(i + 1, n):
            if not assigned[j] and row[j] >= threshold:
                assigned[j] = True
                members.append(j)
        clusters.append(members)
    return clusters


def choose_canonical(entries: list[dict]) -> int:
    """Index of the best canonical entry in a cluster.

    Prefers an answered entry (non-empty answer); among those (or, if none answered,
    among all) prefers the longest — most complete — answer, then the longest question
    as a tiebreak so the clearest phrasing wins.
    """
    def key(e: dict) -> tuple:
        answered = 1 if (e.get("status") == "answered" and (e.get("answer") or "").strip()) else 0
        return (answered, len(e.get("answer") or ""), len(e.get("question") or ""))

    best_i, best_key = 0, None
    for i, e in enumerate(entries):
        k = key(e)
        if best_key is None or k > best_key:
            best_i, best_key = i, k
    return best_i


def links_in(answer: str) -> list[str]:
    """Extract the source URLs already present in an answer's markdown citations."""
    return _LINK_RE.findall(answer or "")


def merge_citations(canonical_answer: str, extra_urls: list[str]) -> str:
    """Append any missing source URLs to the canonical answer's ``Sources:`` line.

    Preserves the existing citation numbering and adds new ``[link N](url)`` entries for
    URLs not already cited. Returns the answer unchanged when there is nothing to add or
    the canonical has no answer text.
    """
    if not canonical_answer:
        return canonical_answer
    have = set(links_in(canonical_answer))
    new = [u for u in dict.fromkeys(extra_urls) if u not in have]
    if not new:
        return canonical_answer

    start_n = len(have) + 1
    additions = " · ".join(f"[link {start_n + i}]({u})" for i, u in enumerate(new))
    if "Sources:" in canonical_answer:
        return canonical_answer.rstrip() + " · " + additions
    return canonical_answer.rstrip() + "\n\nSources: " + additions
