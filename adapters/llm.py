"""Vertex AI Gemini adapter (I/O — coverage-omitted). Implements the core LLM protocol
with gemini-2.5-flash (chat) and gemini-embedding-001 @ 3072-dim (embeddings).

Validated live 2026-07-04 against project video-archival-and-content-gen with the
vertex-dev-sa key (GOOGLE_APPLICATION_CREDENTIALS)."""
import json
import os
import re
import time
import urllib.request

from core import metering


def _with_retry(fn, *, tries=6, base=2.0):
    """Exponential backoff on Vertex rate-limit/transient errors — required for the 841-video
    embed batch, which would otherwise turn 429s into silently-skipped videos."""
    from google.api_core import exceptions as gexc
    for i in range(tries):
        try:
            return fn()
        except (gexc.ResourceExhausted, gexc.ServiceUnavailable, gexc.DeadlineExceeded):
            if i == tries - 1:
                raise
            time.sleep(base ** i)  # 1,2,4,8,16s


class VertexLLM:
    def __init__(self, project, location="us-central1",
                 chat_model="gemini-2.5-flash",
                 embed_model="gemini-embedding-001", embed_dim=3072):
        self._project = project
        self._location = location
        self._chat_model = chat_model
        self._embed_model = embed_model
        self._embed_dim = embed_dim
        self._model = None

    def _ensure_chat(self):
        if self._model is None:
            import vertexai
            from vertexai.generative_models import GenerativeModel
            vertexai.init(project=self._project, location=self._location)
            self._model = GenerativeModel(self._chat_model)

    def chat(self, prompt, want_json=False, response_schema=None):
        self._ensure_chat()
        cfg = {}
        if want_json or response_schema:
            cfg["response_mime_type"] = "application/json"
        if response_schema:
            # Controlled generation — Gemini is constrained to valid JSON matching the schema,
            # eliminating the intermittent unescaped-newline parse failures on long article content.
            cfg["response_schema"] = response_schema
        response = _with_retry(lambda: self._model.generate_content(prompt, generation_config=cfg))
        # Emit token usage to the per-tenant metering counter (no-op outside a tenant context).
        # Prefer the SDK's usage_metadata when available; fall back to a character-based estimate
        # (~4 chars/token) so the counter is always non-zero after a real LLM call.
        try:
            usage = getattr(response, "usage_metadata", None)
            if usage is not None:
                total = getattr(usage, "total_token_count", None) or (
                    getattr(usage, "prompt_token_count", 0)
                    + getattr(usage, "candidates_token_count", 0)
                )
            else:
                total = None
            if not total:
                total = max(1, len(prompt) // 4)
            metering.add("llm_tokens", int(total))
        except Exception:  # noqa: BLE001 — metering must never break the adapter
            pass
        return response.text

    def embed(self, texts, batch=100):
        import vertexai
        from vertexai.language_models import TextEmbeddingModel
        vertexai.init(project=self._project, location=self._location)
        model = TextEmbeddingModel.from_pretrained(self._embed_model)
        texts = list(texts)
        out = []
        for i in range(0, len(texts), batch):  # bound request size; retry each batch on 429
            chunk = texts[i:i + batch]
            embs = _with_retry(
                lambda c=chunk: model.get_embeddings(c, output_dimensionality=self._embed_dim))
            out.extend(e.values for e in embs)
        return out


class OllamaLLM:
    """Local (cerberus Ollama) chat backend with the SAME .chat interface as VertexLLM — used
    for one-time backlog priming (article/FAQ generation) on the free GPU. Returns a JSON string
    when want_json/response_schema (via Ollama format=json), matching VertexLLM's .text contract."""

    def chat(self, prompt, want_json=False, response_schema=None):
        import re  # noqa: PLC0415

        from app.config import settings  # noqa: PLC0415
        from app.llm import _ollama  # noqa: PLC0415
        # Ollama can't enforce a JSON schema (no controlled generation), so spell out the
        # expected keys in the prompt — otherwise the model omits fields like "content".
        if response_schema and isinstance(response_schema, dict):
            props = response_schema.get("properties", {})
            req = response_schema.get("required", list(props))
            prompt = (
                prompt
                + f"\n\nReturn ONLY one valid JSON object with these keys: {', '.join(props)}. "
                + f"Required: {', '.join(req)}. "
                + 'The "content" key (if present) must hold the COMPLETE article body as HTML.'
            )
        payload = {
            "model": settings.LLM_MODEL,
            "prompt": prompt,
            "stream": False,
            # num_predict raised so long article JSON isn't truncated (default cap → unparseable JSON).
            "options": {
                "temperature": 0.1 if (want_json or response_schema) else 0.4,
                "num_ctx": 16384,
                "num_predict": 8192,
            },
        }
        if want_json or response_schema:
            payload["format"] = "json"
        out = _ollama("/api/generate", payload)
        return re.sub(r"<think>.*?</think>", "", out.get("response", ""), flags=re.S).strip()

    def embed(self, texts, batch=100):
        # Embeddings must match the stored 3072-dim Vertex vectors — always use the Vertex embedder.
        return get_embedder().embed(texts, batch=batch)


class LiteLLMLLM:
    """Local gpt-oss-120b (non-think, faster + no JSON-truncation) via the LiteLLM front door (cerberus-ai:4000), an
    OpenAI-compatible chat endpoint — same `.chat` contract as VertexLLM/OllamaLLM. Opt-in
    dev/local generator (settings.LLM_BACKEND == "litellm"); never the prod default (prod's
    fail-fast in app/config.py still requires LLM_BACKEND == "vertex").

    response_schema is deliberately NOT sent as OpenAI `response_format: json_schema`: our
    schemas (e.g. ARTICLE_SCHEMA in jobs/article_job.py) use Vertex's controlled-generation
    shape (uppercase "OBJECT"/"STRING" types), and litellm's json_schema conversion hard-400s
    on that shape (verified live against gpt-oss-120b-think 2026-07-21). Instead this reuses
    OllamaLLM's workaround — spell out the required keys in the prompt — with the
    universally-supported `json_object` mode, which round-tripped ARTICLE_SCHEMA and
    CRITIQUE_SCHEMA cleanly in the same test.
    """

    def __init__(self, url="http://cerberus-ai:4000", model="gpt-oss-120b", api_key=None):
        self._url = url.rstrip("/") + "/v1/chat/completions"
        self._model = model
        self._api_key = api_key

    def _key(self) -> str:
        if self._api_key:
            return self._api_key
        key = os.getenv("LITELLM_API_KEY")
        if key:
            return key
        # Local-dev fallback: the cached copy `llm` (the fleet's CLI) also reads.
        cached = os.path.expanduser("~/.config/litellm/cerberus.key")
        if os.path.exists(cached):
            with open(cached) as f:
                return f.read().strip()
        raise RuntimeError(
            "LITELLM_API_KEY unset and ~/.config/litellm/cerberus.key not found — "
            "required for the litellm backend"
        )

    def chat(self, prompt, want_json=False, response_schema=None):
        if response_schema and isinstance(response_schema, dict):
            props = response_schema.get("properties", {})
            req = response_schema.get("required", list(props))
            prompt = (
                prompt
                + f"\n\nReturn ONLY one valid JSON object with these keys: {', '.join(props)}. "
                + f"Required: {', '.join(req)}. "
                + 'The "content" key (if present) must hold the COMPLETE article body as HTML.'
            )
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1 if (want_json or response_schema) else 0.4,
            # gpt-oss is a reasoning model — a tight budget silently truncates JSON mid-object
            # (measured: 800 tokens truncated CRITIQUE_SCHEMA output; 3000 did not). Article
            # bodies run long, so size generously rather than retune per call site.
            "max_tokens": 8192,
        }
        if want_json or response_schema:
            payload["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            self._url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._key()}"},
        )
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read().decode())
        content = data["choices"][0]["message"]["content"] or ""
        return re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()

    def embed(self, texts, batch=100):
        # Embeddings must match the stored 3072-dim Vertex vectors — always use the Vertex embedder.
        return get_embedder().embed(texts, batch=batch)


