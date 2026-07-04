# Wave 0 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the verified POC into an `adapters/ + core/ + api/ + jobs/` layout with a real Vertex Gemini backend, Firebase-Auth-gated FastAPI, a React SPA shell, CI enforcing a 97% core-logic coverage gate, and Terraform for the client's GCP — all buildable now with zero external creds.

**Architecture:** Pure business logic moves into `core/` (unit-tested to 97%); all external I/O (LLM, embeddings, STT, DB, YouTube, WordPress, social, ffmpeg, Firebase, Secrets) hides behind thin `adapters/` interfaces (coverage-omitted). `api/` is a thin FastAPI serving layer with a Firebase-token auth dependency; `jobs/` holds Cloud Run Job entry points. The existing POC logic is preserved — this is extraction, not rewrite.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Cloud SQL Postgres + pgvector, Vertex AI Gemini (`gemini-2.5-flash` chat + `gemini-embedding-001` 3072-dim), Firebase Auth, Vite + React + TypeScript SPA on Firebase Hosting, Terraform, GitHub Actions, pytest + pytest-cov.

## Global Constraints

- **LLM + embeddings:** Vertex Gemini only. No Anthropic/Ollama in prod paths. `gemini-embedding-001` at **3072 dimensions** for the vector index — never mix embedding models in one index.
- **Coverage gate:** `pytest --cov=core --cov-fail-under=97`; `adapters/` omitted via `.coveragerc`. CI blocks merge on failure.
- **Tenancy:** all data, secrets, and AI spend live in the client's GCP project on `perkinsroofing.net`. No DeGenito-owned keys in the prod path.
- **Auth:** Firebase Auth (Google sign-in) + custom claims → roles `admin` | `sales`, verified server-side on every protected route.
- **Idempotency preserved:** keep the existing `ingestion_runs` (stage, status, content_hash, pipeline_version) resumability model.
- **Adapters are I/O-only, core is pure:** no `requests`/SDK/`SessionLocal` calls in `core/`; no business logic in `adapters/`.

---

### Task 1: Characterization test — pin current behavior before refactor

**Files:**
- Create: `tests/characterization/test_baseline.py`
- Create: `tests/conftest.py` (fixture DB + one fixture video with a caption)
- Test: the above

**Interfaces:**
- Consumes: existing `app.ingest`, `app.retrieval`, `app.answer`, `app.models`.
- Produces: `fixture_db()` pytest fixture returning a session bound to an in-memory/temp SQLite with one video ingested; reused by later tasks.

- [ ] **Step 1: Write the failing characterization test**

```python
# tests/characterization/test_baseline.py
from app import retrieval, answer

def test_search_returns_ranked_hits(fixture_db):
    hits = retrieval.hybrid_search("roof leak repair", session=fixture_db, k=3)
    assert len(hits) >= 1
    assert hits[0].score >= hits[-1].score  # ranked descending

def test_answer_abstains_below_threshold(fixture_db):
    res = answer.ask("what is the capital of France", session=fixture_db)
    assert res["abstained"] is True
```

- [ ] **Step 2: Run to verify it fails** (fixture not yet defined)

Run: `pytest tests/characterization/test_baseline.py -v`
Expected: FAIL — `fixture 'fixture_db' not found`.

- [ ] **Step 3: Write the fixture**

```python
# tests/conftest.py
import pytest
from app.models import Base, Video, Segment, Chunk
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

@pytest.fixture
def fixture_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'t.db'}")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    v = Video(id="vid1", title="Roof leak repair guide", url="http://x")
    s.add(v)
    s.add(Segment(video_id="vid1", text="How to fix a roof leak", start=0, end=5, source="youtube_caption"))
    s.add(Chunk(video_id="vid1", text="How to fix a roof leak", start=0, end=5,
                embedding=[0.1]*768, embed_model="dev", version="v1"))
    s.commit()
    yield s
    s.close()
```

- [ ] **Step 4: Run to verify it passes** (adjust signatures to match actual `retrieval.hybrid_search`/`answer.ask` if they differ — read the current source first)

Run: `pytest tests/characterization/test_baseline.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/ && git commit -m "test: characterization baseline before restructure"
```

---

### Task 2: `adapters/` + `core/` package skeleton, wire imports

**Files:**
- Create: `adapters/__init__.py`, `core/__init__.py`, `api/__init__.py`, `jobs/__init__.py`
- Create: `.coveragerc`
- Modify: `app/__init__.py` (leave POC importable during transition)

