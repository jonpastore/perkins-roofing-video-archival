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


def get_tc_ai_prompts_block() -> dict:
    """Return the static AI-FAQ block data for use by renderers and tests."""
    return {
        "cover_letter": COVER_LETTER,
        "attorney_disclaimer": ATTORNEY_DISCLAIMER,
        "recommended_prompts": RECOMMENDED_PROMPTS,
    }
