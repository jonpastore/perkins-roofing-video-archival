"""Robust parse of an LLM's JSON output (Gemini). Even with response_mime_type=application/json,
article-generation prompts occasionally wrap JSON in fences or emit trailing commas / stray control
chars. Multi-pass repair, ported in spirit from seo-aio's parseClaudeJson and tuned for Gemini."""
import json
import re


def _strip_trailing_commas(s):
    return re.sub(r",(\s*[}\]])", r"\1", s)


def _strip_control(s):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)


def parse_model_json(text):
    """Best-effort parse of model JSON → dict/list; returns {} if unrecoverable."""
    if not text:
        return {}
    s = re.sub(r"^```(?:json)?\s*", "", text.strip())
    s = re.sub(r"\s*```$", "", s).strip()
    starts = [i for i in (s.find("{"), s.find("[")) if i != -1]
    if not starts:
        return {}
    start = min(starts)
    end = max(s.rfind("}"), s.rfind("]"))
    if end <= start:
        return {}
    s = s[start:end + 1]
    for attempt in (s, _strip_trailing_commas(s), _strip_control(_strip_trailing_commas(s))):
        try:
            return json.loads(attempt)
        except (json.JSONDecodeError, ValueError):
            continue
    return {}
