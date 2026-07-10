"""Pure ask-cache logic — no I/O.

Cache flow:
  1. Embed the incoming question (caller provides the embedding).
  2. Probe AskCache via cosine similarity on the tenant-scoped DB.
     - similarity >= 0.95 AND not stale -> cache HIT: return cached answer.
     - 0.85 <= similarity < 0.95       -> SUGGEST: surface up to 3 similar questions.
     - similarity < 0.85               -> MISS: run the full LLM pipeline, write-through.
  3. Write-through: after a miss, INSERT the new Q+A (deduped by question_norm).

SQLite fallback (dev/test): pgvector operators are unavailable; fall back to exact
question_norm match for hits and prefix/substring match for suggestions.

Pre-seeding from faq_entries is a follow-up task; document in the /ask route docstring.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

def normalize_question(q: str) -> str:
    """Lowercase, collapse whitespace and strip punctuation to a canonical form.

    Used as a cheap dedup key before inserting a new cache entry, and as the
    fallback match key on SQLite where pgvector is unavailable.
    """
    # Unicode normalise -> strip accents
    nfd = unicodedata.normalize("NFD", q)
    ascii_only = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    # Lowercase
    lowered = ascii_only.lower()
    # Strip punctuation (keep alphanumeric + spaces)
    stripped = re.sub(r"[^a-z0-9\s]", " ", lowered)
    # Collapse whitespace
    return re.sub(r"\s+", " ", stripped).strip()


# ---------------------------------------------------------------------------
# Similarity thresholds
# ---------------------------------------------------------------------------

def should_serve(similarity: float, threshold: float = 0.95) -> bool:
    """Return True when similarity is high enough to serve the cached answer directly."""
    return similarity >= threshold


def should_suggest(similarity: float, low: float = 0.85, high: float = 0.95) -> bool:
    """Return True when similarity falls in the suggestion band (not a direct hit)."""
    return low <= similarity < high


# ---------------------------------------------------------------------------
# Cache entry construction
# ---------------------------------------------------------------------------

def build_cache_entry(question: str, answer_dict: dict, pipeline_version: str) -> dict:
    """Build a dict suitable for inserting into the ask_cache table.

    Returns only the pure-data fields (no tenant_id — the caller stamps that).
    """
    return {
        "question": question,
        "question_norm": normalize_question(question),
        "embedding": None,          # caller fills this after embed()
        "answer_json": answer_dict,
        "pipeline_version": pipeline_version,
        "hit_count": 0,
    }


# ---------------------------------------------------------------------------
# Staleness check
# ---------------------------------------------------------------------------

def is_stale(
    entry_created_at: datetime,
    entry_pipeline_version: str,
    current_version: str,
    now: datetime | None = None,
    ttl_days: int = 30,
) -> bool:
    """Return True if the cache entry should be treated as stale and bypassed.

    An entry is stale when either:
      - its pipeline_version differs from the current version (model/prompt changed), OR
      - it was created more than ttl_days ago (content drift).
    """
    if now is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Version mismatch
    if entry_pipeline_version != current_version:
        return True

    # Age check (both datetimes assumed tz-naive UTC, matching models._utcnow())
    created = entry_created_at
    if created.tzinfo is not None:
        created = created.replace(tzinfo=None)
    age_days = (now - created).total_seconds() / 86400
    return age_days > ttl_days