class CloudflareLLM:
    """Cloudflare Workers-AI chat backend — same ``.chat`` contract as VertexLLM/LiteLLMLLM.

    This is the PRODUCTION-capable non-local generator (settings.LLM_BACKEND == 'cloudflare'):
    it removes the dependence on the local cerberus fleet (dev-only, not always reachable from
    Cloud Run). Account + model are config-driven; the API token comes from CLOUDFLARE_API_TOKEN
    (injected from Secret Manager in prod). Embeddings still go to Vertex (the stored 3072-dim
    index is Vertex-embedded — only the CHAT backend is swappable). response_schema is spelled
    out in the prompt (same reason as LiteLLMLLM) rather than sent as a provider json_schema.
    """

    _API = "https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"

    def __init__(self, account=None, model="@cf/meta/llama-3.3-70b-instruct-fp8-fast", api_token=None):
        self._account = account or os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
        self._model = model
        self._token = api_token or os.getenv("CLOUDFLARE_API_TOKEN", "")
        if not self._account or not self._token:
            raise RuntimeError(
                "CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are required for the cloudflare "
                "LLM backend (token from Secret Manager 'cloudflare-api-token')."
            )

    def chat(self, prompt, want_json=False, response_schema=None):
        if response_schema and isinstance(response_schema, dict):
            props = response_schema.get("properties", {})
            req = response_schema.get("required", list(props))
            prompt = (
                prompt
                + f"\n\nReturn ONLY one valid JSON object with these keys: {', '.join(props)}. "
                + f"Required: {', '.join(req)}. "
                + 'The "content" key (if present) must hold the COMPLETE article body as HTML.'
            )
        # The model's context is 24k tokens TOTAL (input + output). Estimate input at
        # ~3.2 chars/token (English prose) and clamp the output so the request always
        # fits — an unclamped 8192 on a large grounded prompt 400s, and oversized
        # bodies 413. Floor of 2048 keeps article JSON viable; if even that can't
        # fit, fail loudly with the size rather than let CF truncate mid-JSON.
        est_input = int(len(prompt) / 3.2)
        max_out = min(8192, 24_000 - est_input - 512)
        if max_out < 2048:
            raise RuntimeError(
                f"prompt too large for Cloudflare llama 24k context: ~{est_input} input "
                f"tokens leaves {max_out} for output (need >=2048) — trim the prompt"
            )
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1 if (want_json or response_schema) else 0.4,
            "max_tokens": max_out,
        }
        url = self._API.format(acct=self._account, model=self._model)
        r = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self._token}"},
        )
        with urllib.request.urlopen(r, timeout=300) as resp:
            data = json.loads(resp.read().decode())
        if not data.get("success", False):
            raise RuntimeError(f"Cloudflare Workers-AI error: {data.get('errors')}")
        content = (data.get("result") or {}).get("response") or ""
        return re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()

    def embed(self, texts, batch=100):
        # Embeddings must match the stored 3072-dim Vertex vectors — always use the Vertex embedder.
        return get_embedder().embed(texts, batch=batch)


