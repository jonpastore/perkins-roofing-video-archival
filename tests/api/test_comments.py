"""Behavioral tests for api/routes/comments.py.

All YouTube fetches and LLM calls are monkeypatched — no live network calls.
Uses a fresh FastAPI app + the shared temp SQLite DB from conftest.py.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import set_verifier
from api.routes.comments import _crawl_guard, router
from app.models import CommentDraft, SessionLocal, Video, init_db


@pytest.fixture(autouse=True)
def reset_crawl_guard():
    """Reset single-flight guard state before each test so cooldown doesn't bleed."""
    _crawl_guard._reset_for_testing()
    yield


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def _admin_client():
    set_verifier(lambda token: {"uid": "u1", "email": "admin@x.com", "role": "admin"})
    return TestClient(_make_app())


def _sales_client():
    set_verifier(lambda token: {"uid": "u2", "email": "sales@x.com", "role": "sales"})
    return TestClient(_make_app())


AUTH = {"Authorization": "Bearer tok"}

_VIDEO_ID = "cmtvid1"


def setup_module(module):
    init_db()
    with SessionLocal() as db:
        db.query(CommentDraft).delete()
        db.commit()
        if not db.query(Video).filter(Video.id == _VIDEO_ID).first():
            db.add(Video(id=_VIDEO_ID, title="Roof Repair Tips"))
            db.commit()


# ---------------------------------------------------------------------------
# GET /comments — list
# ---------------------------------------------------------------------------

