"""Negative-path tests for the content API routes: articles, archive, clips, video,
topics, faq, comments, email. (suggestions.py has no POST/PUT/PATCH/DELETE endpoints —
both its routes are GET, so no write-endpoint negative tests apply there.)

For every POST/PUT/PATCH/DELETE endpoint in those files, covers whichever of these are
not already exercised by the existing suite (test_articles.py, test_archive.py,
test_archive_kpis.py, test_clips.py, test_clips_render.py,
test_video_routes.py, test_video_repropose.py, test_topics.py, test_faq.py,
test_comments.py, test_email_features.py, test_email_draft.py). This worktree's
clips.py has no /clips/search endpoint (a later commit on main adds it) — no
negative tests for it are included here.
  1. missing required field -> 422
  2. wrong type for a field -> 422
  3. nonexistent resource id -> 404 (authed, valid body)
  4. unauthenticated -> 401
  5. insufficient role -> 403

FastAPI resolves the require_role dependency before body validation, so 401/403 tests
never need a valid body. 422 (missing/wrong-type) tests only need an authed allowed-role
client — pydantic validation runs before the handler touches the DB, so no real
underlying resource is needed even when the path references an id. 404 tests use a
schema-valid body with a resource id that cannot exist (either a random string or a
huge int) so the lookup inside the handler genuinely misses.
"""
import io

import pytest
from fastapi.testclient import TestClient

import api.app as appmod
from api.auth import set_verifier
from app.models import init_db

AUTH = {"Authorization": "Bearer x"}

NO_SLUG = "zzz-negtest-missing-slug"
NO_VIDEO = "zzz-negtest-missing-video"
NO_ID = 999999999


@pytest.fixture(autouse=True)
def _setup_db():
    init_db()


def _client(claims):
    set_verifier(lambda t: claims)
    return TestClient(appmod.app)


@pytest.fixture()
def admin_client():
    return _client({"uid": "u1", "email": "admin@x.com", "role": "admin", "email_verified": True})


@pytest.fixture()
def sales_client():
    return _client({"uid": "u2", "email": "sales@x.com", "role": "sales", "email_verified": True})


@pytest.fixture()
def web_admin_client():
    return _client({"uid": "u3", "email": "webadmin@x.com", "role": "web_admin", "email_verified": True})


@pytest.fixture()
def unauth_client():
    set_verifier(None)
    return TestClient(appmod.app)


def _call(client, method, path, body):
    fn = getattr(client, method)
    if body is None:
        return fn(path, headers=AUTH)
    return fn(path, json=body, headers=AUTH)


# ---------------------------------------------------------------------------
# 4) unauthenticated -> 401  (no Authorization header at all)
# ---------------------------------------------------------------------------
UNAUTH_401 = [
    ("articles_create", "post", "/articles", {"title": "X"}),
    ("articles_update", "put", f"/articles/{NO_SLUG}", {"title": "X"}),
    ("articles_delete", "delete", f"/articles/{NO_SLUG}", None),
    ("articles_reprocess", "post", f"/articles/{NO_SLUG}/reprocess", None),
    ("articles_fix_seo", "post", f"/articles/{NO_SLUG}/fix-seo", {"check_key": "x"}),
    ("articles_publish", "post", f"/articles/{NO_SLUG}/publish", None),
    ("archive_rename", "post", f"/archive/{NO_VIDEO}/rename", {"title": "X"}),
    ("archive_suggest_name", "post", f"/archive/{NO_VIDEO}/suggest-name", None),
    ("archive_hide", "post", f"/archive/{NO_VIDEO}/hide", None),
    ("archive_unhide", "post", f"/archive/{NO_VIDEO}/unhide", None),
    ("clips_render_spec_put", "put", f"/clips/{NO_ID}/render_spec", {}),
    ("clips_render", "post", f"/clips/{NO_ID}/render", None),
    ("video_propose_topic_series", "post", "/video/propose-topic-series", {}),
    ("faq_mine", "post", "/faq/mine", {}),
    ("faq_answer_one", "post", f"/faq/{NO_ID}/answer", None),
    ("faq_answer_batch", "post", "/faq/answer-batch", {}),
    ("faq_publish_wordpress", "post", "/faq/publish-wordpress", None),
    ("comments_draft", "post", f"/comments/{NO_ID}/draft", None),
    ("comments_update", "put", f"/comments/{NO_ID}", {"status": "ready"}),
    ("comments_post", "post", f"/comments/{NO_ID}/post", None),
    ("email_template_create", "post", "/email/templates",
     {"name": "n", "subject": "s", "body": "b"}),
    ("email_template_update", "put", "/email/templates/1",
     {"name": "n", "subject": "s", "body": "b"}),
    ("email_template_delete", "delete", "/email/templates/1", None),
    ("email_proof", "post", "/email/proof", {"draft": "x"}),
    ("email_send", "post", "/email/send", {"to": "a@b.com", "subject": "s", "html": "<p>x</p>"}),
    ("email_preview", "post", "/email/preview", {"to": "a@b.com", "subject": "s", "html": "<p>x</p>"}),
    ("email_draft", "post", "/email/draft",
     {"sources": [{"title": "t", "snippet": "s", "url": "http://x"}]}),
]


