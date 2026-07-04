"""Regression guard for the Wave-1 VAD/resumability fix (code-review HIGH finding).

Proves: (1) a near-silent clip completes ALL stages terminally with no content and no LLM
calls; (2) re-running a skipped OR a normal video does NOT reprocess (no re-transcribe /
re-embed / re-extract). Hermetic — stubs embed+extract, temp DB, no network/GPU.

Run: .venv/bin/python scripts/validate_ingest_vad.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_URL"] = f"sqlite:///{tempfile.mkdtemp()}/t.db"

from app import graph, ingest  # noqa: E402
from app.models import Chunk, GraphNode, Segment, SessionLocal  # noqa: E402

calls = {"embed": 0, "extract": 0}
ingest.embed = lambda texts: (calls.update(embed=calls["embed"] + 1) or [[0.0] * 3072 for _ in texts])
graph.extract = lambda segs: (calls.update(extract=calls["extract"] + 1)
                              or [{"kind": "topics", "label": "x", "detail": "", "start": 0, "version": "v1"}])


def _stages(st):
    return {r["stage"]: r["status"] for r in st}


def _fail(m):
    raise SystemExit(f"REGRESSION: {m}")


# --- Case A: near-silent clip (speech_ratio below the 0.15 VAD gate) ---
trA = {"source": "whisper", "segments": [{"text": "la la", "start": 0, "end": 2}],
       "words": [], "speech_ratio": 0.05}
sA = _stages(ingest.ingest_video("silentvid", transcript=trA))
if not (sA.get("transcript") == sA.get("graph") == sA.get("embed") == "done"):
    _fail(f"silent clip stages must all be terminal 'done', got {sA}")
s = SessionLocal()
if s.query(Segment).filter_by(video_id="silentvid").count() or \
   s.query(Chunk).filter_by(video_id="silentvid").count() or \
   s.query(GraphNode).filter_by(video_id="silentvid").count():
    _fail("silent clip must store no segments/chunks/graph nodes")
s.close()
if calls["embed"] or calls["extract"]:
    _fail("VAD-skip must not call embed/extract")

# Re-run Case A → must not reprocess (this is the HIGH bug: was re-transcribing every pass)
ingest.ingest_video("silentvid", transcript=trA)
if calls["embed"] or calls["extract"]:
    _fail("re-running a skipped video must not reprocess")

# --- Case B: normal speech ---
trB = {"source": "whisper",
       "segments": [{"text": "roof flashing", "start": 0, "end": 3},
                    {"text": "underlayment", "start": 3, "end": 6}],
       "words": [], "speech_ratio": 0.9}
sB = _stages(ingest.ingest_video("goodvid", transcript=trB))
if not (sB.get("transcript") == sB.get("graph") == sB.get("embed") == "done"):
    _fail(f"normal clip stages must be done, got {sB}")
s = SessionLocal()
if s.query(Segment).filter_by(video_id="goodvid").count() != 2 or \
   s.query(Chunk).filter_by(video_id="goodvid").count() < 1:
    _fail("normal clip must store its segments + chunks")
s.close()
if calls != {"embed": 1, "extract": 1}:
    _fail(f"normal clip should call embed+extract once each, got {calls}")

# Re-run Case B → idempotent, no re-embed
ingest.ingest_video("goodvid", transcript=trB)
if calls != {"embed": 1, "extract": 1}:
    _fail(f"re-running a normal video must not reprocess, calls={calls}")

print("INGEST VAD/RESUMABILITY OK — skips persist terminally, no reprocess on rerun")
