"""Structured logging + cost tracking (council requirements). JSON logs carry run/video IDs;
Cost counters back the per-run guardrails enforced in llm.py."""
import json
import logging
import sys
import threading
import time

_logger = logging.getLogger("perkins")
if not _logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _logger.addHandler(_h)
    _logger.setLevel(logging.INFO)

def log(event, **fields):
    _logger.info(json.dumps({"event": event, "ts": round(time.time(), 3), **fields}))

class Cost:
    """Process-wide cost counters backing the llm.py per-run guardrail. The Cloud Run Jobs
    run as fresh processes (so their counter naturally scopes to one run), but the long-lived
    API process would accumulate forever and eventually trip the cap on EVERY request — so the
    API resets per request (see api/app.py). Mutation is lock-guarded for the uvicorn threadpool."""
    _lock = threading.Lock()
    embed_calls = 0
    embed_items = 0
    llm_calls = 0

    @classmethod
    def add_embed(cls, n):
        with cls._lock:
            cls.embed_calls += 1; cls.embed_items += n

    @classmethod
    def add_llm(cls):
        with cls._lock:
            cls.llm_calls += 1

    @classmethod
    def reset(cls):
        with cls._lock:
            cls.embed_calls = cls.embed_items = cls.llm_calls = 0

    @classmethod
    def report(cls):
        return {"embed_calls": cls.embed_calls, "embed_items": cls.embed_items, "llm_calls": cls.llm_calls}
