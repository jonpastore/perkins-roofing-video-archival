"""Hermetic validation for the Wave-3 propose→approve→render→promote pipeline.

Exercises the full flow with fakes (monkeypatched pull_video + GCS upload)
and an in-memory SQLite DB.  Asserts:
  - propose_series_job.run() inserts a MiniSeries row.
  - After admin approval (approved=1), render_job.run() produces a SocialPost
    with a non-null gcs_url AND a ScheduledContent(kind="reel") with a non-null
    publish_at.
  - promote_job.run() does NOT mark the reel ScheduledContent as "published"
    (Wave-4 is not yet wired).

Usage:
    PYTHONPATH=. .venv/bin/python scripts/validate_render_pipeline.py
"""
from __future__ import annotations

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import os
import sys
import tempfile
import types

# ── 0. Point at a fresh temp-file SQLite DB before any model import ──────────
# Must use a file-based URI so multiple connections (SessionLocal calls) share
# the same DB — sqlite:///:memory: gives each connection its own empty DB.
_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_db_file.close()
os.environ["DB_URL"] = f"sqlite:///{_db_file.name}"

# ── 1. Stub out heavy adapters before any job import ─────────────────────────

# Stub adapters.yt_dlp so pull_video returns a synthetic clip path.
_yt_dlp_stub = types.ModuleType("adapters.yt_dlp")
def _fake_pull_video(video_id: str, dest: str) -> str:
    """Write a tiny valid MP4 via imageio-ffmpeg lavfi, return its path."""
    import subprocess  # noqa: PLC0415

    import imageio_ffmpeg  # noqa: PLC0415
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    out = os.path.join(dest, f"{video_id}.mp4")
    subprocess.run(
        [
            ffmpeg, "-y",
            "-f", "lavfi", "-i", "color=c=blue:size=1920x1080:rate=30:duration=4",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-shortest",
            out,
        ],
        check=True,
        capture_output=True,
    )
    return out
_yt_dlp_stub.pull_video = _fake_pull_video
sys.modules["adapters.yt_dlp"] = _yt_dlp_stub

# Stub google-cloud-storage so GCS upload just copies the file locally.
_gcs_fake_bucket: dict[str, str] = {}

_gcs_stub = types.ModuleType("google.cloud.storage")
class _FakeBlob:
    def __init__(self, key: str) -> None:
        self._key = key
    def upload_from_filename(self, path: str, **_kw: object) -> None:
        import shutil  # noqa: PLC0415
        _gcs_fake_bucket[self._key] = path
        shutil.copy(path, path + ".gcs")
    def make_public(self) -> None:
        pass

class _FakeBucket:
    def __init__(self, name: str) -> None:
        self._name = name
    def blob(self, key: str) -> _FakeBlob:
        return _FakeBlob(key)

class _FakeClient:
    def bucket(self, name: str) -> _FakeBucket:
        return _FakeBucket(name)

_gcs_stub.Client = _FakeClient

_gcs_exceptions_stub = types.ModuleType("google.cloud.exceptions")
class _FakeGoogleCloudError(Exception):
    pass
_gcs_exceptions_stub.GoogleCloudError = _FakeGoogleCloudError

_google_stub = types.ModuleType("google")
_google_cloud_stub = types.ModuleType("google.cloud")
_google_stub.cloud = _google_cloud_stub
_google_cloud_stub.storage = _gcs_stub
_google_cloud_stub.exceptions = _gcs_exceptions_stub
sys.modules.setdefault("google", _google_stub)
sys.modules["google.cloud"] = _google_cloud_stub
sys.modules["google.cloud.storage"] = _gcs_stub
sys.modules["google.cloud.exceptions"] = _gcs_exceptions_stub

# Set a fake project so _reels_bucket() doesn't raise.
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "perkins-test")

# ── 2. Point ffmpeg at the imageio-ffmpeg bundled binary ─────────────────────
import imageio_ffmpeg as _iio_ffmpeg  # noqa: E402

_FFMPEG_EXE = _iio_ffmpeg.get_ffmpeg_exe()
os.environ["FFMPEG_BIN"] = _FFMPEG_EXE

# Monkeypatch make_card: the bundled ffmpeg lacks libfreetype (drawtext).
# In CI/validate we generate a solid-colour PNG instead — same dimensions,
# no text rendering needed to prove the pipeline wiring.
import subprocess as _subprocess  # noqa: E402

import adapters.ffmpeg as _ffmpeg_adapter  # noqa: E402


def _fake_make_card(text: str, out: str, *, seconds: float = 3, bg: str = "black", fg: str = "white") -> str:
    """Solid-colour substitute for make_card when drawtext is unavailable."""
    _subprocess.run(
        [
            _FFMPEG_EXE, "-y",
            "-f", "lavfi", "-i",
            f"color=c={bg}:size=1080x1920:rate=1:duration=1",
            "-vframes", "1",
            out,
        ],
        check=True,
        capture_output=True,
    )
    return out

_ffmpeg_adapter.make_card = _fake_make_card

# ── 3. Bootstrap the in-memory DB ────────────────────────────────────────────
from app.models import (  # noqa: E402
    Base,
    GraphNode,
    MiniSeries,
    ScheduledContent,
    SessionLocal,
    SocialPost,
    Video,
    engine,
)

Base.metadata.create_all(engine)

