"""Pure comment-reply heuristics — no I/O. Tested at high coverage in tests/core/test_comments.py."""

import re

# Interrogative words that, when starting the first sentence AND accompanied by
# a '?', signal a genuine question needing a reply.
_LEADING_INTERROGATIVES = re.compile(
    r"^(who|what|when|where|why|how|which|can|could|would|should|does|do|is|are|will)\b",
    re.IGNORECASE,
)

# Split on sentence-ending punctuation to isolate the first sentence.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _first_sentence(text: str) -> str:
    """Return the first sentence of *text* (lowercased, stripped)."""
    parts = _SENTENCE_SPLIT.split(text.strip(), maxsplit=1)
    return parts[0].strip() if parts else text.strip()


def needs_reply(text: str, has_channel_reply: bool) -> bool:
    """Return True if a comment warrants a reply draft.

    Rules (evaluated in order):
      1. Never flag if the channel has already replied (idempotent).
      2. Flag if the text ends with '?' — the whole comment is a question.
      3. Flag if the FIRST sentence starts with an interrogative word (who/what/
         when/where/why/how/which/can/could/would/should/does/do/is/are/will)
         AND the comment contains a '?' — so "Is there a warranty on this?" is
         flagged but "Is there a warranty on this" (statement) is not.

    Plain compliments ("This is great", "What a great video!") are NOT flagged.
    """
    if has_channel_reply:
        return False
    stripped = (text or "").strip()
    if not stripped:
        return False
    # Rule 2: explicit question mark at end of full comment
    if stripped.endswith("?"):
        return True
    # Rule 3: first sentence starts with interrogative AND comment has a '?'
    if "?" in stripped:
        first = _first_sentence(stripped)
        if _LEADING_INTERROGATIVES.match(first):
            return True
    return False
