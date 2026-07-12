"""Pure Content-Graph logic — timestamp parse, extraction-prompt build, LLM-JSON parse.
Ported from app/graph. The chat() call stays in the app/adapter layer."""

# Long-form Perkins interviews can run 60–100+ minutes. The original POC prompt
# truncated to 9k chars and asked for "max 8" topics, which meant a 1:37 video only
# mined the first ~8 minutes and surfaced exactly 8 topics in the Archive UI. Gemini
# 2.5 Flash has ample context, so use a much larger budget and ask for a comprehensive
# index. (If a local small-context backend is used, the LLM adapter may still enforce
# its own limits; prod uses Vertex.)
TRANSCRIPT_PROMPT_CHAR_LIMIT = 60_000


def secs(ts):
    """Parse an 'mm:ss' timecode to integer seconds; None on any malformed/missing input.

    Returning None (rather than 0) lets callers distinguish a genuine first-frame start
    from a lost/unparseable LLM timecode.  core.retrieval.link() treats None as 'omit ?t='.
    """
    try:
        m, s = ts.split(":")
        return int(m) * 60 + int(s)
    except Exception:
        return None


def build_extract_prompt(segments):
    """Build the deterministic Content-Graph extraction prompt from timed segments.
    segments: list of {"text","start"}. Transcript is capped by TRANSCRIPT_PROMPT_CHAR_LIMIT."""
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
Be comprehensive across the entire transcript, especially for long interviews. Prefer 25-60
distinct topics when enough unique material exists; merge duplicates and avoid generic filler.

TRANSCRIPT:
{timed[:TRANSCRIPT_PROMPT_CHAR_LIMIT]}"""


def parse_nodes(g, graph_version):
    """Turn the extraction LLM's JSON dict into GraphNode-shaped rows."""
    rows = []
    for kind in ("topics", "claims", "objections", "ctas"):
        for it in g.get(kind, []) or []:
            rows.append({
                "kind": kind,
                "label": it.get("label", ""),
                "detail": it.get("detail", ""),
                "start": secs(it.get("ts")),
                "version": graph_version,
            })
    return rows