_default = None
_embedder = None


def get_embedder():
    """Vertex embedding client — independent of LLM_BACKEND (chat). Embeddings always go to
    Vertex so they match the stored 3072-dim chunk vectors; only the CHAT backend is swappable."""
    global _embedder
    if _embedder is None:
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT unset — required for the Vertex embedder")
        _embedder = VertexLLM(
            project=project,
            location=os.getenv("GCP_REGION", "us-central1"),
            embed_model=os.getenv("EMBED_MODEL", "gemini-embedding-001"),
        )
    return _embedder


def get_default():
    """Lazy singleton, backend-selected by settings.LLM_BACKEND. 'ollama' -> local cerberus
    (priming); 'litellm' -> local gpt-oss-120b-think via the cerberus LiteLLM front door
    (opt-in, dev-only); otherwise Vertex (live). Built from env (GOOGLE_CLOUD_PROJECT,
    GCP_REGION, models)."""
    global _default
    if _default is None:
        from app.config import settings  # noqa: PLC0415
        if settings.LLM_BACKEND == "ollama":
            _default = OllamaLLM()
        elif settings.LLM_BACKEND == "litellm":
            _default = LiteLLMLLM(url=settings.LITELLM_URL, model=settings.LITELLM_MODEL)
        elif settings.LLM_BACKEND == "cloudflare":
            _default = CloudflareLLM(account=settings.CLOUDFLARE_ACCOUNT_ID,
                                     model=settings.CLOUDFLARE_MODEL)
        else:
            project = os.getenv("GOOGLE_CLOUD_PROJECT")
            if not project:
                raise RuntimeError("GOOGLE_CLOUD_PROJECT unset — required for the Vertex backend")
            _default = VertexLLM(
                project=project,
                location=os.getenv("GCP_REGION", "us-central1"),
                chat_model=os.getenv("LLM_MODEL", "gemini-2.5-flash"),
                embed_model=os.getenv("EMBED_MODEL", "gemini-embedding-001"),
            )
    return _default
