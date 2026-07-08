"""Content-safety adapter — thin I/O boundary around core/content_safety.py.

Injects the real LLM call (Vertex/Ollama via adapters.llm) into the pure gate.
Coverage-omitted (adapter layer; tested via behavioral validation, not unit tests).
"""

from core.content_safety import GateResult, gate


def judge_with_llm(prompt: str) -> str:
    """Call the default LLM with want_json=True and return the raw response string."""
    from adapters.llm import get_default  # noqa: PLC0415

    return get_default().chat(prompt, want_json=True)


def run_gate(text: str, kind: str) -> GateResult:
    """Run the full two-layer content safety gate with the live LLM judge.

    Args:
        text: Content artifact to evaluate.
        kind: Artifact type — 'article', 'faq', 'caption', 'social', 'avatar_script'.

    Returns:
        GateResult. passed=False means block; do not publish.
    """
    return gate(text, kind, judge_fn=judge_with_llm)
