"""Regression for the 2026-07-07 fixes to jobs/embed_job:
- skip-if-unchanged must NOT re-embed a video already at the current (model, version)
- but it MUST re-embed when the stored model differs (the nomic→gemini migration that the
  split-brain EMBED_MODEL default previously silently no-op'd)
- per-video isolation: one failure doesn't abort the batch."""
import pytest

import jobs.embed_job as EJ
from app.models import Base, Chunk, Segment, SessionLocal, Video, engine


@pytest.fixture(autouse=True)
def _fresh_db():
    """Wipe only the rows we touch.

    Deliberately NOT Base.metadata.drop_all(): pytest imports every test module before
    running any test, so modules that create_all at import time and then only DELETE rows
    have their tables torn out from under them by a drop_all here, failing with
    "no such table". Row deletes are order-independent. Same reasoning as
    tests/jobs/test_backfill_metadata_watermark.py and tests/api/test_portfolio.py.
    """
    Base.metadata.create_all(engine)  # idempotent; heals if another module dropped
    def _wipe():
        with SessionLocal() as db:
            db.query(Chunk).delete()
            db.query(Segment).delete()
            db.query(Video).delete()
            db.commit()
    _wipe()
    yield
    _wipe()


def _seed(vid, chunk_model=None):
    s = SessionLocal()
    s.add(Video(id=vid))
    s.add(Segment(video_id=vid, text="clay tile", start=0.0, end=5.0))
    if chunk_model:
        s.add(Chunk(video_id=vid, text="clay tile", start=0.0, end=5.0,
                    embedding=[0.1, 0.2], embed_model=chunk_model,
                    version=EJ.settings.PIPELINE_VERSION))
    s.commit(); s.close()


def test_skips_up_to_date_video(monkeypatch):
    monkeypatch.setattr(EJ.settings, "EMBED_MODEL", "gemini-embedding-001")
    _seed("v1", chunk_model="gemini-embedding-001")   # already current
    called = {"n": 0}
    monkeypatch.setattr(EJ, "embed", lambda texts: called.__setitem__("n", called["n"] + 1) or [[0.0]])
    result = EJ.run()
    assert result["skipped"] == 1 and result["reembedded_videos"] == 0
    assert called["n"] == 0            # embed() never called for an up-to-date video


def test_reembeds_when_model_differs(monkeypatch):
    # the migration case: corpus stamped nomic, active model gemini → MUST re-embed
    monkeypatch.setattr(EJ.settings, "EMBED_MODEL", "gemini-embedding-001")
    _seed("v1", chunk_model="nomic-embed-text")
    monkeypatch.setattr(EJ, "embed", lambda texts: [[0.0, 0.0] for _ in texts])
    result = EJ.run()
    assert result["reembedded_videos"] == 1 and result["skipped"] == 0
    s = SessionLocal()
    ch = s.query(Chunk).filter_by(video_id="v1").one()
    s.close()
    assert ch.embed_model == "gemini-embedding-001"   # re-stamped with the real model


def test_per_video_isolation(monkeypatch):
    monkeypatch.setattr(EJ.settings, "EMBED_MODEL", "gemini-embedding-001")
    _seed("good"); _seed("bad")

    def flaky(texts):
        # first video succeeds, second raises
        if flaky.calls == 0:
            flaky.calls += 1
            return [[0.1, 0.2] for _ in texts]
        raise RuntimeError("vertex 500")
    flaky.calls = 0
    monkeypatch.setattr(EJ, "embed", flaky)
    result = EJ.run()
    assert result["reembedded_videos"] == 1 and result["errored"] == 1
    s = SessionLocal()
    assert s.query(Chunk).count() == 1   # the good video's chunk persisted
    s.close()
