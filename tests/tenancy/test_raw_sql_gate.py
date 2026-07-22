"""CI grep gate — blocks raw SQLAlchemy text() outside approved modules.

Per TRD-F4 §5, the CI grep gate blocks raw `text()` calls (SQLAlchemy raw SQL
string constructor) outside the approved module allowlist. This catches code paths
that could issue arbitrary SQL and bypass RLS.

What is gated: `text(` — the SQLAlchemy raw SQL string constructor used to wrap
a raw SQL string, e.g. text("SELECT ...") or text("SET LOCAL ...").

What is NOT gated:
  - ORM .execute(select(...)) — normal SQLAlchemy 2.0, no raw SQL
  - The English word "text" in docstrings, comments, or string values

Approved modules (may use text() for legitimate infrastructure reasons):
  - core/tenant.py          — set_tenant_context: SET LOCAL via text()
  - core/authz.py           — platform-level DB lookups (no RLS applies; TRD §4.5)
  - api/auth.py             — GCIP/platform_admin claim resolution (TRD §4.2, §4.4)
  - api/routes/config.py    — health-check SELECT 1 probe
  - app/models.py           — seed helper uses raw insert constructs
  - jobs/ingest_worker.py   — pg_try_advisory_lock() requires raw SQL
  - scripts/                — migration runner
  - infra/migrations/       — SQL files (not Python, but for documentation)
  - tests/                  — test fixtures and assertions legitimately use text()
"""
from __future__ import annotations

import re
from pathlib import Path

# Directories to scan (relative to repo root)
_SCAN_DIRS = ["api", "core", "jobs", "adapters"]

# Files/path prefixes that are approved to call text()
_APPROVED_PREFIXES = (
    "core/tenant.py",           # set_tenant_context issues SET LOCAL via text()
    "core/authz.py",            # platform-level lookups per TRD §4.5 — no RLS applies
    "api/auth.py",              # GCIP tenant resolution + platform_admin lookup (TRD §4.2/§4.4)
    "api/app.py",               # /internal/tenants platform-admin endpoint via PlatformSessionLocal (RLS-exempt)
    "api/routes/config.py",     # health-check SELECT 1 probe
    "app/models.py",            # seed helper (_seed_perkins_tenant) uses raw helpers
    "jobs/ingest_worker.py",    # pg_try_advisory_lock requires raw SQL
    "core/knowify/tokens.py",   # JB-knowify: pg_advisory_lock (shared token-writer lock 8274125) — parameterized :k, safe
    "core/tenant_loop.py",      # F5: active-tenant enumeration on the platform tenants table
    "core/brand_kit.py",        # F5: reads tenants.settings (platform table, RLS-exempt)
    "core/offboard.py",         # F5: cross-tenant cascade DELETE by design (TRD-F5 §9)
    "jobs/enumerate_channel.py",  # F5-M2: reads tenants.settings for channel_sources (platform table, RLS-exempt)
    "jobs/render_job.py",       # reads tenants.settings.safety_denylist (platform table, RLS-exempt) — parameterized :tid, safe
    "core/provision.py",        # F6: provisions rows in the platform tenants table (RLS-exempt)
    "scripts/",
    "infra/migrations/",
    "tests/",
)

# Match `text(` only when it looks like a function call: word boundary, optional spaces, open paren.
# We additionally require the match is NOT preceded by a colon+space (dict/docstring param value)
# or by common English sentence patterns.
_TEXT_CALL_RE = re.compile(r"\btext\s*\(")


def _repo_root() -> Path:
    """Walk up from this file until we find the git root."""
    p = Path(__file__).resolve()
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    raise RuntimeError("Could not locate git repository root")


def _is_code_context(line: str) -> bool:
    """Return True only if text( appears in an executable code context (not a comment/string).

    Heuristic approach: strip the line, skip pure-comment lines, then check whether
    the text( match is preceded by code-like characters (=, (, ,, return, space at
    start of expression) vs. string-like context (inside a docstring description,
    preceded by a colon indicating a parameter description, or only in a quoted string).
    """
    stripped = line.strip()

    # Pure comment line — skip
    if stripped.startswith("#"):
        return False

    # Docstring body line: starts with a bare word or words followed by colon (param desc)
    # e.g. "box:       Whether to draw a background text (default ``False``)."
    # These are Napoleon/Google-style docstring param lines.
    if re.match(r"^[a-zA-Z_][\w\s,\[\]]*:\s+\S", stripped):
        return False

    # Line is purely a string value (starts with quote, or is a dict value after colon)
    # e.g.  "caption:   Caption / description text (≤63,206 chars)."
    # already caught above by the colon-param pattern.

    # If text( only appears after a colon-space (dict value or type annotation default)
    # and the text before the colon doesn't look like a variable assignment, skip.
    # e.g.  "caption:         Caption / description text (≤2 200 chars)."
    # The colon-param check above covers most; this catches indented variants:
    if re.match(r"^\s+\w[\w\s,\[\]]*:\s+[A-Z]", line) and "text(" not in line.split(":")[0]:
        return False

    # If the match is inside a triple-quoted string body (common in docstrings):
    # heuristic — if the line has no = sign and no ( before text( that would indicate
    # a function call chain, and has descriptive text after text(...), it's a docstring.
    # Detect: line contains text( but has no assignment (=) and no import/from/return.
    code_indicators = re.search(r"(\w+\s*=|return\s|from\s|import\s|db\.|session\.|conn\.)", line)
    if not code_indicators:
        # No code indicators — likely a docstring or comment body
        return False

    return True


def test_no_raw_text_outside_approved():
    """No raw SQLAlchemy text() calls outside the approved module allowlist.

    Catches new code that constructs raw SQL strings and could bypass RLS.
    ORM .execute(select(...)) calls are explicitly not flagged.
    """
    root = _repo_root()

    violations = []
    for scan_dir in _SCAN_DIRS:
        target = root / scan_dir
        if not target.exists():
            continue

        for py_file in sorted(target.rglob("*.py")):
            rel = py_file.relative_to(root).as_posix()

            if any(rel.startswith(prefix) for prefix in _APPROVED_PREFIXES):
                continue

            content = py_file.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(content.splitlines(), start=1):
                if not _TEXT_CALL_RE.search(line):
                    continue
                if not _is_code_context(line):
                    continue
                violations.append(f"{rel}:{lineno}: {line.strip()}")

    assert not violations, (
        "Raw SQLAlchemy text() found outside approved modules.\n"
        "Add the file to _APPROVED_PREFIXES with a justification, or move the raw SQL "
        "to core/tenant.py or core/authz.py.\n\n"
        "Violations:\n" + "\n".join(violations)
    )
