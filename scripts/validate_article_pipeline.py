"""Hermetic validation of the article generation + persistence pipeline.

Spins up a temp SQLite DB, monkeypatches all I/O adapters, and asserts:
  - Article is persisted with correct fields
  - JSON-LD contains Article + FAQPage schemas
  - Re-running the same keyword is idempotent (calls update, not publish again)
  - QA verdict is present in the return dict

No live Vertex / WordPress / Serper calls are made.

Run: .venv/bin/python scripts/validate_article_pipeline.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

# ── Must set DB_URL before any app import ────────────────────────────────────
_tmp = tempfile.mkdtemp()
os.environ["DB_URL"] = f"sqlite:///{_tmp}/test_articles.db"
os.environ.setdefault("WP_URL", "https://example.com")
os.environ.setdefault("WP_USER", "admin")
os.environ.setdefault("WP_APP_PWD", "test-app-password")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Init DB ───────────────────────────────────────────────────────────────────
from app.models import Base, engine, SessionLocal, Article  # noqa: E402

Base.metadata.create_all(engine)

# ── Fake LLM ─────────────────────────────────────────────────────────────────
FIXED_ARTICLE = {
    "title": "Best Roof Repair in Columbus OH",
    "slug": "best-roof-repair-columbus-oh",
    "metaDescription": "Top roof repair tips from Perkins Roofing.",
    "excerpt": "Get your roof repaired right.",
    "content": "## Introduction\n\nRoof repair matters.\n\n## FAQ\n\nSee below.",
    "faq": [
        {"q": "How long does a roof repair take?", "a": "Usually 1–2 days."},
        {"q": "What does roof repair cost?", "a": "Varies by damage."},
    ],
    "keywords": ["roof repair", "columbus"],
    "internalLinks": [],
    "wordCount": 120,
}


class FakeLLM:
    def chat(self, prompt, *, want_json=False, **kwargs):
        if want_json:
            return json.dumps(FIXED_ARTICLE)
        # Fact-check / intent-match → PASS
        return "PASS"


# ── Monkeypatch adapters ──────────────────────────────────────────────────────
import adapters.wordpress as _wp  # noqa: E402

_publish_calls: list[dict] = []
_update_calls: list[dict] = []
_update_status_calls: list[dict] = []

_FAKE_POST_ID = 42


def _fake_publish(*, title, html, meta_description, jsonld, status="draft"):
    _publish_calls.append({"title": title, "status": status, "jsonld": jsonld})
    return _FAKE_POST_ID


def _fake_update(post_id, *, title, html, meta_description, jsonld, status="draft"):
    _update_calls.append({"post_id": post_id, "title": title, "status": status})


def _fake_update_status(post_id, status):
    _update_status_calls.append({"post_id": post_id, "status": status})


_wp.publish = _fake_publish
_wp.update = _fake_update
_wp.update_status = _fake_update_status

# Patch at the jobs.article_job import level too (lazy imports inside function)
import importlib  # noqa: E402
import jobs.article_job as _job  # noqa: E402

# Patch the module-level lazy import names used inside generate_article
import unittest.mock as _mock  # noqa: E402

_wp_patch = _mock.patch("jobs.article_job.publish", _fake_publish, create=True)
_wp_patch.start()

# Monkeypatch hybrid_search (best-effort, corpus not needed)
import app.retrieval as _retrieval  # noqa: E402

_retrieval.hybrid_search = lambda query, k=4: {"chunks": []}


# ── Helper ────────────────────────────────────────────────────────────────────
def _fail(msg: str) -> None:
    raise SystemExit(f"FAIL: {msg}")


# ── Test 1: First run — article generated and persisted ──────────────────────
print("Test 1: generate_article — first run (publish path)...")

KEYWORD = "best roof repair columbus oh"
CTX = {"keyword": KEYWORD, "role": "standalone", "pillar_slug": None}
SERP: dict = {}

result = _job.generate_article(
    KEYWORD,
    CTX,
    SERP,
    llm=FakeLLM(),
    ground_videos=True,   # grounding is best-effort; corpus is empty → skipped cleanly
    persist=True,
    status="draft",
)

# Assert basic return shape
if result.get("post_id") != _FAKE_POST_ID:
    _fail(f"expected post_id={_FAKE_POST_ID}, got {result.get('post_id')}")
if not result.get("slug"):
    _fail("slug missing from result")
if "verdict" not in result:
    _fail("verdict key missing from result")
if result.get("verdict") not in ("pass", "warn", "block"):
    _fail(f"unexpected verdict: {result.get('verdict')}")

# Assert publish was called once
if len(_publish_calls) != 1:
    _fail(f"expected 1 publish call, got {len(_publish_calls)}")
if len(_update_calls) != 0:
    _fail(f"expected 0 update calls on first run, got {len(_update_calls)}")

# Assert Article row persisted
_db = SessionLocal()
try:
    row = _db.get(Article, result["slug"])
    if row is None:
        _fail("Article row not found in DB after first run")
    if row.wp_post_id != _FAKE_POST_ID:
        _fail(f"Article.wp_post_id={row.wp_post_id}, expected {_FAKE_POST_ID}")
    if row.status != "draft":
        _fail(f"Article.status={row.status!r}, expected 'draft'")
    if row.title != FIXED_ARTICLE["title"]:
        _fail(f"Article.title mismatch: {row.title!r}")
    if not isinstance(row.jsonld_json, list) or len(row.jsonld_json) < 2:
        _fail(f"jsonld_json should have ≥2 entries (Article+FAQPage), got {row.jsonld_json}")
finally:
    _db.close()

# Assert JSON-LD has Article + FAQPage
jsonld = result.get("article") and _db  # already closed; use publish call data
jsonld_list = _publish_calls[0]["jsonld"]
types_found = {entry.get("@type") for entry in jsonld_list}
if "Article" not in types_found:
    _fail(f"JSON-LD missing Article schema; found: {types_found}")
if "FAQPage" not in types_found:
    _fail(f"JSON-LD missing FAQPage schema; found: {types_found}")

print(f"  OK — post_id={result['post_id']}, verdict={result['verdict']}, "
      f"jsonld types={sorted(types_found)}")

# ── Test 2: Idempotent re-run — should call update, NOT publish ───────────────
print("Test 2: generate_article — second run (idempotency / update path)...")

# Reset call counters
_publish_calls.clear()
_update_calls.clear()

result2 = _job.generate_article(
    KEYWORD,
    CTX,
    SERP,
    llm=FakeLLM(),
    ground_videos=False,
    persist=True,
    status="draft",
)

if len(_publish_calls) != 0:
    _fail(f"second run must not call publish; got {len(_publish_calls)} calls")
if len(_update_calls) != 1:
    _fail(f"second run must call update once; got {len(_update_calls)}")
if result2.get("post_id") != _FAKE_POST_ID:
    _fail(f"post_id mismatch on second run: {result2.get('post_id')}")

print(f"  OK — idempotent: update called with post_id={_update_calls[0]['post_id']}")

# ── Test 3: update_status callable (used by promote_job) ─────────────────────
print("Test 3: adapters.wordpress.update_status is monkeypatchable...")

_wp.update_status(_FAKE_POST_ID, "publish")
if len(_update_status_calls) != 1:
    _fail("update_status call not recorded")
if _update_status_calls[0]["status"] != "publish":
    _fail(f"wrong status: {_update_status_calls[0]['status']!r}")

print(f"  OK — update_status({_FAKE_POST_ID}, 'publish') recorded")

# ── All done ──────────────────────────────────────────────────────────────────
print()
print("ARTICLE PIPELINE OK")
