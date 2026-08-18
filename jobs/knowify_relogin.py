"""CLI: mint Knowify OAuth tokens via vaulted login + Playwright.

    PYTHONPATH=. GOOGLE_CLOUD_PROJECT=... .venv/bin/python -m jobs.knowify_relogin
    .venv/bin/python -m jobs.knowify_relogin --headed   # debug the login page
    .venv/bin/python -m jobs.knowify_relogin --prompt   # type user/pass; vaulted after OAuth works
"""
from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = argv if argv is not None else sys.argv[1:]
    from core.knowify.playwright_relogin import relogin_or_prompt  # noqa: PLC0415

    if _playwright_missing():
        log.error("playwright is not installed (pip install playwright && playwright install chromium)")
        return 1
    relogin_or_prompt(headless="--headed" not in args, force_prompt="--prompt" in args)
    return 0


def _playwright_missing() -> bool:
    from core.knowify.playwright_relogin import _playwright_import  # noqa: PLC0415
    return _playwright_import() is None


if __name__ == "__main__":
    sys.exit(main())
