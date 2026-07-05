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


def build_faq_answer_prompt(question, sources):
    """Build a concise, professional FAQ-answer prompt.

    sources: list of (n, title, text) where n is the 1-based citation number.
    The model answers in 2-4 tight sentences, brand-professional, and cites facts
    with bracketed numbers like [1] that map to the numbered sources. It must NOT
    write any URLs — the caller appends the numbered links after the prose.
    """
    src = "\n\n".join(f"SOURCE [{n}] — {title}\n{text}" for n, title, text in sources)
    return (
        "You are the content team for Perkins Roofing, a professional South Florida roofing "
        "company, writing the answer to one Frequently Asked Question for the company website.\n"
        "Write a clear, professional, and CONCISE answer (2-4 sentences, no fluff, no repetition) "
        "using ONLY the source material below. Speak in the company's confident, helpful voice.\n"
        "Cite the specific sources you use with bracketed numbers like [1] or [2] that match the "
        "SOURCE numbers below. Do NOT write any URLs or links — just the [n] markers. Do not "
        "restate the question. If the sources do not answer it, reply with exactly: NO_ANSWER\n\n"
        f"QUESTION: {question}\n\n{src}"
    )
