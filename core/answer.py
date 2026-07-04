"""Pure answer logic — confidence-gated abstention + prompt construction.
Ported from app/answer.ask (the LLM call itself stays in the adapter/app layer)."""


def should_abstain(top_score, threshold):
    """Below the calibrated confidence threshold we refuse rather than hallucinate.
    With no hits the caller passes top_score=0.0, which abstains for any positive threshold."""
    return top_score < threshold


def build_answer_prompt(query, contexts, key_points):
    """Build the grounded 'Ask Tim' prompt.

    contexts:   list of (source_link, transcript_text).
    key_points: list of (source_link, label_or_detail) from the Content Graph.
    """
    key = "\n".join(f"(key point, source {lk}) {label}" for lk, label in key_points[:20])
    ctx = "\n\n".join(f"(source {lk}) {text}" for lk, text in contexts)
    return ("Answer the homeowner's question using ONLY the material below. Cite the source link "
            "after each point. Prefer KEY POINTS (verified facts from the video). If the material "
            "does not cover it, say you couldn't find it in Tim's videos.\n\n"
            f"QUESTION: {query}\n\nKEY POINTS:\n{key}\n\nTRANSCRIPT EXCERPTS:\n{ctx}")