@pytest.mark.parametrize("name,method,path,body", UNAUTH_401, ids=[c[0] for c in UNAUTH_401])
def test_unauthenticated_returns_401(unauth_client, name, method, path, body):
    r = _call(unauth_client, method, path, body)
    assert r.status_code == 401, f"{name}: expected 401, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# 5) insufficient role -> 403
# ---------------------------------------------------------------------------
FORBIDDEN_SALES = [
    ("articles_fix_seo", "post", f"/articles/{NO_SLUG}/fix-seo", {"check_key": "x"}),
    ("archive_rename", "post", f"/archive/{NO_VIDEO}/rename", {"title": "X"}),
    ("archive_suggest_name", "post", f"/archive/{NO_VIDEO}/suggest-name", None),
    ("archive_hide", "post", f"/archive/{NO_VIDEO}/hide", None),
    ("archive_unhide", "post", f"/archive/{NO_VIDEO}/unhide", None),
    ("clips_render_spec_put", "put", f"/clips/{NO_ID}/render_spec", {}),
    ("clips_render", "post", f"/clips/{NO_ID}/render", None),
    ("video_propose_topic_series", "post", "/video/propose-topic-series", {}),
    ("comments_post", "post", f"/comments/{NO_ID}/post", None),
]


@pytest.mark.parametrize("name,method,path,body", FORBIDDEN_SALES, ids=[c[0] for c in FORBIDDEN_SALES])
def test_sales_role_forbidden_returns_403(sales_client, name, method, path, body):
    r = _call(sales_client, method, path, body)
    assert r.status_code == 403, f"{name}: expected 403, got {r.status_code}: {r.text}"


FORBIDDEN_WEBADMIN = [
    ("email_template_create", "post", "/email/templates",
     {"name": "n", "subject": "s", "body": "b"}),
    ("email_template_update", "put", "/email/templates/1",
     {"name": "n", "subject": "s", "body": "b"}),
    ("email_template_delete", "delete", "/email/templates/1", None),
    ("email_proof", "post", "/email/proof", {"draft": "x"}),
    ("email_send", "post", "/email/send", {"to": "a@b.com", "subject": "s", "html": "<p>x</p>"}),
]


@pytest.mark.parametrize("name,method,path,body", FORBIDDEN_WEBADMIN, ids=[c[0] for c in FORBIDDEN_WEBADMIN])
def test_web_admin_role_forbidden_returns_403(web_admin_client, name, method, path, body):
    """web_admin lacks manage_templates/email_compose/email_proof/email_send (sales has
    them, so sales can't be used as the insufficient-role tester for this router)."""
    r = _call(web_admin_client, method, path, body)
    assert r.status_code == 403, f"{name}: expected 403, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# 3) nonexistent resource id -> 404 (authed, valid body)
