#!/usr/bin/env python3
"""Compute the canonical RFC 8785 SHA-256 hash for a pricing config JSON file.

Strips underscore-prefixed annotation keys before hashing, matching
core.pricing_config.compute_hash exactly.

Usage:
    python scripts/compute_config_hash.py infra/fixtures/pricing_config_exhibit_b.json
    python scripts/compute_config_hash.py path/to/config.json

Output: the 64-character hex digest, suitable for seeding or verification.

Referenced in TRD-F2 §6 and §8.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <config.json>", file=sys.stderr)
        return 1

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        return 1

    config_dict = json.loads(path.read_text())

    from core.pricing_config import compute_hash
    digest = compute_hash(config_dict)
    print(digest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
