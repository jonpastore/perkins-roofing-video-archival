"""Idempotent, resumable, staged ingestion (council requirement). Each stage
(transcript → graph → embed) is content-hashed and status-tracked in IngestionRun;
re-running skips unchanged stages and retries only what failed."""
import hashlib, json
from .config import settings
from .models import SessionLocal, init_db, Video, IngestionRun, Segment, Word, GraphNode, Chunk
from . import transcript as T, graph as G
from .llm import embed
from core.chunking import chunk_segments
from core.vad import should_transcribe

def _hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]

def _run(s, vid, stage):
    return s.query(IngestionRun).filter_by(video_id=vid, stage=stage).one_or_none()

def _set(s, vid, stage, status, content_hash=None, err=None):
    r = _run(s, vid, stage) or IngestionRun(video_id=vid, stage=stage, attempts=0)
    r.status = status
    r.pipeline_version = settings.PIPELINE_VERSION
    if content_hash:
        r.content_hash = content_hash
    if status == "error":
        r.attempts = (r.attempts or 0) + 1
    r.last_error = err
    s.add(r); s.commit()

def _fresh(st, h):
    return st and st.status == "done" and st.content_hash == h and st.pipeline_version == settings.PIPELINE_VERSION

def ingest_video(vid, meta=None, force=False, transcript=None):
    init_db()
    s = SessionLocal()
    v = s.get(Video, vid) or Video(id=vid, url=f"https://youtu.be/{vid}")
    if meta:
        v.title = meta.get("title", v.title); v.duration = meta.get("duration", v.duration)
        v.upload_date = meta.get("upload_date", v.upload_date)
        v.views = meta.get("view_count", v.views); v.likes = meta.get("like_count", v.likes)
        v.comments = meta.get("comment_count", v.comments)
    s.add(v); s.commit()

    # ---- stage: transcript
    # The fetch (Whisper GPU + yt-dlp download) is EXPENSIVE, so gate it behind the stage's
    # freshness: a resumable rerun of an already-transcribed video reuses the DB segments and
    # never re-downloads/re-transcribes. Only fetch when injected, forced, or not-yet-done.
    prev_t = _run(s, vid, "transcript")
    already = bool(prev_t and prev_t.status == "done"
                   and prev_t.pipeline_version == settings.PIPELINE_VERSION)
    if transcript is not None:
        tr = transcript
    elif force or not already:
        try:
            tr = T.get_transcript(vid, gcs_uri=v.archive_uri)
        except Exception as e:                       # record the failure so it's queryable
            s.rollback(); _set(s, vid, "transcript", "error", err=str(e)[:200])
            s.close(); return status(vid)
    else:
        tr = None                                    # already done at this version — reuse DB

    if tr is not None:
        # VAD gate: a near-silent clip (music-only Short) gets no indexed content, but the
        # stage still completes so it is never re-transcribed on the next resumable pass.
        if "speech_ratio" in tr and not should_transcribe(tr["speech_ratio"]):
            tr = {**tr, "segments": [], "words": []}
        h = _hash([tr["source"], [x["text"] for x in tr["segments"]]])
        if force or not _fresh(prev_t, h):
            s.query(Segment).filter_by(video_id=vid).delete()
            s.query(Word).filter_by(video_id=vid).delete()
            for seg in tr["segments"]:
                s.add(Segment(video_id=vid, text=seg["text"], start=seg["start"], end=seg["end"], source=tr["source"]))
            for w in tr["words"]:
                s.add(Word(video_id=vid, word=w["word"], start=w["start"], confidence=w["confidence"]))
            s.commit(); _set(s, vid, "transcript", "done", h)

    segs = s.query(Segment).filter_by(video_id=vid).order_by(Segment.start).all()
    seg_dicts = [{"text": x.text, "start": x.start} for x in segs]

    # ---- stage: graph
    gh = _hash([settings.GRAPH_VERSION, len(seg_dicts)])
    if force or not _fresh(_run(s, vid, "graph"), gh):
        if not seg_dicts:
            _set(s, vid, "graph", "done", gh)          # no content → terminal, don't reprocess
        else:
            try:
                s.query(GraphNode).filter_by(video_id=vid).delete(); s.commit()
                for r in G.extract(seg_dicts):
                    s.add(GraphNode(video_id=vid, **r))
                s.commit(); _set(s, vid, "graph", "done", gh)
            except Exception as e:
                s.rollback(); _set(s, vid, "graph", "error", err=str(e)[:200])

    # ---- stage: embed
    eh = _hash([settings.EMBED_MODEL, settings.CHUNK_SIZE, len(seg_dicts)])
    if force or not _fresh(_run(s, vid, "embed"), eh):
        if not seg_dicts:
            _set(s, vid, "embed", "done", eh)          # no content → terminal, don't reprocess
        else:
            try:
                s.query(Chunk).filter_by(video_id=vid).delete(); s.commit()
                chunks = chunk_segments(segs, settings.CHUNK_SIZE)
                vecs = embed([c[0] for c in chunks]) if chunks else []
                for (text, a, b), vec in zip(chunks, vecs):
                    s.add(Chunk(video_id=vid, text=text, start=a, end=b, embedding=vec,
                                embed_model=settings.EMBED_MODEL, version=settings.PIPELINE_VERSION))
                s.commit(); _set(s, vid, "embed", "done", eh)
            except Exception as e:
                s.rollback(); _set(s, vid, "embed", "error", err=str(e)[:200])

    s.close()
    return status(vid)

def status(vid=None):
    s = SessionLocal()
    q = s.query(IngestionRun)
    if vid:
        q = q.filter_by(video_id=vid)
    out = [{"video_id": r.video_id, "stage": r.stage, "status": r.status, "attempts": r.attempts,
            "error": r.last_error} for r in q.all()]
    s.close()
    return out
