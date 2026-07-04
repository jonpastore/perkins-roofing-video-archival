"""Cloud Run Job: run the resumable staged ingest over enumerated videos.
Transcript = on-disk captions → local Whisper fallback. Near-silent Shorts are VAD-skipped
inside ingest_video (core.vad) — the skip is persisted so they're never re-transcribed.

Run: .venv/bin/python -m jobs.ingest_worker [limit]
"""
import sys

from app import ingest
from app.models import SessionLocal, Video


def run(limit=None):
    s = SessionLocal()
    q = s.query(Video)
    vids = [v.id for v in (q.limit(limit).all() if limit else q.all())]
    s.close()

    ingested, errored = 0, 0
    for vid in vids:
        try:
            ingest.ingest_video(vid)  # resumable; VAD-skips + empty clips complete terminally
            ingested += 1
        except Exception as e:  # noqa: BLE001 — one bad video must not stop the batch
            errored += 1
            print(f"[error] {vid}: {str(e)[:160]}")
    return {"ingested": ingested, "errored": errored, "total": len(vids)}


if __name__ == "__main__":
    _limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    print(run(limit=_limit))
