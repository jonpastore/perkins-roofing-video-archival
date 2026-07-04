"""LLM interface used by core logic + a deterministic fake for tests.
The real Vertex Gemini implementation lives in adapters/llm.py (I/O, coverage-omitted)."""
from typing import Protocol


class LLM(Protocol):
    def chat(self, prompt: str, want_json: bool = False) -> str: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeLLM:
    """Deterministic LLM stand-in for unit tests. Default embedding dim matches
    gemini-embedding-001 (3072) so vector-shape assertions catch regressions."""

    def __init__(self, chat_reply: str = "", dim: int = 3072):
        self._reply = chat_reply
        self._dim = dim

    def chat(self, prompt: str, want_json: bool = False) -> str:
        return self._reply

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self._dim for _ in texts]
