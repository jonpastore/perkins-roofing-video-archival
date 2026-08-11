#!/usr/bin/env python3
"""Load Josh's caption master prompt into PlatformConfig VIDEO_DESCRIPTION_PROMPT.

The key ships EMPTY, so `core.video_description.DEFAULT_PROMPT` — a plain YouTube-description
fallback — is what actually runs. Josh's prompt (his 2026-08-11 13:41 email, "Social media prompt
+ Metal Roof Clip Spacing Sheet") is the register Perkins posts in: Instagram/Facebook captions,
hook first, hashtags, no "Here is your caption" preamble.

The source file in docs/ is the VERBATIM EMAIL — greeting, signature block and a confidentiality
notice wrap the prompt. Those must not reach the model: an instruction set that ends in "Please
notify the sender immediately" is an invitation to write it into a caption. This script slices
out the prompt body between the MASTER PROMPT heading and the sign-off, so docs/ stays the
unedited archive and the config gets only the instructions.

There is no {transcript} placeholder in Josh's text and that is fine — render_prompt appends the
transcript when the template omits it (core/video_description.py).

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/seed_video_description_prompt.py [--apply]
       (prints what it would write and changes nothing unless --apply is passed)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

KEY = "VIDEO_DESCRIPTION_PROMPT"
SOURCE = Path(__file__).resolve().parent.parent / "docs" / "josh-social-caption-master-prompt-2026-08-11.txt"
START = "# MASTER PROMPT"
END = "Best regards,"


#: Josh's text says "approximately 5 relevant hashtags". Jon, 2026-08-11: the limit is strict.
#: Applied here rather than by editing docs/ — that file is the archived email and stays verbatim.
#: `core.video_description.enforce` also trims to MAX_HASHTAGS after generation, because a prompt
#: is a request and a ceiling that only exists in the prompt is not a ceiling.
HASHTAG_RULE_FROM = "End every caption with approximately 5 relevant hashtags."
HASHTAG_RULE_TO = (
    "End every caption with EXACTLY 5 relevant hashtags. Never more than 5. "
    "A caption with a sixth hashtag is wrong even if every hashtag is relevant."
)


def extract_prompt(email_text: str) -> str:
    """Return just the prompt body from Josh's email.

    Raises ValueError rather than falling back to the whole email: seeding the signature and the
    confidentiality notice as model instructions is worse than seeding nothing.
    """
    start = email_text.find(START)
    if start < 0:
        raise ValueError(f"{START!r} not found — the source file is not the expected email")
    end = email_text.find(END, start)
    if end < 0:
        raise ValueError(f"{END!r} not found — cannot tell where the prompt stops")
    body = email_text[start:end].strip()
    if len(body) < 1000:
        raise ValueError(f"extracted prompt is only {len(body)} chars — the slice is wrong")
    if HASHTAG_RULE_FROM not in body:
        raise ValueError("the hashtag rule is not where this script expects it — Josh's prompt "
                         "changed, so re-check the 5-hashtag override before seeding")
    return body.replace(HASHTAG_RULE_FROM, HASHTAG_RULE_TO)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write it (otherwise print and exit)")
    args = ap.parse_args()

    prompt = extract_prompt(SOURCE.read_text(encoding="utf-8"))

    from app.models import PlatformConfig, PlatformSessionLocal  # noqa: PLC0415

    with PlatformSessionLocal() as pdb:
        pdb.info["platform_scope"] = True
        row = pdb.get(PlatformConfig, KEY)
        current = (row.value if row else "") or ""

        print(f"source:  {SOURCE}")
        print(f"extract: {len(prompt)} chars, {prompt.count(chr(10)) + 1} lines")
        print(f"current: {len(current)} chars" + (" (EMPTY — DEFAULT_PROMPT is in use)" if not current.strip() else ""))
        if current.strip() == prompt:
            print("\nAlready seeded; nothing to do.")
            return
        print("\n--- first 400 chars to be written ---")
        print(prompt[:400])
        print("--- last 200 ---")
        print(prompt[-200:])

        if not args.apply:
            print("\nDry run. Re-run with --apply to write.")
            return

        if row is None:
            pdb.add(PlatformConfig(key=KEY, value=prompt, updated_by="seed_video_description_prompt"))
        else:
            row.value = prompt
            row.updated_by = "seed_video_description_prompt"
        pdb.commit()

    # Read it back through a NEW session: a write nothing reads back is this repo's recurring
    # defect, and platform_config is exactly where it bit last time.
    with PlatformSessionLocal() as pdb:
        pdb.info["platform_scope"] = True
        stored = (pdb.get(PlatformConfig, KEY).value or "")
    if stored != prompt:
        sys.exit(f"WROTE {len(prompt)} chars but READ BACK {len(stored)} — not seeded")
    print(f"\nApplied and read back: {len(stored)} chars in {KEY}.")


if __name__ == "__main__":
    main()
