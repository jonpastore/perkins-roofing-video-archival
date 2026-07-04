"""Free local STT endpoint for the Perkins v2 pipeline — faster-whisper on cerberus (RTX 5090).

POST /asr  {"url": "<youtube url>"}  ->  {segments, language, duration, speech_ratio}
Requires  Authorization: Bearer $WHISPER_TOKEN.  Only YouTube hosts are fetchable (no SSRF).
GPU access is serialized (one transcription at a time). The route is sync so FastAPI runs it in
a threadpool — the blocking transcribe never stalls the event loop / health checks.
Deployed to ~/whisper-perkins by ansible/whisper.yml (source of truth)."""
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException
from faster_whisper import WhisperModel
from pydantic import BaseModel

MODEL_NAME = os.getenv("WHISPER_MODEL", "large-v3")
TOKEN = os.getenv("WHISPER_TOKEN", "")
_ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_gpu = threading.Semaphore(1)  # bound the single CUDA model to one transcription at a time

app = FastAPI()
model = WhisperModel(MODEL_NAME, device="cuda", compute_type="float16")


class AsrReq(BaseModel):
    url: str


def _allowed(url: str) -> bool:
    try:
        return (urlparse(url).hostname or "") in _ALLOWED_HOSTS
    except ValueError:
        return False


def _fetch_audio(url: str, dst: Path) -> None:
    # yt-dlp via the venv Python (PATH-independent under systemd); 16kHz mono wav for whisper.
    subprocess.run(
        [sys.executable, "-m", "yt_dlp", "-x", "--audio-format", "wav",
         "--postprocessor-args", "-ar 16000 -ac 1", "-o", str(dst), url],
        check=True, capture_output=True, timeout=1800,
    )


def _speech_seconds(segs) -> float:
    """Total speech time with overlapping intervals merged (honest ratio, not double-counted)."""
    total, cur_s, cur_e = 0.0, None, None
    for a, b in sorted((s["start"], s["end"]) for s in segs):
        if cur_e is None:
            cur_s, cur_e = a, b
        elif a <= cur_e:
            cur_e = max(cur_e, b)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = a, b
    if cur_e is not None:
        total += cur_e - cur_s
    return total


@app.post("/asr")
def asr(body: AsrReq, authorization: str = Header(default="")):
    if not TOKEN:
        raise HTTPException(503, "server misconfigured: WHISPER_TOKEN unset")
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "unauthorized")
    if not _allowed(body.url):
        raise HTTPException(400, "url host not allowed")

    with tempfile.TemporaryDirectory() as d:
        try:
            _fetch_audio(body.url, (Path(d) / "a").with_suffix(""))
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "audio fetch timed out")
        except subprocess.CalledProcessError:
            raise HTTPException(422, "audio fetch failed")  # stderr logged server-side, not leaked
        wav = next(Path(d).glob("*.wav"), None)
        if not wav:
            raise HTTPException(422, "no audio extracted")
        with _gpu:  # one GPU transcription at a time
            segments, info = model.transcribe(str(wav), vad_filter=True)
            segs = [{"text": s.text.strip(), "start": s.start, "end": s.end} for s in segments]

    dur = getattr(info, "duration", 0.0) or 0.0
    return {
        "segments": segs,
        "language": info.language,
        "duration": dur,
        "speech_ratio": round(min(1.0, _speech_seconds(segs) / dur), 3) if dur else 0.0,
    }


@app.get("/health")
def health():
    return {"ok": True, "model": MODEL_NAME, "auth": bool(TOKEN)}
