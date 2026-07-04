"""Pure Content-Graph logic — timestamp parse, extraction-prompt build, LLM-JSON parse.
Ported from app/graph. The chat() call stays in the app/adapter layer."""


def secs(ts):
    """Parse an 'mm:ss' timecode to integer seconds; 0 on any malformed input."""
    try:
        m, s = ts.split(":")
        return int(m) * 60 + int(s)
    except Exception:
        return 0


def build_extract_prompt(segments):
    """Build the deterministic Content-Graph extraction prompt from timed segments.
    segments: list of {"text","start"}. Transcript is truncated to 9000 chars (matches POC)."""
    timed = "\n".join(
        f"[{int(s['start'] // 60):02d}:{int(s['start'] % 60):02d}] {s['text']}" for s in segments
    )
    return f"""You are extracting a knowledge index from a roofing video transcript.
Return ONLY JSON: {{"topics":[{{"label":"","ts":"mm:ss"}}],
"claims":[{{"detail":"","ts":"mm:ss"}}],
"objections":[{{"detail":"","ts":"mm:ss"}}],
"ctas":[{{"detail":"","ts":"mm:ss"}}]}}
Topics = roofing subjects (materials, techniques, problems). Claims = recommendations/warnings.
Objections = concerns/red-flags addressed. CTAs = calls to action. Use transcript timecodes.
Concise, max 8 per list.

TRANSCRIPT:
{timed[:9000]}"""


def parse_nodes(g, graph_version):
    """Turn the extraction LLM's JSON dict into GraphNode-shaped rows."""
    rows = []
    for kind in ("topics", "claims", "objections", "ctas"):
        for it in g.get(kind, []) or []:
            rows.append({
                "kind": kind,
                "label": it.get("label", ""),
                "detail": it.get("detail", ""),
                "start": secs(it.get("ts", "0:0")),
                "version": graph_version,
            })
    return rows
