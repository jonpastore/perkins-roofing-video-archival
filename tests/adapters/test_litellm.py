"""LiteLLMLLM (adapters/llm.py) — mocked, no live network calls.

Live compliance against the real cerberus-ai:4000 front door (gpt-oss-120b-think) was verified
manually 2026-07-21: both ARTICLE_SCHEMA and CRITIQUE_SCHEMA round-tripped to valid JSON via the
json_object + prompt-spelled-keys workaround. These tests lock in the request/response contract
so a refactor can't silently break that path.
"""
import json

import pytest

import adapters.llm as llm_mod
from adapters.llm import LiteLLMLLM


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture_urlopen(monkeypatch, response_body: dict):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["payload"] = json.loads(req.data.decode())
        return _FakeResponse(response_body)

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", fake_urlopen)
    return captured


def test_chat_hits_openai_compatible_endpoint_with_bearer_key(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "sk-test-key")
    captured = _capture_urlopen(monkeypatch, {
        "choices": [{"message": {"content": "OK"}}],
    })
    out = LiteLLMLLM().chat("say ok")
    assert out == "OK"
    assert captured["url"] == "http://cerberus-ai:4000/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test-key"
    assert captured["payload"]["model"] == "gpt-oss-120b-think"
    assert captured["payload"]["messages"] == [{"role": "user", "content": "say ok"}]


def test_chat_strips_think_tags(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "sk-test-key")
    _capture_urlopen(monkeypatch, {
        "choices": [{"message": {"content": "<think>reasoning...</think>final answer"}}],
    })
    out = LiteLLMLLM().chat("hello")
    assert out == "final answer"


def test_chat_with_response_schema_spells_out_keys_and_uses_json_object_mode(monkeypatch):
    """Mirrors OllamaLLM's workaround — never send response_schema through as OpenAI
    json_schema, because our Vertex-shaped schemas (uppercase OBJECT/STRING types) 400
    against litellm's json_schema conversion (verified live 2026-07-21)."""
    monkeypatch.setenv("LITELLM_API_KEY", "sk-test-key")
    schema = {
        "type": "OBJECT",
        "properties": {"title": {"type": "STRING"}, "content": {"type": "STRING"}},
        "required": ["title", "content"],
    }
    captured = _capture_urlopen(monkeypatch, {
        "choices": [{"message": {"content": '{"title": "x", "content": "y"}'}}],
    })
    out = LiteLLMLLM().chat("write something", want_json=True, response_schema=schema)
    assert json.loads(out) == {"title": "x", "content": "y"}
    payload = captured["payload"]
    assert payload["response_format"] == {"type": "json_object"}
    assert "title" in payload["messages"][0]["content"]
    assert "content" in payload["messages"][0]["content"]
    assert "Required: title, content" in payload["messages"][0]["content"]


def test_key_falls_back_to_cached_file_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    key_file = tmp_path / "cerberus.key"
    key_file.write_text("sk-cached-key\n")
    monkeypatch.setattr(
        llm_mod.os.path, "expanduser",
        lambda p: str(key_file) if p == "~/.config/litellm/cerberus.key" else p)
    captured = _capture_urlopen(monkeypatch, {"choices": [{"message": {"content": "OK"}}]})
    LiteLLMLLM().chat("hi")
    assert captured["headers"]["Authorization"] == "Bearer sk-cached-key"


def test_key_raises_when_unset_and_no_cached_file(monkeypatch, tmp_path):
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.setattr(
        llm_mod.os.path, "expanduser",
        lambda p: str(tmp_path / "missing.key") if p == "~/.config/litellm/cerberus.key" else p)
    with pytest.raises(RuntimeError):
        LiteLLMLLM().chat("hi")


def test_get_default_returns_litellm_backend(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "sk-test-key")
    import app.config as config_mod
    monkeypatch.setattr(config_mod.settings, "LLM_BACKEND", "litellm")
    llm_mod._default = None
    try:
        inst = llm_mod.get_default()
        assert isinstance(inst, LiteLLMLLM)
        assert inst._model == "gpt-oss-120b-think"
        assert inst._url == "http://cerberus-ai:4000/v1/chat/completions"
    finally:
        llm_mod._default = None
