"""C1 Part 2 step 1 — the retrieval chain must use a caller-passed (stamped) session.

Under strict=True every unstamped tenant SessionLocal session raises on Postgres, so
/search, /ask and the FAQ-answer path must thread the request's stamped session through
store.vector_search -> retrieval.hybrid_search/search -> answer.ask/answer_faq.

These tests patch SessionLocal in each module with a tripwire that raises if the chain
opens its own session while a db was passed, and verify the no-db compat path still works.
"""
import pytest


def _seed():
    from app.models import Base, Chunk, GraphNode, SessionLocal, Video, engine
    Base.metadata.create_all(engine)
    s = SessionLocal()
    try:
        if not s.get(Video, "dbt-vid"):
            s.add(Video(id="dbt-vid", title="Metal Roof Cost Video"))
            s.add(Chunk(video_id="dbt-vid", text="metal roof cost runs twelve dollars",
                        start=1.0, end=5.0, embedding=[1.0, 0.0, 0.0]))
            s.add(GraphNode(video_id="dbt-vid", kind="claims",
                            label="metal roof cost", detail="cost detail", start=1.0))
            s.commit()
    finally:
        s.close()


@pytest.fixture(autouse=True, scope="module")
def _cleanup_seed():
    """Remove the seeded rows after this module so they can't skew other files'
    content_graph/chunk counts (shared temp SQLite for the whole suite)."""
    yield
    from app.models import Chunk, GraphNode, SessionLocal, Video
    s = SessionLocal()
    try:
        s.query(Chunk).filter(Chunk.video_id == "dbt-vid").delete()
        s.query(GraphNode).filter(GraphNode.video_id == "dbt-vid").delete()
        s.query(Video).filter(Video.id == "dbt-vid").delete()
        s.commit()
    finally:
        s.close()


def _tripwire(monkeypatch, *modules):
    def boom(*a, **k):
        raise AssertionError("chain opened its own SessionLocal despite a passed db")
    for m in modules:
        monkeypatch.setattr(m, "SessionLocal", boom)


@pytest.fixture()
def session(monkeypatch):
    _seed()
    import app.answer as answer
    import app.store as store
    _fake_embed = lambda texts: [[1.0, 0.0, 0.0] for _ in texts]  # noqa: E731
    monkeypatch.setattr(store, "embed", _fake_embed)
    # ask() now embeds the query up front for the semantic cache probe (ask_cache);
    # mock answer.embed too so no test in this module reaches the real embedder.
    monkeypatch.setattr(answer, "embed", _fake_embed)
    from app.models import SessionLocal
    s = SessionLocal()
    yield s
    s.close()


def test_hybrid_search_uses_passed_db(monkeypatch, session):
    import app.retrieval as retrieval
    import app.store as store
    _tripwire(monkeypatch, retrieval, store)
    r = retrieval.hybrid_search("metal roof cost", db=session)
    assert r["chunks"], "expected seeded chunk back through the passed session"


def test_search_threads_db(monkeypatch, session):
    import app.retrieval as retrieval
    import app.store as store
    _tripwire(monkeypatch, retrieval, store)
    rows = retrieval.search("metal roof cost", db=session)
    assert rows and rows[0]["video_id"] == "dbt-vid"


def test_ask_uses_passed_db(monkeypatch, session):
    import app.answer as answer
    import app.retrieval as retrieval
    import app.store as store
    _tripwire(monkeypatch, answer, retrieval, store)
    monkeypatch.setattr(answer, "chat", lambda prompt: "Grounded answer.")
    monkeypatch.setattr(answer.settings, "ABSTAIN_THRESHOLD", 0.1)
    res = answer.ask("metal roof cost", db=session)
    assert res["abstained"] is False
    assert res["sources"][0]["title"] == "Metal Roof Cost Video"


def test_answer_faq_uses_passed_db(monkeypatch, session):
    import app.answer as answer
    import app.retrieval as retrieval
    import app.store as store
    _tripwire(monkeypatch, answer, retrieval, store)
    monkeypatch.setattr(answer, "chat", lambda prompt: "Concise cited answer.")
    monkeypatch.setattr(answer.settings, "ABSTAIN_THRESHOLD", 0.1)
    res = answer.answer_faq("metal roof cost", db=session)
    assert res["abstained"] is False
    assert "Sources:" in res["answer"]


def test_compat_without_db_still_opens_own_session(monkeypatch):
    _seed()
    import app.retrieval as retrieval
    import app.store as store
    monkeypatch.setattr(store, "embed", lambda texts: [[1.0, 0.0, 0.0] for _ in texts])
    r = retrieval.hybrid_search("metal roof cost")
    assert r["chunks"]
