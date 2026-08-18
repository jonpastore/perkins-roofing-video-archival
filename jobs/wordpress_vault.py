"""CLI: prompt for WP username + Application Password, verify REST, then vault.

    PYTHONPATH=. WP_URL=https://… WP_USER=jon \\
      .venv/bin/python -m jobs.wordpress_vault --prompt
"""
from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = argv if argv is not None else sys.argv[1:]
    if "--prompt" not in args:
        log.error("usage: python -m jobs.wordpress_vault --prompt")
        return 2
    from core.verified_secret import can_prompt  # noqa: PLC0415
    from core.wordpress_creds import prompt_and_vault  # noqa: PLC0415

    if not can_prompt():
        log.error("stdin is not a TTY — run this on a keyboard, not from an agent")
        return 1
    url = (os.environ.get("WP_URL") or "").strip()
    if not url:
        from adapters.wordpress import resolved_wp_url  # noqa: PLC0415
        url = resolved_wp_url()
    if not url:
        log.error("WP_URL is unset")
        return 1
    prompt_and_vault(wp_url=url, default_user=os.environ.get("WP_USER", "jon"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
