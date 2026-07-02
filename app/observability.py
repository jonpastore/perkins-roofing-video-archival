"""Structured logging + cost tracking (council requirements). JSON logs carry run/video IDs;
Cost counters back the per-run guardrails enforced in llm.py."""
import json, logging, sys, time

_logger = logging.getLogger("perkins")
if not _logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _logger.addHandler(_h)
    _logger.setLevel(logging.INFO)

def log(event, **fields):
    _logger.info(json.dumps({"event": event, "ts": round(time.time(), 3), **fields}))

class Cost:
    embed_calls = 0
    embed_items = 0
    llm_calls = 0

    @classmethod
    def add_embed(cls, n):
        cls.embed_calls += 1; cls.embed_items += n

    @classmethod
    def add_llm(cls):
        cls.llm_calls += 1

    @classmethod
    def report(cls):
        return {"embed_calls": cls.embed_calls, "embed_items": cls.embed_items, "llm_calls": cls.llm_calls}
