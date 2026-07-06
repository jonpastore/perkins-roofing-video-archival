"""Pure comment-reply heuristics — no I/O. Tested at high coverage in tests/core/test_comments.py."""

import re

# Question words that signal a comment needs a reply when no channel reply exists.
_QUESTION_WORDS = re.compile(
    r"\b(who|what|when|where|why|how|can|does|is|should)\b", re.IGNORECASE
)


def needs_reply(text: str, has_channel_reply: bool) -> bool:
    """Return True if a comment warrants a reply draft.

    Rules:
      - Never flag if the channel has already replied (idempotent).
      - Flag if the text ends with '?' (explicit question).
      - Flag if the text contains a question word (who/what/when/where/why/how/can/does/is/should).
    """
    if has_channel_reply:
        return False
    stripped = (text or "").strip()
    if stripped.endswith("?"):
        return True
    if _QUESTION_WORDS.search(stripped):
        return True
    return False
