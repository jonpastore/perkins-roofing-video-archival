from core.llm_types import FakeLLM


def test_fake_chat_returns_configured_reply():
    llm = FakeLLM(chat_reply='{"ok": true}')
    assert llm.chat("hi", want_json=True) == '{"ok": true}'


def test_fake_embed_matches_gemini_dim():
    llm = FakeLLM()
    vecs = llm.embed(["a", "b"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 3072