# ── 4. Seed one Video with GraphNode rows ────────────────────────────────────
db = SessionLocal()
video = Video(
    id="test-vid-1",
    title="Roof Repair 101",
    duration=120.0,
    upload_date="2026-01-01",
    views=1000,
    likes=50,
    comments=10,
    url="https://youtube.com/watch?v=test-vid-1",
)
db.add(video)
for i, (label, start) in enumerate([
    ("Introduction", 0.0),
    ("Shingles",     25.0),
    ("Flashing",     50.0),
    ("Gutters",      75.0),
    ("Warranty",     100.0),
]):
    db.add(GraphNode(video_id="test-vid-1", kind="topics", label=label, detail="", start=start))
db.commit()
db.close()

# ── 5. propose_series_job.run() ───────────────────────────────────────────────
from jobs.propose_series_job import run as propose_run  # noqa: E402

result = propose_run(limit=5)
print(f"[propose] {result}")
assert result["proposed"] == 1, f"Expected 1 proposed, got {result}"
assert result["skipped"] == 0
assert result["errored"] == 0

# Verify MiniSeries row
db = SessionLocal()
ms = db.query(MiniSeries).filter(MiniSeries.video_id == "test-vid-1").first()
assert ms is not None, "MiniSeries row not found"
assert ms.approved == 0, "MiniSeries should default to unapproved"
assert isinstance(ms.parts_json, list) and len(ms.parts_json) >= 4
series_id = ms.id
db.close()

# Idempotency: run again — should skip, not duplicate
result2 = propose_run(limit=5)
assert result2["proposed"] == 0, "Second run should produce 0 new rows (idempotent)"
assert result2["skipped"] == 1

print("[propose] PASS — MiniSeries created + idempotency confirmed")

# ── 6. Simulate admin approval ────────────────────────────────────────────────
db = SessionLocal()
ms = db.get(MiniSeries, series_id)
ms.approved = 1
db.commit()
db.close()

# ── 7. render_job.run() ───────────────────────────────────────────────────────
from jobs.render_job import run as render_run  # noqa: E402

render_result = render_run(limit=1)
print(f"[render] {render_result}")
assert render_result["errored"] == 0, f"render_job had errors: {render_result}"
assert render_result["rendered"] > 0, "Expected at least one part rendered"

# Verify SocialPost rows exist with non-null gcs_url
db = SessionLocal()
posts = db.query(SocialPost).filter(SocialPost.series_id == series_id).all()
assert len(posts) > 0, "No SocialPost rows created"
for p in posts:
    assert p.gcs_url is not None, f"SocialPost id={p.id} has null gcs_url"
    assert p.platform == "instagram,tiktok", f"SocialPost id={p.id} has wrong platform: {p.platform!r}"

# Verify ScheduledContent rows with kind=reel and non-null publish_at
scheds = db.query(ScheduledContent).filter(ScheduledContent.kind == "reel").all()
assert len(scheds) > 0, "No ScheduledContent(kind=reel) rows created"
for sc in scheds:
    assert sc.publish_at is not None, f"ScheduledContent id={sc.id} has null publish_at"
    assert sc.target == "instagram,tiktok", f"ScheduledContent id={sc.id} has wrong target: {sc.target!r}"
    assert sc.status == "scheduled", f"ScheduledContent id={sc.id} wrong status: {sc.status!r}"

db.close()
print("[render] PASS — SocialPost + ScheduledContent(reel, publish_at NOT NULL) created")

# ── 8. Idempotency: second render run should render nothing new ───────────────
# run() pre-filters already-rendered parts (SocialPost.gcs_url IS NOT NULL), so
# work list is empty → rendered=0, skipped=0, errored=0.
render_result2 = render_run(limit=1)
assert render_result2["rendered"] == 0, "Second render run should render 0 (idempotent)"
assert render_result2["errored"] == 0, "Second render run should have 0 errors"
print("[render] PASS — second run correctly no-ops (idempotent)")

# ── 9. promote_job.run() — reels must NOT be marked published ─────────────────
# Stub wordpress adapter so promote_job doesn't try real HTTP.
_wp_stub = types.ModuleType("adapters.wordpress")
_wp_stub.update_status = lambda *_a, **_kw: None
sys.modules["adapters.wordpress"] = _wp_stub

from datetime import datetime  # noqa: E402

from jobs.promote_job import run as promote_run  # noqa: E402

promote_result = promote_run(now=datetime.utcnow())
print(f"[promote] {promote_result}")

# After promote, reels move to a distinct 'awaiting_social' state (NOT 'published', and NOT
# still 'scheduled' — so scheduler.due won't re-select them every cron tick). Wave-4 publishes.
db = SessionLocal()
scheds_after = db.query(ScheduledContent).filter(ScheduledContent.kind == "reel").all()
for sc in scheds_after:
    assert sc.status == "awaiting_social", (
        f"ScheduledContent id={sc.id} (reel) expected 'awaiting_social', got {sc.status!r}"
    )
db.close()

# And a second promote run must NOT re-select the reel (due() ignores awaiting_social).
res2 = promote_run()
assert res2["promoted"] == 0, f"reel was re-promoted on second run (re-selection loop): {res2}"
print("[promote] PASS — reel moved to awaiting_social, not re-selected on rerun (Wave-4 pending)")

print("\nOK")