**Interfaces:**
- Produces: importable `adapters`, `core`, `api`, `jobs` packages.

- [ ] **Step 1: Create the packages**

```bash
mkdir -p adapters core api jobs
touch adapters/__init__.py core/__init__.py api/__init__.py jobs/__init__.py
```

- [ ] **Step 2: Write `.coveragerc`**

```ini
# .coveragerc
[run]
source = core
omit =
    adapters/*
    api/*
    jobs/*
    tests/*
[report]
fail_under = 97
show_missing = true
```

- [ ] **Step 3: Verify packages import**

Run: `python -c "import adapters, core, api, jobs; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add adapters core api jobs .coveragerc && git commit -m "chore: scaffold adapters/core/api/jobs packages"
```

---

### Task 3: `LLMClient` protocol + Vertex Gemini chat adapter

**Files:**
- Create: `adapters/llm.py`
- Create: `core/llm_types.py` (pure types + a `FakeLLM` used by core tests)
- Test: `tests/adapters/test_llm_contract.py`

**Interfaces:**
- Produces:
  - `core/llm_types.py`: `class LLM(Protocol): def chat(self, prompt: str, *, want_json: bool=False) -> str; def embed(self, texts: list[str]) -> list[list[float]]`. `class FakeLLM` implementing it deterministically.
  - `adapters/llm.py`: `class VertexLLM(LLM)` using `google-cloud-aiplatform`; reads `GOOGLE_CLOUD_PROJECT`, model `gemini-2.5-flash`. `def make_llm(settings) -> LLM` factory.

- [ ] **Step 1: Write the pure protocol + fake (test first)**

```python
# tests/adapters/test_llm_contract.py
from core.llm_types import FakeLLM

def test_fake_llm_roundtrips():
    llm = FakeLLM(chat_reply='{"ok": true}')
    assert llm.chat("hi", want_json=True) == '{"ok": true}'
    vecs = llm.embed(["a", "b"])
    assert len(vecs) == 2 and len(vecs[0]) == 3072
```

- [ ] **Step 2: Run — fails** (`core.llm_types` missing). `pytest tests/adapters/test_llm_contract.py -v` → FAIL.

- [ ] **Step 3: Implement types + fake**

```python
# core/llm_types.py
from typing import Protocol

class LLM(Protocol):
    def chat(self, prompt: str, *, want_json: bool = False) -> str: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...

class FakeLLM:
    def __init__(self, chat_reply: str = "", dim: int = 3072):
        self._reply, self._dim = chat_reply, dim
    def chat(self, prompt: str, *, want_json: bool = False) -> str:
        return self._reply
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self._dim for _ in texts]
```

- [ ] **Step 4: Run — passes.** `pytest tests/adapters/test_llm_contract.py -v` → PASS.

- [ ] **Step 5: Implement the real Vertex adapter** (not unit-tested — coverage-omitted; verified live in Wave 1)

```python
# adapters/llm.py
import json
from core.llm_types import LLM

class VertexLLM(LLM):
    def __init__(self, project: str, location: str = "us-central1",
                 chat_model: str = "gemini-2.5-flash",
                 embed_model: str = "gemini-embedding-001"):
        import vertexai
        from vertexai.generative_models import GenerativeModel
        vertexai.init(project=project, location=location)
        self._chat = GenerativeModel(chat_model)
        self._embed_model = embed_model
        self._location, self._project = location, project

    def chat(self, prompt: str, *, want_json: bool = False) -> str:
        cfg = {"response_mime_type": "application/json"} if want_json else {}
        return self._chat.generate_content(prompt, generation_config=cfg).text

    def embed(self, texts: list[str]) -> list[list[float]]:
        from vertexai.language_models import TextEmbeddingModel
        m = TextEmbeddingModel.from_pretrained(self._embed_model)
        # gemini-embedding-001 supports output_dimensionality; pin to 3072
        embs = m.get_embeddings(texts, output_dimensionality=3072)
        return [e.values for e in embs]

def make_llm(settings) -> LLM:
    return VertexLLM(project=settings.gcp_project)
```

- [ ] **Step 6: Commit**

```bash
git add adapters/llm.py core/llm_types.py tests/adapters/test_llm_contract.py
git commit -m "feat: LLM protocol + Vertex Gemini adapter (gemini-embedding-001 3072-dim)"
```

---

### Task 4: Bump embedding schema to 3072-dim + Alembic migration

