"""T&C AI-FAQ static block — pure constants and one accessor function, no I/O."""

COVER_LETTER = (
    "While we recommend reading everything yourself and thoroughly understanding "
    "the agreement you're entering into, we've created an FAQ for your review on "
    "the last page and here's a concise summary:"
)

ATTORNEY_DISCLAIMER = (
    "AI is not a replacement for legal counsel, and we always recommend for full "
    "validation and protection that you have an attorney review this agreement."
)

RECOMMENDED_PROMPTS = [
    "Summarize my obligations and what I'm agreeing to.",
    "What are the payment terms, deposits, and any penalties or late fees?",
    "What are my cancellation/rescission rights and any fees?",
    "What warranties and guarantees am I getting, and what voids them?",
    "What happens in delays, weather, or unforeseen conditions?",
    "What am I responsible for vs. the contractor?",
]

CONTRACT_REVIEW_SYSTEM_PROMPT = (
    "You are reviewing a roofing contract for a homeowner. You are not a lawyer and "
    "must not provide legal advice. Explain the contract in plain English, cite the "
    "exact clauses you rely on, and clearly say when a question is not answered by "
    "the contract text. Recommend attorney review for legal decisions."
)

CONTRACT_REVIEW_USER_PROMPTS = [
    "Read this contract and list the top 10 things I should understand before signing. "
    "For each item, quote the exact clause.",
    "Compare the FAQ answers against this contract. Which FAQs are directly supported, "
    "which need nuance, and which are not supported?",
    "For each FAQ below, identify the contract clause(s) that relate to it and explain any caveats or exceptions.",
    "What homeowner obligations could create extra costs, delays, or warranty issues? Quote the clauses.",
    "What cancellation, payment, change-order, warranty, maintenance, liability, "
    "and access provisions should I ask about?",
    "Create a plain-English checklist of questions to ask Perkins before signing, based only on the contract text.",
]


def get_tc_ai_prompts_block() -> dict:
    """Return the static AI-FAQ block data for use by renderers and tests."""
    return {
        "cover_letter": COVER_LETTER,
        "attorney_disclaimer": ATTORNEY_DISCLAIMER,
        "recommended_prompts": RECOMMENDED_PROMPTS,
        "contract_review_system_prompt": CONTRACT_REVIEW_SYSTEM_PROMPT,
        "contract_review_user_prompts": CONTRACT_REVIEW_USER_PROMPTS,
    }


def build_contract_review_prompt(tc_text: str, faq_items: list[dict] | None = None) -> dict:
    """Return copy/paste AI prompts for reviewing T&C text against generated FAQs.

    Pure helper: no model calls. The UI/API can expose these prompts so a human can
    use an external AI tool to explain the contract and cross-check FAQs both ways:
    contract → FAQ coverage and FAQ → contract support.
    """
    faq_block = ""
    if faq_items:
        lines = []
        for i, item in enumerate(faq_items, 1):
            q = item.get("question") or item.get("q") or ""
            a = item.get("answer") or item.get("a") or ""
            if q or a:
                lines.append(f"{i}. Q: {q}\n   A: {a}")
        if lines:
            faq_block = "\n\nFAQS TO CHECK:\n" + "\n".join(lines)

    user_prompt = (
        "Review the roofing contract Terms & Conditions below. Explain it in plain English, "
        "quote exact supporting clauses, and identify which FAQ items are supported, need nuance, "
        "or are not answered by the text. Do not invent obligations.\n\n"
        "CONTRACT TERMS & CONDITIONS:\n"
        f"{tc_text}"
        f"{faq_block}"
    )
    return {
        "system_prompt": CONTRACT_REVIEW_SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "suggested_followups": CONTRACT_REVIEW_USER_PROMPTS,
    }
