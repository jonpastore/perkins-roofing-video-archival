"""Core tests (dev: requires cerberus reachable + migrated corpus in app/dev.db).
Run: python3 -m pytest app/tests -q"""
from app import retrieval, answer, ingest

def test_search_returns_timecoded_results():
    res = retrieval.search("clay tile underlayment", 3)
    assert len(res) > 0
    assert res[0]["link"].startswith("https://youtu.be/")
    assert "?t=" in res[0]["link"]

def test_search_is_cross_library():
    # the headline ask should pull from more than one video
    res = retrieval.search("clay tiles", 8)
    assert len({r["video_id"] for r in res}) >= 2

def test_abstains_on_offtopic():
    r = answer.ask("How do I bake sourdough bread?")
    assert r["abstained"] is True
    assert r["citations"] == []

def test_answers_ontopic_with_citations():
    r = answer.ask("What are red flags in a tile roof estimate?")
    assert r["abstained"] is False
    assert len(r["citations"]) > 0

def test_ingest_is_idempotent():
    ingest.ingest_video("ls9zLWRiDHg")              # captions already on disk
    st = ingest.ingest_video("ls9zLWRiDHg")          # second run = skip-unchanged
    stages = {r["stage"]: r["status"] for r in st}
    assert stages.get("transcript") == "done"
    assert stages.get("embed") == "done"
    assert all(r["status"] != "error" for r in st)