class TestListComments:
    def test_empty_list(self):
        c = _admin_client()
        r = c.get("/comments", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "total" in data and "items" in data
        assert data["total"] == 0

    def test_sales_can_read(self):
        c = _sales_client()
        r = c.get("/comments", headers=AUTH)
        assert r.status_code == 200

    def test_filter_by_status(self):
        with SessionLocal() as db:
            db.add(CommentDraft(
                video_id=_VIDEO_ID, comment_id="yt_test_001",
                author="Alice", comment_text="How long does it take?",
                needs_reply=True, status="drafted", draft_reply="Great question!",
            ))
            db.commit()

        c = _admin_client()
        r = c.get("/comments?status=drafted", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        assert all(item["status"] == "drafted" for item in data["items"])

    def test_filter_by_needs_reply_true(self):
        c = _admin_client()
        r = c.get("/comments?needs_reply=true", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert all(item["needs_reply"] is True for item in data["items"])

    def test_filter_by_needs_reply_false(self):
        with SessionLocal() as db:
            db.add(CommentDraft(
                video_id=_VIDEO_ID, comment_id="yt_test_002",
                author="Bob", comment_text="Great video!",
                needs_reply=False, status="pending",
            ))
            db.commit()

        c = _admin_client()
        r = c.get("/comments?needs_reply=false", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert all(item["needs_reply"] is False for item in data["items"])

    def test_pagination(self):
        c = _admin_client()
        r = c.get("/comments?limit=1&offset=0", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert len(data["items"]) <= 1

    def test_video_title_joined(self):
        c = _admin_client()
        r = c.get("/comments?status=drafted", headers=AUTH)
        assert r.status_code == 200
        items = r.json()["items"]
        for item in items:
            if item["video_id"] == _VIDEO_ID:
                assert item["video_title"] == "Roof Repair Tips"


# ---------------------------------------------------------------------------
# POST /comments/{id}/draft — regenerate
# ---------------------------------------------------------------------------

class TestRegenerateDraft:
    def test_regenerate_calls_llm(self, monkeypatch):
        with SessionLocal() as db:
            row = CommentDraft(
                video_id=_VIDEO_ID, comment_id="yt_test_003",
                author="Carol", comment_text="Can you explain the warranty?",
                needs_reply=True, status="pending",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            row_id = row.id

        monkeypatch.setattr("api.routes.comments.chat", lambda prompt, want_json=False: "Thanks for asking! Our warranty covers 10 years.")

        c = _admin_client()
        r = c.post(f"/comments/{row_id}/draft", headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "drafted"
        assert "warranty" in data["draft_reply"].lower() or data["draft_reply"]

    def test_regenerate_404(self):
        c = _admin_client()
        r = c.post("/comments/999999/draft", headers=AUTH)
        assert r.status_code == 404

    def test_sales_cannot_regenerate(self):
        c = _sales_client()
        r = c.post("/comments/1/draft", headers=AUTH)
        assert r.status_code == 403

    def test_llm_empty_reply_raises_502(self, monkeypatch):
        with SessionLocal() as db:
            row = CommentDraft(
                video_id=_VIDEO_ID, comment_id="yt_test_004",
                author="Dan", comment_text="What is the cost?",
                needs_reply=True, status="pending",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            row_id = row.id

        monkeypatch.setattr("api.routes.comments.chat", lambda prompt, want_json=False: "")  # noqa: E501

        c = _admin_client()
        r = c.post(f"/comments/{row_id}/draft", headers=AUTH)
        assert r.status_code == 502


# ---------------------------------------------------------------------------
# PUT /comments/{id} — edit / set status
# ---------------------------------------------------------------------------

class TestUpdateComment:
    def _seed_row(self, comment_id_suffix: str) -> int:
        with SessionLocal() as db:
            row = CommentDraft(
                video_id=_VIDEO_ID, comment_id=f"yt_upd_{comment_id_suffix}",
                author="Ed", comment_text="How long does it take?",
                needs_reply=True, status="drafted", draft_reply="Draft text here.",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row.id

    def test_update_draft_text(self):
        row_id = self._seed_row("a")
        c = _admin_client()
        r = c.put(f"/comments/{row_id}", json={"draft_reply": "Updated reply text."}, headers=AUTH)
        assert r.status_code == 200
        assert r.json()["draft_reply"] == "Updated reply text."

    def test_set_status_ready(self):
        row_id = self._seed_row("b")
        c = _admin_client()
        r = c.put(f"/comments/{row_id}", json={"status": "ready"}, headers=AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "ready"

    def test_set_status_dismissed(self):
        row_id = self._seed_row("c")
        c = _admin_client()
        r = c.put(f"/comments/{row_id}", json={"status": "dismissed"}, headers=AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "dismissed"

    def test_invalid_status_422(self):
        row_id = self._seed_row("d")
        c = _admin_client()
        r = c.put(f"/comments/{row_id}", json={"status": "bogus"}, headers=AUTH)
        assert r.status_code == 422

    def test_update_404(self):
        c = _admin_client()
        r = c.put("/comments/999999", json={"status": "ready"}, headers=AUTH)
        assert r.status_code == 404

    def test_sales_cannot_update(self):
        c = _sales_client()
        r = c.put("/comments/1", json={"status": "ready"}, headers=AUTH)
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# POST /comments/crawl — trigger job
# ---------------------------------------------------------------------------

class TestCrawlEndpoint:
    def _fake_run(self, limit, max_drafts=25, **kwargs):
        return {
            "videos_processed": 1, "comments_upserted": 2,
            "flagged": 1, "drafted": 1, "errors": 0,
        }

    def test_crawl_mocked_fully(self, monkeypatch):
        """Patch the job module directly so the route succeeds without DB/YouTube access."""
        import jobs.crawl_comments as jmod
        monkeypatch.setattr(jmod, "run", self._fake_run)

        c = _admin_client()
        r = c.post("/comments/crawl", json={"limit": 3}, headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert "videos_processed" in data
        assert "errors" in data

    def test_sales_cannot_crawl(self):
        c = _sales_client()
        r = c.post("/comments/crawl", json={"limit": 1}, headers=AUTH)
        assert r.status_code == 403

    def test_crawl_limit_capped(self, monkeypatch):
        """Limit > 100 is capped at 100 server-side."""
        captured = {}
        import jobs.crawl_comments as jmod

        def fake_run(limit, max_drafts=25):
            captured["limit"] = limit
            captured["max_drafts"] = max_drafts
            return {"videos_processed": 0, "comments_upserted": 0,
                    "flagged": 0, "drafted": 0, "errors": 0}

        monkeypatch.setattr(jmod, "run", fake_run)

        c = _admin_client()
        r = c.post("/comments/crawl", json={"limit": 9999}, headers=AUTH)
        assert r.status_code == 200
        assert captured.get("limit", 9999) <= 100

    def test_crawl_max_drafts_passed_through(self, monkeypatch):
        """max_drafts from request body is forwarded to the job."""
        captured = {}
        import jobs.crawl_comments as jmod

        def fake_run(limit, max_drafts=25):
            captured["max_drafts"] = max_drafts
            return {"videos_processed": 0, "comments_upserted": 0,
                    "flagged": 0, "drafted": 0, "errors": 0}

        monkeypatch.setattr(jmod, "run", fake_run)

        c = _admin_client()
        r = c.post("/comments/crawl", json={"limit": 5, "max_drafts": 10}, headers=AUTH)
        assert r.status_code == 200
        assert captured.get("max_drafts") == 10

    def test_crawl_max_drafts_capped(self, monkeypatch):
        """max_drafts > 200 is capped at 200 server-side."""
        captured = {}
        import jobs.crawl_comments as jmod

        def fake_run(limit, max_drafts=25):
            captured["max_drafts"] = max_drafts
            return {"videos_processed": 0, "comments_upserted": 0,
                    "flagged": 0, "drafted": 0, "errors": 0}

        monkeypatch.setattr(jmod, "run", fake_run)

        c = _admin_client()
        r = c.post("/comments/crawl", json={"limit": 5, "max_drafts": 9999}, headers=AUTH)
        assert r.status_code == 200
        assert captured.get("max_drafts", 9999) <= 200

    def test_crawl_errors_in_summary(self, monkeypatch):
        """errors count in response reflects per-comment LLM failures, not just fetch failures."""
        import jobs.crawl_comments as jmod

        monkeypatch.setattr(jmod, "run", lambda limit, max_drafts=25: {
            "videos_processed": 2,
            "comments_upserted": 4,
            "flagged": 3,
            "drafted": 1,
            "errors": 2,  # 2 LLM draft failures
        })

        c = _admin_client()
        r = c.post("/comments/crawl", json={"limit": 5}, headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["errors"] == 2
        assert data["drafted"] == 1  # only 1 succeeded despite 3 flagged

    def test_crawl_budget_stops_at_max_drafts(self, monkeypatch):
        """Simulate job honouring max_drafts=1: drafted <= max_drafts."""
        import jobs.crawl_comments as jmod

        def budget_run(limit, max_drafts=25):
            # Simulate: 10 flagged comments but budget stops at max_drafts
            drafted = min(3, max_drafts)
            return {
                "videos_processed": limit,
                "comments_upserted": 10,
                "flagged": 3,
                "drafted": drafted,
                "errors": 0,
            }

        monkeypatch.setattr(jmod, "run", budget_run)

        c = _admin_client()
        r = c.post("/comments/crawl", json={"limit": 5, "max_drafts": 1}, headers=AUTH)
        assert r.status_code == 200
        data = r.json()
        assert data["drafted"] <= 1


# ---------------------------------------------------------------------------
# POST /comments/{id}/post — E1 safety gate (plan 2026-07-17 Phase 1.0)
# ---------------------------------------------------------------------------

class TestPostReplySafetyGate:
    def _seed(self, text="Thanks! Polyglass is a great choice for that."):
        with SessionLocal() as db:
            row = CommentDraft(
                video_id=_VIDEO_ID, comment_id="yt-c-gate", author="A",
                comment_text="what underlayment?", needs_reply=True,
                draft_reply=text, status="ready",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row.id

    def _cleanup(self):
        with SessionLocal() as db:
            db.query(CommentDraft).filter(CommentDraft.comment_id == "yt-c-gate").delete()
            db.commit()

    def test_blocked_reply_never_posts(self, monkeypatch):
        # Gate fails → 422, post_reply NOT called, status unchanged.
        rid = self._seed()
        try:
            class _Fail:
                passed = False
                reason = "unprofessional tone"
            monkeypatch.setattr("adapters.safety.run_gate", lambda text, kind: _Fail())
            called = {}
            monkeypatch.setattr(
                "adapters.youtube_comments.post_reply",
                lambda cid, text: called.setdefault("posted", True),
            )
            r = _admin_client().post(f"/comments/{rid}/post", headers=AUTH)
            assert r.status_code == 422
            assert "safety gate" in r.json()["detail"]
            assert "posted" not in called
            with SessionLocal() as db:
                assert db.get(CommentDraft, rid).status == "ready"
        finally:
            self._cleanup()

    def test_clean_reply_posts(self, monkeypatch):
        rid = self._seed()
        try:
            class _Pass:
                passed = True
                reason = ""
            monkeypatch.setattr("adapters.safety.run_gate", lambda text, kind: _Pass())
            monkeypatch.setattr("adapters.youtube_comments.post_reply", lambda cid, text: {"id": "r1"})
            r = _admin_client().post(f"/comments/{rid}/post", headers=AUTH)
            assert r.status_code == 200
            with SessionLocal() as db:
                assert db.get(CommentDraft, rid).status == "posted"
        finally:
            self._cleanup()
