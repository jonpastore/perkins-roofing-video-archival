"""Pure email-proofing helpers (no I/O). Build a Gemini proofread prompt and compute
line-level diff suggestions between an original draft and the proofed result."""
import difflib


def build_proof_prompt(draft: str) -> str:
    """Return a prompt that instructs the LLM to proofread *draft* for grammar, clarity,
    and professionalism and to return only the corrected text with no commentary."""
    return (
        "You are a professional copyeditor. Proofread the following sales email for grammar,"
        " clarity, and professionalism. Return ONLY the corrected email text — no explanations,"
        " no commentary, no preamble.\n\n"
        f"---\n{draft}\n---"
    )


def diff_suggestions(original: str, proofed: str) -> list[dict]:
    """Compare *original* and *proofed* line by line; return a list of dicts describing
    every line that changed.  Unchanged lines are omitted.

    Each dict has the shape::

        {"original": "<old line>", "proofed": "<new line>"}

    Lines are compared after splitting on ``\\n``.  Insertions (no matching original line)
    set ``original`` to ``""``; deletions (no matching proofed line) set ``proofed`` to ``""``.
    """
    orig_lines = original.splitlines()
    proof_lines = proofed.splitlines()
    matcher = difflib.SequenceMatcher(None, orig_lines, proof_lines, autojunk=False)
    suggestions: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            orig_chunk = orig_lines[i1:i2]
            proof_chunk = proof_lines[j1:j2]
            for k in range(max(len(orig_chunk), len(proof_chunk))):
                suggestions.append({
                    "original": orig_chunk[k] if k < len(orig_chunk) else "",
                    "proofed": proof_chunk[k] if k < len(proof_chunk) else "",
                })
        elif tag == "delete":
            for line in orig_lines[i1:i2]:
                suggestions.append({"original": line, "proofed": ""})
        elif tag == "insert":
            for line in proof_lines[j1:j2]:
                suggestions.append({"original": "", "proofed": line})
    return suggestions
