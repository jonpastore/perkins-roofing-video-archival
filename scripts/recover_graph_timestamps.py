#!/usr/bin/env python3
"""Recover real timestamps for content_graph rows zeroed by the graph.py secs() bug.

Root cause (fixed in 5e60d59): secs() defaulted malformed/absent LLM timecodes to 0, so
675 topic/claim/objection nodes point at the video start. The original timecode strings
weren't stored, so we recover in-place by matching each node's text to the transcript
segment with the highest meaningful word overlap and taking that segment's start. Node IDs
are preserved (155 faq_entries reference them). No LLM, no re-extraction.

Conservative: a node whose best match is below MIN_OVERLAP is set to NULL (link omits ?t=)
— a bare link is strictly better than a confidently-wrong jump. start=0 that legitimately
matches a segment at t=0 stays 0.

Run (ADC + Cloud SQL connector):
    GOOGLE_CLOUD_PROJECT=video-archival-and-content-gen \
      .venv/bin/python scripts/recover_graph_timestamps.py [--apply]
Default is DRY RUN (prints stats, writes nothing). --apply commits.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

import sqlalchemy as sa

MIN_OVERLAP = 2  # require >= 2 shared meaningful words to trust a match
_STOP = {
    "the", "a", "an", "of", "to", "and", "or", "is", "are", "in", "on", "for", "with",
    "your", "you", "it", "that", "this", "how", "what", "why", "vs", "s",
}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in _STOP}


_INTRO_SKIP_SECS = 8.0  # skip the opening intro segment: it name-drops topics discussed
                        # later, which biased every match to t=0 (the exact bug symptom)


def _best_segment(node_words: set[str], segs: list[tuple[float, str]]) -> tuple[float | None, int]:
    """Return (start, overlap) of the segment (after the intro) with max word overlap.

    A topic/claim's timecode should point to where it's DISCUSSED, not the intro that
    merely lists it. Candidates are restricted to start > _INTRO_SKIP_SECS; ties break to
    the earliest such segment (first real discussion)."""
    best_start, best_overlap = None, 0
    for start, text in segs:
        if start <= _INTRO_SKIP_SECS:
            continue
        overlap = len(node_words & _words(text))
        if overlap > best_overlap:  # strictly greater -> earliest max-overlap segment wins
            best_start, best_overlap = start, overlap
    return best_start, best_overlap


def main(apply: bool) -> int:
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    pw = subprocess.check_output(
        ["gcloud", "secrets", "versions", "access", "latest",
         "--secret=db-password", "--project", project]).decode().strip()
    from google.cloud.sql.connector import Connector
    conn_mgr = Connector()

    def _c():
        return conn_mgr.connect(
            f"{project}:us-central1:{project}-pg", "pg8000",
            user="app", password=pw, db="perkins")

    engine = sa.create_engine("postgresql+pg8000://", creator=_c)
    updated = nulled = kept = 0
    with engine.begin() as conn:
        conn.execute(sa.text("SELECT set_config('app.tenant_id', '1', true)"))
        nodes = conn.execute(sa.text(
            "SELECT id, video_id, label, detail FROM content_graph WHERE start = 0"
        )).fetchall()
        # cache segments per video
        seg_cache: dict[str, list[tuple[float, str]]] = {}
        for nid, vid, label, detail in nodes:
            if vid not in seg_cache:
                seg_cache[vid] = [
                    (float(s), t) for s, t in conn.execute(sa.text(
                        "SELECT start, text FROM segments WHERE video_id = :v "
                        "AND start IS NOT NULL ORDER BY start"), {"v": vid}).fetchall()]
            nw = _words(label) | _words(detail)
            start, overlap = _best_segment(nw, seg_cache[vid]) if nw else (None, 0)
            if overlap >= MIN_OVERLAP and start is not None and start > 0:
                updated += 1
                if apply:
                    conn.execute(sa.text("UPDATE content_graph SET start=:s WHERE id=:i"),
                                 {"s": start, "i": nid})
            elif start is not None and start == 0:
                kept += 1  # legitimately matches a t=0 segment
            else:
                nulled += 1
                if apply:
                    conn.execute(sa.text("UPDATE content_graph SET start=NULL WHERE id=:i"),
                                 {"i": nid})
        if not apply:
            conn.rollback()
    conn_mgr.close()
    print(f"{'APPLIED' if apply else 'DRY RUN'}: {len(nodes)} start=0 nodes | "
          f"recovered->timestamp: {updated} | kept at 0 (real t=0 match): {kept} | "
          f"set NULL (no confident match): {nulled}")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
