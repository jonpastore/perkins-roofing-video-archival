"""Cloud Run Job: (re-)embed every video that has segments, using the configured
EMBED_BACKEND. Purpose: the nomic-768 → Vertex gemini-embedding-001 (3072-dim) migration
— re-embeds the whole corpus with the single prod model into one index.

Run: EMBED_BACKEND=vertex .venv/bin/python -m jobs.embed_job [limit]
"""
import sys

from app.config import settings
from app.llm import embed
from app.models import Chunk, Segment, SessionLocal, Video
from core.chunking import chunk_segments


def run(limit=None, force=False):
    s = SessionLocal()
    reembedded, chunks_written, errored, skipped = 0, 0, 0, 0
    try:
        vids = [v.id for v in (s.query(Video).limit(limit).all() if limit else s.query(Video).all())]
        for vid in vids:
            segs = s.query(Segment).filter_by(video_id=vid).order_by(Segment.start).all()
            if not segs:
                continue
            # Skip-if-unchanged: chunks already embedded with the current model+version are
            # up to date — don't re-bill Vertex for the whole corpus on every run/retry.
            if not force:
                existing = s.query(Chunk).filter_by(video_id=vid).first()
                if (existing and existing.embed_model == settings.EMBED_MODEL
                        and existing.version == settings.PIPELINE_VERSION):
                    skipped += 1
                    continue
            try:  # per-video isolation — one bad video must not abort the corpus migration
                chunks = chunk_segments(segs, settings.CHUNK_SIZE)
                vecs = embed([c[0] for c in chunks])
                s.query(Chunk).filter_by(video_id=vid).delete()
                for (text, a, b), vec in zip(chunks, vecs):
                    s.add(Chunk(video_id=vid, text=text, start=a, end=b, embedding=vec,
                                embed_model=settings.EMBED_MODEL, version=settings.PIPELINE_VERSION))
                    chunks_written += 1
                s.commit()
                reembedded += 1
            except Exception as e:  # noqa: BLE001
                s.rollback()
                errored += 1
                print(f"[error] {vid}: {str(e)[:160]}")
    finally:
        s.close()
    return {"reembedded_videos": reembedded, "chunks": chunks_written, "skipped": skipped,
            "errored": errored, "model": settings.EMBED_MODEL}


if __name__ == "__main__":
    _limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    _force = "--force" in sys.argv
    print(run(limit=_limit, force=_force))
