"""Local Whisper STT adapter (I/O, coverage-omitted). POSTs a media URL to the free
faster-whisper endpoint on cerberus (WHISPER_URL) and returns the normalized transcript
schema {source, segments, words, speech_ratio}. speech_ratio feeds core.vad."""
import json
import os
import urllib.request


def transcribe(video_id):
    url = os.getenv("WHISPER_URL", "http://cerberus-ai:9000/asr")
    payload = json.dumps({"url": f"https://youtu.be/{video_id}"}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    tok = os.getenv("WHISPER_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=1800) as r:
        data = json.loads(r.read().decode())
    segs = [{"text": s["text"], "start": s["start"], "end": s["end"]}
            for s in data.get("segments", [])]
    return {"source": "whisper", "segments": segs, "words": [],
            "speech_ratio": data.get("speech_ratio", 0.0)}
