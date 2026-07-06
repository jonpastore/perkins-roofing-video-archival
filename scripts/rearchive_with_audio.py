#!/usr/bin/env python
"""Re-archive video(s) WITH audio when the archived MP4 is video-only.

Some videos were archived video-only (their yt-dlp audio merge failed at archive time), so
Speech-to-Text has no audio track to transcribe ("Output file does not contain any stream").
This tool re-downloads the source WITH audio (browser cookies + a modern Chrome UA), VERIFIES an
audio stream is present, overwrites the GCS archive, and resets the transcript stage so the
ingest cron re-transcribes it. It never overwrites the archive with a still-audio-less download.

Run it locally (needs a browser logged into YouTube for cookies), against Cloud SQL via the proxy:

    /tmp/cloud-sql-proxy video-archival-and-content-gen:us-central1:video-archival-and-content-gen-pg --port 5432 &
    export GOOGLE_CLOUD_PROJECT=video-archival-and-content-gen
    export GOOGLE_APPLICATION_CREDENTIALS=infra/vertex-dev-sa.json
    export DB_URL="postgresql+psycopg://app:$(gcloud secrets versions access latest --secret=db-password)@127.0.0.1:5432/perkins"
    export COOKIES_FROM_BROWSER=chrome        # or firefox / chromium
    export FFMPEG_BIN=$(.venv/bin/python -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")
    PYTHONPATH=. .venv/bin/python scripts/rearchive_with_audio.py [VIDEO_ID ...]

With no ids, it auto-detects targets from transcript errors whose message indicates a missing
audio track. Prints a per-video summary.
"""
import os
import sys
import tempfile

from sqlalchemy import or_

from adapters import ffmpeg, storage, yt_dlp
from app.models import IngestionRun, SessionLocal

# Error-message fragments that mean "the archived MP4 has no audio track" (see stt_gcp / ffmpeg).
_NO_AUDIO_MARKERS = ("does not contain any stream", "no audio", "audio-demux")


def _media_bucket() -> str:
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    return f"{project}-media"


def _auto_targets(s) -> list[str]:
    conds = [IngestionRun.last_error.ilike(f"%{m}%") for m in _NO_AUDIO_MARKERS]
    rows = (
        s.query(IngestionRun.video_id)
        .filter(
            IngestionRun.stage == "transcript",
            IngestionRun.status == "error",
            or_(*conds),
        )
        .all()
    )
    return [r[0] for r in rows]


def _reset_transcript(s, vid: str) -> None:
    r = s.query(IngestionRun).filter_by(video_id=vid, stage="transcript").one_or_none()
    if r:
        r.status = "pending"
        r.attempts = 0
        r.last_error = None
        s.add(r)
        s.commit()


def _rearchive(vid: str, bucket: str) -> str:
    """Re-download *vid* with audio and overwrite its GCS archive. Returns a status string."""
    key = f"videos/{vid}.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        path = yt_dlp.pull_video(vid, tmp)  # cookies (COOKIES_FROM_BROWSER) + Chrome UA via adapter
        if not ffmpeg.has_audio(path):
            return "still no audio after re-download (source may be genuinely silent) — NOT uploaded"
        storage.upload_file(path, bucket, key, content_type="video/mp4")
    return "ok"


def main(ids: list[str]) -> None:
    bucket = _media_bucket()
    if not os.getenv("COOKIES_FROM_BROWSER"):
        print("[warn] COOKIES_FROM_BROWSER is unset — YouTube will likely gate on the bot-check.")

    s = SessionLocal()
    try:
        targets = ids or _auto_targets(s)
        if not targets:
            print("no targets — no audio-less archives detected.")
            return
        print(f"re-archiving {len(targets)} video(s) WITH audio: {targets}")
        for vid in targets:
            try:
                status = _rearchive(vid, bucket)
                if status == "ok":
                    _reset_transcript(s, vid)
                    print(f"[ok]   {vid}: re-archived with audio; transcript reset to pending")
                else:
                    print(f"[skip] {vid}: {status}")
            except Exception as e:  # noqa: BLE001 — one bad video must not stop the batch
                print(f"[error] {vid}: {str(e)[:200]}")
    finally:
        s.close()


if __name__ == "__main__":
    main(sys.argv[1:])
