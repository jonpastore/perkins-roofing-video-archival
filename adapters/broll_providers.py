"""B-roll asset provider adapters (I/O — coverage-omitted).

SCAFFOLD: both providers are blocked on API keys.  Uncomment and implement
once credentials are available.

  StockProvider  — Pexels video search (PEXELS_API_KEY)
  AIImageProvider — AI image generation (AI_IMAGE_API_KEY, model TBD)

Interface contract:
  StockProvider.search(keyword: str) -> list[dict]
      Each dict: {"url": str, "keyword": str, "id": str, "thumb": str}

  AIImageProvider.generate(prompt: str) -> dict
      Returns: {"url": str, "keyword": str, "id": str, "thumb": str}
"""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# StockProvider — Pexels video search
# SCAFFOLD: blocked on PEXELS_API_KEY
# ---------------------------------------------------------------------------


class StockProvider:
    """Pexels video search client.

    Args:
        api_key: Pexels API key.  Defaults to the ``PEXELS_API_KEY`` env var.

    Raises:
        RuntimeError: if *api_key* is not set.
    """

    # SCAFFOLD: blocked on PEXELS_API_KEY — uncomment when key is available.
    # API docs: https://www.pexels.com/api/documentation/#videos-search

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.getenv("PEXELS_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "PEXELS_API_KEY env var is not set — "
                "obtain a free key at https://www.pexels.com/api/"
            )

    def search(self, keyword: str, *, per_page: int = 5) -> list[dict]:
        """Search Pexels for videos matching *keyword*.

        Returns a list of asset dicts compatible with ``core.broll.plan_broll``::

            [{"url": str, "keyword": str, "id": str, "thumb": str}, ...]

        Args:
            keyword:  Search query string.
            per_page: Maximum results to return (1–80, Pexels default 15).

        Raises:
            RuntimeError: on HTTP errors or unexpected response shape.
        """
        # SCAFFOLD: blocked on PEXELS_API_KEY
        import requests  # noqa: PLC0415 — lazy import; avoid top-level dep in scaffold

        url = "https://api.pexels.com/videos/search"
        headers = {"Authorization": self._api_key}
        params = {"query": keyword, "per_page": per_page, "orientation": "portrait"}

        resp = requests.get(url, headers=headers, params=params, timeout=15)
        if not resp.ok:
            raise RuntimeError(
                f"Pexels search failed: {resp.status_code} {resp.text[:200]}"
            )

        data = resp.json()
        results: list[dict] = []
        for video in data.get("videos", []):
            # Prefer the smallest HD file for previewing.
            files = video.get("video_files", [])
            hd_files = [f for f in files if f.get("quality") in ("hd", "sd")]
            best = hd_files[0] if hd_files else (files[0] if files else {})
            results.append({
                "url": best.get("link", ""),
                "keyword": keyword,
                "id": str(video.get("id", "")),
                "thumb": video.get("image", ""),
            })
        return results


# ---------------------------------------------------------------------------
# AIImageProvider — AI image generation
# SCAFFOLD: blocked on AI_IMAGE_API_KEY / image-model key
# ---------------------------------------------------------------------------


class AIImageProvider:
    """AI image generation client (model TBD — placeholder for Imagen / DALL-E / etc.).

    Args:
        api_key: Image model API key.  Defaults to the ``AI_IMAGE_API_KEY`` env var.

    Raises:
        RuntimeError: if *api_key* is not set.
    """

    # SCAFFOLD: blocked on AI_IMAGE_API_KEY / image-model key — implement once
    # the image model vendor is confirmed (Imagen 3, DALL-E 3, Stability, etc.).

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.getenv("AI_IMAGE_API_KEY")
        if not self._api_key:
            raise RuntimeError(
                "AI_IMAGE_API_KEY env var is not set — "
                "set it to the image-model vendor key once confirmed"
            )

    def generate(self, prompt: str) -> dict:
        """Generate an image for *prompt* and return an asset dict.

        Returns an asset dict compatible with ``core.broll.plan_broll``::

            {"url": str, "keyword": str, "id": str, "thumb": str}

        The ``url`` is the temporary hosted URL of the generated image.
        Callers must download and cache it before the URL expires.

        Args:
            prompt: Text description of the desired image.

        Raises:
            NotImplementedError: until a vendor is wired up.
        """
        # SCAFFOLD: blocked on AI_IMAGE_API_KEY / image-model key
        raise NotImplementedError(
            "AIImageProvider.generate() is not yet implemented — "
            "wire up a vendor (Imagen 3, DALL-E 3, Stability AI, etc.) "
            "once AI_IMAGE_API_KEY is set."
        )
