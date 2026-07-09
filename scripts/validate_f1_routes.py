#!/usr/bin/env python3
"""F1 route completeness validator (TRD-F1 §6 Group 3).

Parses web/src/App.tsx as text and asserts:
  1. Every required tab key appears in the TabContent render switch.
  2. Legacy keys users and config have a fallback handler (no silent 404).
  3. The new tab keys quoting, admin-config, contract-faq, status-view are present.
  4. No tab key that existed in the old ROLE_CONFIG is silently dropped.

Run from the repo root:
    python3 scripts/validate_f1_routes.py
Exits 0 on success, 1 on failure (prints failing assertions).
"""

import re
import sys
from pathlib import Path

APP_TSX = Path(__file__).parent.parent / "web" / "src" / "App.tsx"

# Every key that must route to something (either a real page or a backward-compat redirect).
REQUIRED_TAB_KEYS = [
    # Pinned
    "dashboard",
    # Knowledge Base
    "search-ask",
    "faq",
    "archive",
    "contract-faq",
    # Marketing
    "opportunities",
    "articles",
    "scheduling",
    "clip-studio",
    "comments",
    "email",
    "video-approval",
    "status-view",
    # Estimating
    "estimator",
    # Quoting
    "quoting",
    # Admin
    "admin-config",
    "logs",
    # Legacy keys absorbed into admin-config — must still render something (backward compat)
    "users",
    "config",
]

# New keys introduced in F1 that must be present
NEW_TAB_KEYS = ["quoting", "admin-config", "contract-faq", "status-view"]

# Keys that existed in the old ROLE_CONFIG and must not silently vanish
OLD_TAB_KEYS = [
    "dashboard", "search-ask", "opportunities", "articles", "faq",
    "email", "scheduling", "clip-studio", "comments", "video-approval",
    "archive", "estimator", "users", "config", "logs",
]


def read_app() -> str:
    if not APP_TSX.exists():
        print(f"ERROR: {APP_TSX} not found", file=sys.stderr)
        sys.exit(1)
    return APP_TSX.read_text()


def extract_tabcontent_keys(source: str) -> set[str]:
    """Extract tab key strings from the TabContent function.

    Looks for patterns like:
      tab === "some-key"
      tab == "some-key"
    and also:
      case "some-key":   (if a switch is used)
    """
    keys: set[str] = set()
    # Match: tab === "key" or tab == "key"
    for m in re.finditer(r'tab\s*===?\s*["\']([^"\']+)["\']', source):
        keys.add(m.group(1))
    # Match: case "key": or case 'key':
    for m in re.finditer(r'case\s+["\']([^"\']+)["\']', source):
        keys.add(m.group(1))
    return keys


def extract_role_config_keys(source: str) -> set[str]:
    """Extract all tab key strings that appear inside ROLE_CONFIG / ShellConfig structures.

    Looks for array-pair patterns like ["some-key", "Label"] throughout the file.
    """
    keys: set[str] = set()
    for m in re.finditer(r'\[\s*["\']([^"\']+)["\']\s*,\s*["\'][^"\']*["\']\s*\]', source):
        keys.add(m.group(1))
    return keys


def run_checks(source: str) -> list[str]:
    failures: list[str] = []

    tabcontent_keys = extract_tabcontent_keys(source)
    role_config_keys = extract_role_config_keys(source)

    # 1. Every required key must appear in TabContent
    for key in REQUIRED_TAB_KEYS:
        if key not in tabcontent_keys:
            failures.append(
                f"MISSING in TabContent: '{key}' — tab renders nothing for this key"
            )

    # 2. New F1 keys must appear in ROLE_CONFIG
    for key in NEW_TAB_KEYS:
        if key not in role_config_keys:
            failures.append(
                f"MISSING in ROLE_CONFIG: new key '{key}' not wired into any role's tab list"
            )

    # 3. Old keys must not have silently vanished from TabContent
    for key in OLD_TAB_KEYS:
        if key not in tabcontent_keys:
            failures.append(
                f"REGRESSION: old key '{key}' no longer handled in TabContent"
            )

    # 4. status-view must appear (the Marketing section Status entry)
    if "status-view" not in tabcontent_keys:
        failures.append(
            "MISSING: 'status-view' not in TabContent — Marketing > Status won't render"
        )

    return failures


def main() -> int:
    source = read_app()
    failures = run_checks(source)

    if failures:
        print(f"validate_f1_routes FAILED — {len(failures)} issue(s):")
        for f in failures:
            print(f"  ✗ {f}")
        return 1

    print(f"validate_f1_routes PASSED — all {len(REQUIRED_TAB_KEYS)} required keys present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
