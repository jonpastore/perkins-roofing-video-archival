"""Vertex AI Gemini adapter (I/O — coverage-omitted). Implements the core LLM protocol
with gemini-2.5-flash (chat) and gemini-embedding-001 @ 3072-dim (embeddings).

Validated live 2026-07-04 against project video-archival-and-content-gen with the
vertex-dev-sa key (GOOGLE_APPLICATION_CREDENTIALS)."""
import os
import time


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
        return _with_retry(lambda: self._model.generate_content(prompt, generation_config=cfg).text)

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


_default = None


def get_default():
    """Lazy singleton built from env (GOOGLE_CLOUD_PROJECT, GCP_REGION, LLM_MODEL, EMBED_MODEL)."""
    global _default
    if _default is None:
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
