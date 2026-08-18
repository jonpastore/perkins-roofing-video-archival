"""CLI: repair YouTube API key or reply OAuth. Verify, then vault.

    PYTHONPATH=. GOOGLE_CLOUD_PROJECT=... \\
      .venv/bin/python -m jobs.youtube_relogin --prompt
    .venv/bin/python -m jobs.youtube_relogin --headed
    .venv/bin/python -m jobs.youtube_relogin --api-key
"""
from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = argv if argv is not None else sys.argv[1:]
    if "--api-key" in args:
        from core.verified_secret import can_prompt  # noqa: PLC0415
        from core.youtube_creds import prompt_and_vault_api_key  # noqa: PLC0415

        if not can_prompt():
            log.error("stdin is not a TTY — run this on a keyboard, not from an agent")
            return 1
        prompt_and_vault_api_key()
        return 0
    from core.youtube_playwright import _playwright_import, relogin_or_prompt  # noqa: PLC0415

    if _playwright_import() is None:
        log.error("playwright is not installed (pip install playwright && playwright install chromium)")
        return 1
    relogin_or_prompt(headless="--headed" not in args, force_prompt="--prompt" in args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
