"""Embeddings + LLM with backend routing + cost guardrails. Dev = cerberus Ollama.
Prod backends: Vertex AI / Anthropic (guarded imports — explicit, never silent)."""
import json
import os
import re
import urllib.request

from .config import settings
from .observability import Cost


def _ollama(path, payload, timeout=300):
    req = urllib.request.Request(settings.OLLAMA_URL + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

# ---------------- embeddings ----------------
def embed(texts):
    Cost.add_embed(len(texts))
    if settings.EMBED_BACKEND == "ollama":
        return _ollama("/api/embed", {"model": settings.EMBED_MODEL, "input": texts})["embeddings"]
    if settings.EMBED_BACKEND == "vertex":
        # Use the dedicated Vertex embedder — NOT get_default(), which is routed by LLM_BACKEND
        # (an ollama chat backend must still embed via Vertex; get_default would recurse).
        from adapters.llm import get_embedder
        return get_embedder().embed(texts)
    raise NotImplementedError("embed backend " + settings.EMBED_BACKEND)

# ---------------- chat ----------------
_LLM_CAP = settings.MAX_VIDEOS_PER_RUN * 40  # crude per-process guardrail

def chat(prompt, want_json=False, timeout=300):
    if Cost.llm_calls >= _LLM_CAP:
        raise RuntimeError(f"LLM call cap reached ({_LLM_CAP}) — cost guardrail")
    Cost.add_llm()
    if settings.LLM_BACKEND == "ollama":
        # think=False is REQUIRED: the dev model (qwen3.6) is a hybrid reasoning model and will
        # otherwise burn a few hundred reasoning tokens before every answer (126 eval tokens to
        # say "OK" vs 2 with it off). Ollama returns that reasoning in a separate `thinking`
        # field, so the <think> strip below does NOT catch it.
        out = _ollama("/api/generate", {"model": settings.LLM_MODEL, "prompt": prompt, "stream": False,
                                        "think": False,
                                        "options": {"temperature": 0.1 if want_json else 0.4, "num_ctx": 8192}})
        txt = re.sub(r"<think>.*?</think>", "", out.get("response", ""), flags=re.S).strip()
    elif settings.LLM_BACKEND == "anthropic":
        txt = _anthropic(prompt)
    elif settings.LLM_BACKEND == "vertex":
        from adapters.llm import get_default
        txt = get_default().chat(prompt, want_json=want_json)
    else:
        raise NotImplementedError("llm backend " + settings.LLM_BACKEND)
    if want_json:
        a, b = txt.find("{"), txt.rfind("}")
        if a != -1 and b != -1:
            try: return json.loads(txt[a:b + 1])
            except Exception: return {}
        return {}
    return txt

def _anthropic(prompt):
    try:
        import anthropic
    except ImportError:
        raise NotImplementedError("pip install anthropic + set ANTHROPIC_API_KEY for prod LLM backend")
    c = anthropic.Anthropic()
    m = c.messages.create(model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
                          max_tokens=1500, messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in m.content if getattr(b, "type", "") == "text")