**Files:**
- Modify: `app/models.py` (Chunk.embedding dimension) — or the new `core/models.py` if moved
- Create: `migrations/versions/0001_embedding_3072.py` (Alembic) or a documented raw-SQL migration
- Test: `tests/core/test_schema.py`

**Interfaces:**
- Produces: `Chunk.embedding` typed `Vector(3072)` in prod (pgvector), JSON list in dev/SQLite. HNSW index over 3072-dim vectors.

- [ ] **Step 1: Test the dev-path schema roundtrips a 3072 vector**

```python
# tests/core/test_schema.py
from app.models import Base, Chunk
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def test_chunk_stores_3072(tmp_path):
    e = create_engine(f"sqlite:///{tmp_path/'s.db'}"); Base.metadata.create_all(e)
    s = sessionmaker(bind=e)()
    s.add(Chunk(video_id="v", text="t", start=0, end=1,
                embedding=[0.0]*3072, embed_model="gemini-embedding-001", version="v2"))
    s.commit()
    assert len(s.query(Chunk).one().embedding) == 3072
```

- [ ] **Step 2: Run — fails** if dev column caps/asserts 768. `pytest tests/core/test_schema.py -v`.

- [ ] **Step 3: Update the model** — change the prod pgvector dimension to 3072 and default `embed_model="gemini-embedding-001"`; dev JSON stays list-typed.

- [ ] **Step 4: Write the prod migration** (raw SQL documented; run at Wave-1 deploy):

```sql
-- migrations/versions/0001_embedding_3072.sql
ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(3072);
DROP INDEX IF EXISTS chunks_embedding_hnsw;
CREATE INDEX chunks_embedding_hnsw ON chunks
  USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
```

- [ ] **Step 5: Run — passes.** `pytest tests/core/test_schema.py -v` → PASS.

- [ ] **Step 6: Commit.** `git commit -am "feat: 3072-dim embedding schema + pgvector HNSW migration"`

---

### Task 5: DB + transcript/STT + YouTube adapters (extract I/O)

**Files:**
- Create: `adapters/db.py`, `adapters/transcript.py`, `adapters/stt_whisper.py`, `adapters/stt_gcp.py`, `adapters/youtube.py`, `adapters/yt_dlp.py`
- Modify: move I/O bodies out of `app/transcript.py`, `app/youtube.py`, `app/ingest_comments.py`
- Test: `tests/adapters/test_transcript_source.py`

**Interfaces:**
- Produces:
  - `adapters/transcript.py`: `class TranscriptSource(Protocol): def get(self, video_id: str) -> list[Segment]`. Impls: `YoutubeCaptionSource`, `WhisperSource` (local faster-whisper), `GcpSttSource` (fallback). `def pick_source(...)` chooses captions → Whisper.
  - `adapters/db.py`: `session_scope()` context manager + `make_session(db_url)`.
  - `adapters/stt_whisper.py`: `transcribe(path_or_url) -> list[Segment]` calling a faster-whisper endpoint on cerberus (URL from `settings.whisper_url`).

- [ ] **Step 1: Test source selection is pure and picks captions first**

```python
# tests/adapters/test_transcript_source.py
from adapters.transcript import pick_source

def test_prefers_captions_when_available():
    assert pick_source(has_captions=True).__class__.__name__ == "YoutubeCaptionSource"

def test_falls_back_to_whisper():
    assert pick_source(has_captions=False).__class__.__name__ == "WhisperSource"
```

> Note: `pick_source` selection logic is pure → also mirror it in `core/` if you want it under the coverage gate. Keep the I/O impls in `adapters/`.

- [ ] **Step 2: Run — fails.** `pytest tests/adapters/test_transcript_source.py -v`.

- [ ] **Step 3: Implement the adapters** — move existing `app/transcript.py` YouTube-caption + GCP-STT bodies into `adapters/transcript.py`; add `WhisperSource` posting to `settings.whisper_url` (`/asr` with the video URL, returns segments). Keep `Segment` shape identical to the ORM.

- [ ] **Step 4: Run — passes.** `pytest tests/adapters/test_transcript_source.py -v` → PASS.

- [ ] **Step 5: Commit.** `git commit -am "feat: extract db/transcript/whisper/youtube adapters"`

---

### Task 6: Extract `core/` pure logic + raise coverage to 97%

**Files:**
- Create: `core/ingest_stages.py`, `core/graph.py`, `core/retrieval.py`, `core/answer.py`, `core/chunking.py`
- Modify: `app/ingest.py`, `app/graph.py`, `app/retrieval.py`, `app/answer.py`, `app/store.py` → delegate to `core/` + adapters
- Test: `tests/core/test_ingest_stages.py`, `test_graph_parse.py`, `test_retrieval.py`, `test_answer.py`