# ---------------------------------------------------------------------------
NOTFOUND_404 = [
    ("articles_fix_seo", "post", f"/articles/{NO_SLUG}/fix-seo", {"check_key": "any_check"}),
    ("archive_rename", "post", f"/archive/{NO_VIDEO}/rename", {"title": "New Name"}),
    ("archive_suggest_name", "post", f"/archive/{NO_VIDEO}/suggest-name", None),
    ("archive_hide", "post", f"/archive/{NO_VIDEO}/hide", None),
    ("archive_unhide", "post", f"/archive/{NO_VIDEO}/unhide", None),
    ("clips_render_spec_put", "put", f"/clips/{NO_ID}/render_spec", {}),
    ("comments_post", "post", f"/comments/{NO_ID}/post", None),
    ("email_template_update", "put", f"/email/templates/{NO_ID}",
     {"name": "n", "subject": "s", "body": "b"}),
    ("email_template_delete", "delete", f"/email/templates/{NO_ID}", None),
]


@pytest.mark.parametrize("name,method,path,body", NOTFOUND_404, ids=[c[0] for c in NOTFOUND_404])
def test_nonexistent_id_returns_404(admin_client, name, method, path, body):
    r = _call(admin_client, method, path, body)
    assert r.status_code == 404, f"{name}: expected 404, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# 1) missing required field -> 422
# ---------------------------------------------------------------------------
MISSING_FIELD_422 = [
    ("articles_create_no_title", "post", "/articles", {}),
    ("articles_fix_seo_no_check_key", "post", f"/articles/{NO_SLUG}/fix-seo", {}),
    ("archive_rename_no_title", "post", f"/archive/{NO_VIDEO}/rename", {}),
    ("clips_save_no_title", "post", "/clips/save",
     {"video_id": "x", "parts": [{"title": "t", "start": 0, "end": 1}]}),
    ("topics_generate_no_topic", "post", "/topics/generate-article", {}),
    ("email_template_create_no_name", "post", "/email/templates", {"subject": "s", "body": "b"}),
    ("email_template_update_no_name", "put", "/email/templates/1", {"subject": "s", "body": "b"}),
    ("email_proof_no_draft", "post", "/email/proof", {}),
    ("email_send_no_to", "post", "/email/send", {"subject": "s", "html": "<p>x</p>"}),
    ("email_preview_no_to", "post", "/email/preview", {"subject": "s", "html": "<p>x</p>"}),
    ("email_draft_no_sources", "post", "/email/draft", {}),
]


@pytest.mark.parametrize("name,method,path,body", MISSING_FIELD_422, ids=[c[0] for c in MISSING_FIELD_422])
def test_missing_required_field_returns_422(admin_client, name, method, path, body):
    r = _call(admin_client, method, path, body)
    assert r.status_code == 422, f"{name}: expected 422, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# 2) wrong type for a field -> 422
