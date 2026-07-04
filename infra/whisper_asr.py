"""Free local STT endpoint for the Perkins v2 pipeline — faster-whisper on cerberus (RTX 5090).

POST /asr  {"url": "<youtube or direct media url>"}  ->  {segments, language, duration, speech_ratio}
Deployed at ~/whisper-perkins on cerberus; adapters/stt_whisper.py posts here (WHISPER_URL).
Optional bearer auth via WHISPER_TOKEN env var.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from faster_whisper import WhisperModel

MODEL_NAME = os.getenv("WHISPER_MODEL", "large-v3")
TOKEN = os.getenv("WHISPER_TOKEN", "")

app = FastAPI()
# 24GB 5090: large-v3 float16 fits comfortably.
model = WhisperModel(MODEL_NAME, device="cuda", compute_type="float16")


def _fetch_audio(url: str, dst: Path) -> None:
    # yt-dlp handles YouTube + most direct media URLs; extract 16kHz mono wav for whisper.
    # Invoke yt-dlp via the venv's Python so it resolves without relying on PATH (nohup).
    subprocess.run(
        [sys.executable, "-m", "yt_dlp", "-x", "--audio-format", "wav",
         "--postprocessor-args", "-ar 16000 -ac 1",
         "-o", str(dst), url],
        check=True, capture_output=True, timeout=1800,
    )


@app.post("/asr")
async def asr(req: Request):
    if TOKEN and req.headers.get("authorization") != f"Bearer {TOKEN}":
        raise HTTPException(401, "unauthorized")
    body = await req.json()
    url = body.get("url")
    if not url:
        raise HTTPException(400, "missing url")

    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "a.wav"
        try:
            _fetch_audio(url, out.with_suffix(""))  # yt-dlp appends .wav
        except subprocess.CalledProcessError as e:
            raise HTTPException(422, f"fetch failed: {e.stderr.decode()[-300:]}")
        wav = next(Path(d).glob("*.wav"), None)
        if not wav:
            raise HTTPException(422, "no audio extracted")

        # vad_filter drops non-speech; word_timestamps keeps alignment for chunking.
        segments, info = model.transcribe(str(wav), vad_filter=True, word_timestamps=False)
        segs = [{"text": s.text.strip(), "start": s.start, "end": s.end} for s in segments]

    speech = sum(s["end"] - s["start"] for s in segs)
    dur = getattr(info, "duration", 0.0) or 0.0
    return {
        "segments": segs,
        "language": info.language,
        "duration": dur,
        # clamp to [0,1] — VAD segments are normally non-overlapping but guard anyway
        "speech_ratio": min(1.0, round(speech / dur, 3)) if dur else 0.0,
    }


@app.get("/health")
def health():
    return {"ok": True, "model": MODEL_NAME}
