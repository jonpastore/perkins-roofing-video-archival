"""Deterministic, versioned Content Graph extraction — the product's real edge."""
from .config import settings
from .llm import chat

def _secs(ts):
    try:
        m, s = ts.split(":"); return int(m) * 60 + int(s)
    except Exception:
        return 0

def extract(segments):
    timed = "\n".join(f"[{int(s['start']//60):02d}:{int(s['start']%60):02d}] {s['text']}" for s in segments)
    prompt = f"""You are extracting a knowledge index from a roofing video transcript.
Return ONLY JSON: {{"topics":[{{"label":"","ts":"mm:ss"}}],
"claims":[{{"detail":"","ts":"mm:ss"}}],
"objections":[{{"detail":"","ts":"mm:ss"}}],
"ctas":[{{"detail":"","ts":"mm:ss"}}]}}
Topics = roofing subjects (materials, techniques, problems). Claims = recommendations/warnings.
Objections = concerns/red-flags addressed. CTAs = calls to action. Use transcript timecodes.
Concise, max 8 per list.

TRANSCRIPT:
{timed[:9000]}"""
    g = chat(prompt, want_json=True)
    rows = []
    for kind in ("topics", "claims", "objections", "ctas"):
        for it in g.get(kind, []) or []:
            rows.append({"kind": kind, "label": it.get("label", ""), "detail": it.get("detail", ""),
                         "start": _secs(it.get("ts", "0:0")), "version": settings.GRAPH_VERSION})
    return rows