**Interfaces:**
- Produces (pure, adapter-injected):
  - `core/graph.py`: `def build_extract_prompt(segments) -> str`; `def parse_nodes(llm_json: str, video_id: str) -> list[GraphNode]`.
  - `core/retrieval.py`: `def rank(query_vec, rows, *, lexical_terms, graph_hits) -> list[Hit]` (vector + lexical +0.15 + graph +0.1 boosts — port exact weights from `app/retrieval.py`).
  - `core/answer.py`: `def should_abstain(top_score, threshold) -> bool`; `def build_answer_prompt(question, hits) -> str`.
  - `core/ingest_stages.py`: `def stage_hash(inputs) -> str`; `def next_stage(run_status) -> str|None` (resumability).

- [ ] **Step 1: Write pure-logic tests** (one per module — e.g. ranking order, abstention boundary, hash stability, graph JSON parse of a canned LLM reply). Example:

```python
# tests/core/test_retrieval.py
from core.retrieval import rank
def test_lexical_boost_reorders():
    rows = [{"id":1,"cos":0.50,"text":"roof leak"}, {"id":2,"cos":0.55,"text":"gutters"}]
    hits = rank(query_vec=[0.0]*3072, rows=rows, lexical_terms=["leak"], graph_hits=set())
    assert hits[0].id == 1  # +0.15 lexical beats the 0.05 cosine gap
```

- [ ] **Step 2: Run — fails.** `pytest tests/core -v`.

- [ ] **Step 3: Port the pure logic** out of `app/*` into `core/*`; leave `app/*` (and later `api/`, `jobs/`) calling `core.*` with adapter results injected.

- [ ] **Step 4: Run with coverage gate**

Run: `pytest --cov=core --cov-fail-under=97 tests/core -v`
Expected: PASS at ≥97% (add tests for any uncovered branch).

- [ ] **Step 5: Commit.** `git commit -am "refactor: extract pure core logic, 97% covered"`

---

### Task 7: GitHub Actions CI — lint + coverage gate + SPA build

**Files:**
- Create: `.github/workflows/ci.yml`, `pyproject.toml` (ruff + pytest config) if absent

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/ci.yml
name: ci
on: [push, pull_request]
jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r app/requirements.txt pytest pytest-cov ruff
      - run: ruff check core adapters api jobs
      - run: pytest --cov=core --cov-config=.coveragerc --cov-fail-under=97
  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: cd web && npm ci && npm run build
```

- [ ] **Step 2: Verify locally** — `ruff check core adapters api jobs` and `pytest --cov=core --cov-fail-under=97` both green before pushing.

- [ ] **Step 3: Commit + push, confirm the Actions run is green.** `git commit -am "ci: coverage gate + lint + SPA build"`

---

### Task 8: Firebase Auth adapter + FastAPI role dependency

**Files:**
- Create: `adapters/firebase.py`, `api/auth.py`, `api/app.py`
- Create: `core/authz.py` (pure role rules)
- Test: `tests/core/test_authz.py`, `tests/api/test_auth_dependency.py`

**Interfaces:**
- Produces:
  - `core/authz.py`: `def can(role: str, action: str) -> bool` (pure matrix: admin=all; sales=search/ask/email-compose/article-read).
  - `adapters/firebase.py`: `def verify_token(id_token: str) -> dict` (returns `{uid, email, role}` via `firebase_admin.auth.verify_id_token`).
  - `api/auth.py`: `def require_role(action: str)` FastAPI dependency → 401 if no/invalid token, 403 if `not can(role, action)`.

- [ ] **Step 1: Test the pure authz matrix**

```python
# tests/core/test_authz.py
from core.authz import can
def test_sales_cannot_admin():
    assert can("admin", "manage_templates") is True
    assert can("sales", "manage_templates") is False
    assert can("sales", "search") is True
```

- [ ] **Step 2: Run — fails.** `pytest tests/core/test_authz.py -v`.

- [ ] **Step 3: Implement `core/authz.py`** with the pure matrix.

- [ ] **Step 4: Test the dependency with a fake verifier** (inject `verify_token`):

```python
# tests/api/test_auth_dependency.py
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
from api.auth import require_role, set_verifier

