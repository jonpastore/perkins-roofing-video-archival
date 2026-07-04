"""Behavioral validation for the archive job.

Hermetic: monkeypatches adapters.yt_dlp.pull_video and adapters.storage.*,
uses a temp SQLite DB, seeds two Video rows, runs jobs.archive_job.run(),
and asserts both rows receive archive_uri. Re-runs to verify idempotency
(second run must skip both rows, not re-download).

Usage:
    PYTHONPATH=. .venv/bin/python scripts/validate_archive.py
"""
from __future__ import annotations

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import os
import tempfile

# ── 0. Point to a throwaway SQLite DB before any app.models import ───────────
_tmp_db_dir = tempfile.mkdtemp()
_tmp_db_path = os.path.join(_tmp_db_dir, "validate_archive.db")
os.environ["DB_URL"] = f"sqlite:///{_tmp_db_path}"
os.environ["GOOGLE_CLOUD_PROJECT"] = "test-project"

# ── 1. Bootstrap schema ───────────────────────────────────────────────────────
from app.models import Base, SessionLocal, Video, engine  # noqa: E402

Base.metadata.create_all(engine)

# ── 2. Seed two Video rows (no archive_uri) ───────────────────────────────────
_db = SessionLocal()
_db.add(Video(id="vid_aaa", title="Video A", url="https://youtu.be/vid_aaa"))
_db.add(Video(id="vid_bbb", title="Video B", url="https://youtu.be/vid_bbb"))
_db.commit()
_db.close()

# ── 3. Monkeypatch adapters ───────────────────────────────────────────────────
import adapters.storage  # noqa: E402
import adapters.yt_dlp  # noqa: E402

_uploaded: dict[str, str] = {}   # key -> gs:// uri
_downloaded: list[str] = []      # video_ids that were "pulled"


def _fake_pull_video(video_id: str, dst: str) -> str:
    """Write a tiny placeholder file and return its path."""
    path = os.path.join(dst, f"{video_id}.mp4")
    with open(path, "wb") as fh:
        fh.write(b"FAKE_MP4_CONTENT")
    _downloaded.append(video_id)
    return path


def _fake_upload_file(
    local_path: str,
    bucket: str,
    key: str,
    content_type: str = "video/mp4",
) -> str:
    uri = f"gs://{bucket}/{key}"
    _uploaded[key] = os.path.getsize(local_path)  # store size for the integrity check
    return uri


def _fake_object_size(bucket: str, key: str) -> int:
    return _uploaded.get(key, -1)


adapters.yt_dlp.pull_video = _fake_pull_video  # type: ignore[assignment]
adapters.storage.upload_file = _fake_upload_file  # type: ignore[assignment]
adapters.storage.object_size = _fake_object_size  # type: ignore[assignment]

# Patch references that archive_job will import lazily
import jobs.archive_job  # noqa: E402  (import after env vars are set)

# ── 4. First run — expect both videos to be archived ─────────────────────────
result1 = jobs.archive_job.run()
assert result1["archived"] == 2, f"Expected archived=2, got {result1}"
assert result1["skipped"] == 0, f"Expected skipped=0, got {result1}"
assert result1["errored"] == 0, f"Expected errored=0, got {result1}"
assert result1["total"] == 2, f"Expected total=2, got {result1}"
assert len(_downloaded) == 2, f"Expected 2 downloads, got {_downloaded}"

# Verify DB rows were updated
_db = SessionLocal()
_vid_a = _db.get(Video, "vid_aaa")
_vid_b = _db.get(Video, "vid_bbb")
assert _vid_a is not None and _vid_a.archive_uri == "gs://test-project-media/videos/vid_aaa.mp4", (
    f"vid_aaa archive_uri wrong: {_vid_a and _vid_a.archive_uri!r}"
)
assert _vid_b is not None and _vid_b.archive_uri == "gs://test-project-media/videos/vid_bbb.mp4", (
    f"vid_bbb archive_uri wrong: {_vid_b and _vid_b.archive_uri!r}"
)
_db.close()

# ── 5. Second run — idempotency: both rows now have archive_uri, must skip ────
_downloaded.clear()
result2 = jobs.archive_job.run()
assert result2["archived"] == 0, f"Expected archived=0 on re-run, got {result2}"
assert result2["total"] == 0, f"Expected total=0 on re-run (no unarchived rows), got {result2}"
assert len(_downloaded) == 0, f"Expected no downloads on re-run, got {_downloaded}"

print("ARCHIVE JOB OK")
