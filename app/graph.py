"""Deterministic, versioned Content Graph extraction — the product's real edge.
Prompt build + JSON parse are pure (core.graph); only the chat() call is I/O."""
from core import graph as _cg

from .config import settings
from .llm import chat


def extract(segments):
    g = chat(_cg.build_extract_prompt(segments), want_json=True)
    return _cg.parse_nodes(g, settings.GRAPH_VERSION)