def test_403_for_wrong_role():
    set_verifier(lambda tok: {"uid":"u","email":"e","role":"sales"})
    app = FastAPI()
    @app.get("/admin", dependencies=[Depends(require_role("manage_templates"))])
    def _(): return {"ok": True}
    c = TestClient(app)
    assert c.get("/admin", headers={"Authorization":"Bearer x"}).status_code == 403
```

- [ ] **Step 5: Run — fails, then implement** `api/auth.py` (`set_verifier` for test injection; default = `adapters.firebase.verify_token`). Run against the **Firebase emulator** for a live smoke.

- [ ] **Step 6: Commit.** `git commit -am "feat: Firebase auth adapter + role-gated FastAPI dependency"`

---

### Task 9: Admin/Sales SPA shell (Vite + React + TS)

**Files:**
- Create: `web/` (Vite scaffold), `web/src/auth.ts` (Firebase web SDK login), `web/src/api.ts` (attaches ID token), `web/src/App.tsx` (role-gated nav), `web/firebase.json` (Hosting)

- [ ] **Step 1: Scaffold**

```bash
cd web && npm create vite@latest . -- --template react-ts && npm i firebase
```

- [ ] **Step 2: Implement Google sign-in** (`signInWithPopup`, GoogleAuthProvider) in `web/src/auth.ts`; expose `getIdToken()`.

- [ ] **Step 3: API client** — `web/src/api.ts` sends `Authorization: Bearer <idToken>` on every call.

- [ ] **Step 4: Role-gated shell** — `App.tsx` reads the custom claim `role`; renders Admin nav (templates, articles, scheduling, video approve, config) vs Sales nav (search/ask, compose email). Placeholder routes are fine — later waves fill them.

- [ ] **Step 5: Verify build.** `npm run build` → succeeds. `firebase emulators:start` → login works against emulator.

- [ ] **Step 6: Commit.** `git commit -m "feat: SPA shell with Firebase login + role-gated nav"`

---

### Task 10: Terraform for client GCP + `bootstrap.sh`

**Files:**
- Create: `infra/main.tf`, `infra/variables.tf`, `infra/outputs.tf`, `infra/bootstrap.sh`, `infra/README.md`

**Interfaces:**
- Produces (Terraform resources): Cloud SQL Postgres 16 + `pgvector` (via `cloudsql.enable_pgvector` / init), GCS buckets (media, rendered-reels public), Cloud Run service (`api`) + Cloud Run Jobs (ingest, render, article, social), Cloud Scheduler (cron promoter), Secret Manager (WP, Resend, Serper, Meta, TikTok, YouTube), service accounts with least-priv IAM, a **budget alert**, Vertex AI + STT APIs enabled.

- [ ] **Step 1: Write `variables.tf`** — `project_id`, `region` (`us-central1`), `budget_amount`, notification email.

- [ ] **Step 2: Write `main.tf`** with the resources above (each documented). Public buckets use uniform bucket-level access + a public-read IAM binding **only** on the rendered-reels bucket (IG/TikTok need public URLs). Enable `run.googleapis.com`, `sqladmin.googleapis.com`, `aiplatform.googleapis.com`, `speech.googleapis.com`, `secretmanager.googleapis.com`, `cloudscheduler.googleapis.com`.

- [ ] **Step 3: Write `bootstrap.sh`** — the post-billing runbook Jon runs: `gcloud config set project`, `terraform init && terraform plan && terraform apply`, then seed secrets from a `.env` template into Secret Manager. **Does not run until prereq P1 (billing) lands.**

- [ ] **Step 4: Validate offline.** `cd infra && terraform init -backend=false && terraform validate` → success. (No `apply` until billing.)

- [ ] **Step 5: Commit.** `git commit -m "feat: Terraform for client GCP + bootstrap runbook"`

---

## Self-Review

- **Spec coverage:** repo restructure (T2,5,6) ✓ · CI+coverage gate (T7) ✓ · Firebase auth (T8) ✓ · Vertex backend (T3) ✓ · SPA shell (T9) ✓ · Terraform+bootstrap (T10) ✓ · 3072-dim decision (T4) ✓ · local-Whisper adapter seam (T5) ✓.
- **Deferred to later waves (correct):** running the full ingest/embed (Wave 1, needs billing), content engines (Wave 2), video (Wave 3), social (Wave 4).
- **Open prereqs referenced:** P1 billing gates T10 apply and any live Vertex/STT call; confirm the cerberus Whisper endpoint URL for T5 (`settings.whisper_url`).

## Execution Handoff

Detailed in the parent restart plan. Recommended: subagent-driven, fresh subagent per task, review between tasks.