# ---------------------------------------------------------------------------
WRONGTYPE_422 = [
    ("articles_create_title_int", "post", "/articles", {"title": 123}),
    ("articles_update_publish_at_bad_date", "put", f"/articles/{NO_SLUG}",
     {"publish_at": "not-a-date"}),
    ("articles_fix_seo_check_key_int", "post", f"/articles/{NO_SLUG}/fix-seo", {"check_key": 123}),
    ("archive_rename_title_int", "post", f"/archive/{NO_VIDEO}/rename", {"title": 123}),
    ("archive_poll_kpis_limit_str", "post", "/archive/poll-kpis", {"limit": "abc"}),
    ("clips_suggest_count_str", "post", "/clips/suggest", {"video_id": "x", "count": "abc"}),
    ("clips_save_parts_not_list", "post", "/clips/save",
     {"video_id": "x", "title": "t", "parts": "not-a-list"}),
    ("clips_render_spec_captions_not_dict", "put", f"/clips/{NO_ID}/render_spec",
     {"captions": "not-a-dict"}),
    ("video_propose_topics_not_int", "post", "/video/propose-topic-series", {"topics": "not-an-int"}),
    ("video_approve_parts_not_list", "post", f"/video/{NO_ID}/approve", {"parts": "not-a-list"}),
    ("topics_generate_topic_int", "post", "/topics/generate-article", {"topic": 123}),
    ("faq_mine_limit_str", "post", "/faq/mine", {"limit": "abc"}),
    ("faq_answer_batch_limit_str", "post", "/faq/answer-batch", {"limit": "abc"}),
    ("comments_update_status_int", "put", f"/comments/{NO_ID}", {"status": 123}),
    ("comments_crawl_limit_str", "post", "/comments/crawl", {"limit": "abc"}),
    ("email_template_create_subject_int", "post", "/email/templates",
     {"name": "n", "subject": 123, "body": "b"}),
    ("email_template_update_subject_int", "put", "/email/templates/1",
     {"name": "n", "subject": 123, "body": "b"}),
    ("email_proof_draft_int", "post", "/email/proof", {"draft": 123}),
    ("email_send_bad_email", "post", "/email/send",
     {"to": "not-an-email", "subject": "s", "html": "<p>x</p>"}),
    ("email_preview_bad_email", "post", "/email/preview",
     {"to": "not-an-email", "subject": "s", "html": "<p>x</p>"}),
    ("email_draft_sources_not_list", "post", "/email/draft", {"sources": "not-a-list"}),
]


@pytest.mark.parametrize("name,method,path,body", WRONGTYPE_422, ids=[c[0] for c in WRONGTYPE_422])
def test_wrong_type_field_returns_422(admin_client, name, method, path, body):
    r = _call(admin_client, method, path, body)
    assert r.status_code == 422, f"{name}: expected 422, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# Clips brand-scene / brand-video uploads — multipart, so tested standalone
# rather than via the generic JSON tables above.
# ---------------------------------------------------------------------------
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 16


def test_upload_brand_scene_401_no_token(unauth_client):
    r = unauth_client.post(
        "/clips/upload-brand-scene?scene=title",
        files={"file": ("t.png", io.BytesIO(_PNG_BYTES), "image/png")},
    )
    assert r.status_code == 401, r.text


def test_upload_brand_scene_403_sales(sales_client):
    r = sales_client.post(
        "/clips/upload-brand-scene?scene=title",
        files={"file": ("t.png", io.BytesIO(_PNG_BYTES), "image/png")},
        headers=AUTH,
    )
    assert r.status_code == 403, r.text


def test_upload_brand_scene_422_missing_scene_and_file(admin_client):
    r = admin_client.post("/clips/upload-brand-scene", headers=AUTH)
    assert r.status_code == 422, r.text


def test_upload_brand_scene_422_invalid_scene_value(admin_client):
    r = admin_client.post(
        "/clips/upload-brand-scene?scene=bogus",
        files={"file": ("t.png", io.BytesIO(_PNG_BYTES), "image/png")},
        headers=AUTH,
    )
    assert r.status_code == 422, r.text


def test_upload_brand_video_401_no_token(unauth_client):
    r = unauth_client.post(
        "/clips/upload-brand-video?scene=intro",
        files={"file": ("t.mp4", io.BytesIO(_MP4_BYTES), "video/mp4")},
    )
    assert r.status_code == 401, r.text


def test_upload_brand_video_403_sales(sales_client):
    r = sales_client.post(
        "/clips/upload-brand-video?scene=intro",
        files={"file": ("t.mp4", io.BytesIO(_MP4_BYTES), "video/mp4")},
        headers=AUTH,
    )
    assert r.status_code == 403, r.text


def test_upload_brand_video_422_missing_scene_and_file(admin_client):
    r = admin_client.post("/clips/upload-brand-video", headers=AUTH)
    assert r.status_code == 422, r.text


def test_upload_brand_video_422_invalid_scene_value(admin_client):
    r = admin_client.post(
        "/clips/upload-brand-video?scene=bogus",
        files={"file": ("t.mp4", io.BytesIO(_MP4_BYTES), "video/mp4")},
        headers=AUTH,
    )
    assert r.status_code == 422, r.text
