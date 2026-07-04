"""Hermetic behavior-preservation check for the adapters/core refactor.

Seeds a temp SQLite DB with known chunks/graph, stubs the embed+chat I/O, and asserts the
refactored app.retrieval.search / app.answer.ask (which now delegate to core) produce the
same ranking + abstention behavior as the pre-refactor POC. No network / no GPU needed.

Run: .venv/bin/python scripts/validate_pipeline.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_d = tempfile.mkdtemp()
os.environ["DB_URL"] = f"sqlite:///{_d}/t.db"  # must be set before importing app.models

from app import answer, models, retrieval, store  # noqa: E402

models.init_db()
s = models.SessionLocal()
s.add(models.Video(id="v1", url="https://youtu.be/v1"))
s.add(models.Chunk(video_id="v1", text="Always check the flashing first", start=5, end=9,
                   embedding=[1.0, 0.0, 0.0], embed_model="test", version="v1"))
s.add(models.Chunk(video_id="v1", text="Clean your gutters seasonally", start=10, end=14,
                   embedding=[0.0, 1.0, 0.0], embed_model="test", version="v1"))
s.add(models.GraphNode(video_id="v1", kind="claims", label="check flashing", detail="", start=5, version="v1"))
s.commit()
s.close()


def _fail(msg):
    raise SystemExit(f"REGRESSION: {msg}")


# --- on-topic: query aligned with the flashing chunk ---
store.embed = lambda texts: [[1.0, 0.0, 0.0]]
res = retrieval.search("flashing", 3)
if not res:
    _fail("search returned nothing on-topic")
if not res[0]["link"].startswith("https://youtu.be/") or "?t=" not in res[0]["link"]:
    _fail(f"bad citation link {res[0]['link']!r}")
if res[0]["link"] != "https://youtu.be/v1?t=5":
    _fail(f"expected flashing chunk on top, got {res[0]}")
# score = 1.0 vector + 0.15 lexical('flashing') + 0.10 graph = 1.25 (verbatim from POC math)
if abs(res[0]["score"] - 1.25) > 1e-6:
    _fail(f"score math changed: {res[0]['score']} != 1.25")

answer.chat = lambda prompt, **k: "Grounded answer with citation."
a = answer.ask("flashing")
if a["abstained"] is not False or not a["citations"]:
    _fail(f"on-topic should answer with citations, got {a}")

# --- off-topic: query orthogonal to everything → abstain ---
store.embed = lambda texts: [[0.0, 0.0, 1.0]]
a2 = answer.ask("how do I bake sourdough")
if a2["abstained"] is not True or a2["citations"] != []:
    _fail(f"off-topic should abstain with no citations, got {a2}")

print("PIPELINE REGRESSION OK — refactored search/ask preserve POC ranking + abstention")
print(f"  on-topic top: {res[0]['link']} score={res[0]['score']}")
print(f"  off-topic abstained={a2['abstained']} citations={a2['citations']}")
