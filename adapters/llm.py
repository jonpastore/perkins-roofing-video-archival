"""Vertex AI Gemini adapter (I/O — coverage-omitted). Implements the core LLM protocol
with gemini-2.5-flash (chat) and gemini-embedding-001 @ 3072-dim (embeddings).

Validated live 2026-07-04 against project video-archival-and-content-gen with the
vertex-dev-sa key (GOOGLE_APPLICATION_CREDENTIALS)."""
import os


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

    def chat(self, prompt, want_json=False):
        self._ensure_chat()
        cfg = {"response_mime_type": "application/json"} if want_json else {}
        return self._model.generate_content(prompt, generation_config=cfg).text

    def embed(self, texts):
        import vertexai
        from vertexai.language_models import TextEmbeddingModel
        vertexai.init(project=self._project, location=self._location)
        model = TextEmbeddingModel.from_pretrained(self._embed_model)
        embs = model.get_embeddings(list(texts), output_dimensionality=self._embed_dim)
        return [e.values for e in embs]


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
