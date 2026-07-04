"""Serper.dev SERP adapter — I/O only. No business logic here."""

import os

import requests


def fetch_serp(query: str) -> dict:
    """POST to Serper.dev and return a normalized SERP dict.

    Returns:
        {
            "organic": [...],
            "peopleAlsoAsk": [...],
            "answerBox": ... | None,
            "knowledgeGraph": ... | None,
            "relatedSearches": [...],
        }

    Raises:
        RuntimeError if SERPER_API_KEY is unset.
        requests.HTTPError on non-2xx responses.
    """
    api_key = os.getenv("SERPER_API_KEY")
    if not api_key:
        raise RuntimeError("SERPER_API_KEY env var is not set")

    resp = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    organic = [
        {
            "title": (item.get("title") or "").strip(),
            "link": (item.get("link") or "").strip(),
            "snippet": (item.get("snippet") or "").strip(),
            "position": item.get("position") or (i + 1),
            "date": item.get("date"),
            "sitelinks": item.get("sitelinks"),
        }
        for i, item in enumerate(data.get("organic") or [])
        if (item.get("title") or "").strip() and (item.get("link") or "").strip()
    ]

    people_also_ask = [
        {
            "question": (item.get("question") or "").strip(),
            "snippet": (item.get("snippet") or "").strip() or None,
            "link": (item.get("link") or "").strip() or None,
        }
        for item in (data.get("peopleAlsoAsk") or [])
        if (item.get("question") or "").strip()
    ]

    raw_ab = data.get("answerBox")
    answer_box = (
        {
            "title": (raw_ab.get("title") or "").strip() or None,
            "answer": (raw_ab.get("answer") or "").strip() or None,
            "snippet": (raw_ab.get("snippet") or "").strip() or None,
            "link": (raw_ab.get("link") or "").strip() or None,
        }
        if raw_ab
        else None
    )

    raw_kg = data.get("knowledgeGraph")
    knowledge_graph = (
        {
            "title": (raw_kg.get("title") or "").strip() or None,
            "type": (raw_kg.get("type") or "").strip() or None,
            "description": (raw_kg.get("description") or "").strip() or None,
            "attributes": raw_kg.get("attributes") or {},
        }
        if raw_kg
        else None
    )

    related_searches = [
        (item.get("query") or "").strip()
        for item in (data.get("relatedSearches") or [])
        if (item.get("query") or "").strip()
    ]

    return {
        "organic": organic,
        "peopleAlsoAsk": people_also_ask,
        "answerBox": answer_box,
        "knowledgeGraph": knowledge_graph,
        "relatedSearches": related_searches,
    }
