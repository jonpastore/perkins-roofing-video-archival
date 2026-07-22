"""Unit tests for the Cloudflare Workers-AI chat backend (no network — urlopen mocked)."""
import io
import json
from unittest import mock

import pytest

from adapters.llm import CloudflareLLM


def _resp(obj):
    return io.BytesIO(json.dumps(obj).encode())


def _cf(**kw):
    return CloudflareLLM(account="acct123", model="@cf/meta/test", api_token="tok", **kw)


def test_requires_account_and_token(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="CLOUDFLARE_ACCOUNT_ID"):
        CloudflareLLM()


def test_chat_parses_response():
    c = _cf()
    with mock.patch("urllib.request.urlopen", return_value=_resp(
            {"success": True, "result": {"response": "  hello <think>x</think> world  "}})) as m:
        out = c.chat("hi")
    assert out == "hello  world"
    # correct Workers-AI URL (account + model in the path)
    url = m.call_args[0][0].full_url
    assert "accounts/acct123/ai/run/@cf/meta/test" in url


def test_chat_raises_on_api_error():
    c = _cf()
    with mock.patch("urllib.request.urlopen", return_value=_resp(
            {"success": False, "errors": [{"message": "no neurons"}]})):
        with pytest.raises(RuntimeError, match="Cloudflare Workers-AI error"):
            c.chat("hi")


def test_schema_keys_injected_into_prompt():
    c = _cf()
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["body"] = json.loads(req.data.decode())
        return _resp({"success": True, "result": {"response": "{}"}})

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        c.chat("draft it", response_schema={"properties": {"title": {}, "content": {}},
                                            "required": ["title"]})
    sent = captured["body"]["messages"][0]["content"]
    assert "title" in sent and "content" in sent and "valid JSON object" in sent
