"""Transcript-source abstraction (council requirement #1). Downstream never cares whether
the transcript came from YouTube captions or GCP STT — it always gets the same normalized
schema: {source, segments:[{text,start,end}], words:[{word,start,confidence}]}."""
import os, glob, json
from .config import settings

def _json3_path(vid):
    g = sorted(glob.glob(os.path.join(settings.DATA_DIR, f"{vid}*.json3")))
    # prefer non-orig 'en' track if present
    g = [p for p in g if ".en." in p] or g
    return g[0] if g else None

def from_youtube_caption(vid):
    p = _json3_path(vid)
    if not p:
        raise FileNotFoundError(f"no captions on disk for {vid}")
    j = json.load(open(p))
    segs, words = [], []
    for ev in j.get("events", []):
        s = ev.get("segs")
        if not s:
            continue
        t0 = ev.get("tStartMs", 0) / 1000.0
        dur = ev.get("dDurationMs", 0) / 1000.0
        line = "".join(x.get("utf8", "") for x in s).strip()
        if not line:
            continue
        for x in s:
            w = x.get("utf8", "").strip()
            if w:
                words.append({"word": w, "start": t0 + x.get("tOffsetMs", 0) / 1000.0, "confidence": None})
        segs.append({"text": line, "start": t0, "end": t0 + dur})
    return {"source": "youtube_caption", "segments": segs, "words": words}

def from_gcp_stt(vid):
    # PROD: download audio to GCS, call Speech-to-Text v2 (word-level + confidence), normalize.
    raise NotImplementedError("GCP STT v2 backend — implement for production (word ts + confidence)")

def get_transcript(vid):
    if settings.TRANSCRIPT_POLICY == "stt_only":
        return from_gcp_stt(vid)
    try:
        return from_youtube_caption(vid)
    except FileNotFoundError:
        return from_gcp_stt(vid)
