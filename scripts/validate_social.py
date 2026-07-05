"""Hermetic validation for Wave-4 social publishing pipeline.

Monkeypatches both platform publishers + signed_get_url, seeds an
awaiting_social reel, runs social_job.run(), then asserts:
  - external_id stored on per-platform SocialPost rows
  - ScheduledContent.status advances to "published"
  - Idempotent re-run does NOT double-post (published count = 0)

Usage:
    PYTHONPATH=. .venv/bin/python scripts/validate_social.py
"""
from __future__ import annotations

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import os
import sys
import tempfile
import types

# ── 0. Fresh temp SQLite DB ──────────────────────────────────────────────────
_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_db_file.close()
os.environ["DB_URL"] = f"sqlite:///{_db_file.name}"

# Ensure social creds env vars exist so social_job does not short-circuit
os.environ.setdefault("IG_USER_ID", "fake_ig_user")
os.environ.setdefault("META_SYSTEM_USER_TOKEN", "fake_meta_token")
os.environ.setdefault("TIKTOK_ACCESS_TOKEN", "fake_tt_token")
os.environ.setdefault("TIKTOK_OPEN_ID", "fake_tt_oid")

# ── 1. Stub google-cloud-storage (signed_get_url) ───────────────────────────
_gcs_stub = types.ModuleType("google.cloud.storage")

class _FakeBlob:
    def __init__(self, key):
        self._key = key
    def generate_signed_url(self, **_kw):
        return f"https://signed.example.com/{self._key}?sig=fake"

class _FakeBucket:
    def __init__(self, name):
        self._name = name
    def blob(self, key):
        return _FakeBlob(key)

class _FakeClient:
    def bucket(self, name):
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

# ── 2. Stub platform publishers ──────────────────────────────────────────────

# Track call counts to verify idempotency
_publish_calls: dict[str, int] = {"instagram": 0, "tiktok": 0}

class _FakeIgPublisher:
    def publish(self, *, video_url, caption, idempotency_key):
        _publish_calls["instagram"] += 1
        return f"ig_ext_{_publish_calls['instagram']}"

class _FakeTikTokPublisher:
    def publish(self, *, video_url, caption, idempotency_key):
        _publish_calls["tiktok"] += 1
        return f"tt_ext_{_publish_calls['tiktok']}"

_meta_ig_stub = types.ModuleType("adapters.meta_ig")
_meta_ig_stub.IgPublisher = _FakeIgPublisher

_tiktok_stub = types.ModuleType("adapters.tiktok")
_tiktok_stub.TikTokPublisher = _FakeTikTokPublisher

sys.modules["adapters.meta_ig"] = _meta_ig_stub
sys.modules["adapters.tiktok"] = _tiktok_stub

# ── 3. Bootstrap DB and seed data ────────────────────────────────────────────
from app.models import (  # noqa: E402
    Base,
    ScheduledContent,
    SessionLocal,
    SocialPost,
    engine,
)

Base.metadata.create_all(engine)

db = SessionLocal()

# Seed a SocialPost (simulating what render_job creates)
post = SocialPost(
    series_id=1,
    part=0,
    platform="instagram,tiktok",
    gcs_url="https://storage.googleapis.com/perkins-test-reels/1/0.mp4",
    status="rendered",
)
db.add(post)
db.flush()

# Seed the ScheduledContent row (simulating what promote_job sets)
sched = ScheduledContent(
    kind="reel",
    ref_id=str(post.id),
    publish_at=None,
    status="awaiting_social",
    target="instagram,tiktok",
)
db.add(sched)
db.commit()
post_id = post.id
sched_id = sched.id
db.close()

print(f"[seed] SocialPost id={post_id}  ScheduledContent id={sched_id}")

# ── 4. Run social_job.run() ──────────────────────────────────────────────────
from jobs.social_job import run as social_run  # noqa: E402

result = social_run()
print(f"[social_job] first run: {result}")
assert result["published"] == 2, f"Expected 2 published (1 IG + 1 TikTok), got {result}"
assert result["errored"] == 0, f"Expected 0 errors, got {result}"

# ── 5. Verify external_ids stored on per-platform rows ───────────────────────
db = SessionLocal()
ig_posts = (
    db.query(SocialPost)
    .filter(SocialPost.series_id == 1, SocialPost.part == 0, SocialPost.platform == "instagram")
    .all()
)
tt_posts = (
    db.query(SocialPost)
    .filter(SocialPost.series_id == 1, SocialPost.part == 0, SocialPost.platform == "tiktok")
    .all()
)

assert len(ig_posts) >= 1, "No instagram SocialPost row found"
assert ig_posts[0].external_id is not None, "IG external_id is None"
assert ig_posts[0].status == "posted", f"IG status wrong: {ig_posts[0].status!r}"

assert len(tt_posts) >= 1, "No tiktok SocialPost row found"
assert tt_posts[0].external_id is not None, "TikTok external_id is None"
assert tt_posts[0].status == "posted", f"TikTok status wrong: {tt_posts[0].status!r}"

sc = db.get(ScheduledContent, sched_id)
assert sc.status == "published", f"ScheduledContent status expected 'published', got {sc.status!r}"
db.close()

print("[verify] external_ids stored, ScheduledContent=published — PASS")

# ── 6. Idempotency: second run must NOT double-post ──────────────────────────
_before_ig = _publish_calls["instagram"]
_before_tt = _publish_calls["tiktok"]

result2 = social_run()
print(f"[social_job] second run (idempotent): {result2}")

assert _publish_calls["instagram"] == _before_ig, (
    f"IG publisher called again on re-run! calls={_publish_calls['instagram']}"
)
assert _publish_calls["tiktok"] == _before_tt, (
    f"TikTok publisher called again on re-run! calls={_publish_calls['tiktok']}"
)
assert result2["published"] == 0, f"Expected 0 published on re-run, got {result2['published']}"

print("[idempotency] no double-post on re-run — PASS")

print("\nSOCIAL OK")
