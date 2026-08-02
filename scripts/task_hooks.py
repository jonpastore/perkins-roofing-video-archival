#!/usr/bin/env python3
"""Close and update Jarvis tasks from commit messages — R6.3, mechanised.

WHY. R6.3 has required "update tasks via the jarvis-memory MCP on every commit" since 2026-07-18.
On 2026-08-02 a backlog sweep found SIX tasks describing work that had already shipped — #430,
#449, #418, #385/#386, and #409/#410, the last two fixed by a single commit (`4fd78f7`) whose
subject names both task numbers and closed neither. The rule was right and unenforced, and an
unenforced rule is a suggestion. This turns it into a hook.

WHAT THIS CAN AND CANNOT VERIFY — stated plainly, because the alternative is a green check that
means nothing. A hook cannot read a task's acceptance criteria: they are prose in the task body
("95% out-of-sample with rule selection nested inside the CV"). No parser settles that. So:

  * It CAN require that a commit claiming to close a task states what it verified (`Verified:`),
    and refuse the commit otherwise. Evidence becomes mandatory, not optional.
  * It CAN run the CHEAP gates (ruff, and the tests that cover the changed modules) and refuse to
    CLOSE on a red one — downgrading to 90% "awaiting verification" instead. A commit that does
    not pass its own lint has not finished anything.
  * It CANNOT run the 40-60 minute coverage gate: R7 forbids touching the tree while it runs, and
    a commit hook that takes an hour will be bypassed within a day. CI remains the real gate; this
    records which gate was claimed and by which commit.

TRAILERS the commit message may carry:

    Closes #453                 close the task (subject to the gates above)
    Refs #429 60%               progress only, never closes
    No-Task: <reason>           an explicit opt-out, so "I forgot" and "not task work" differ

Offline and misconfiguration are non-fatal by design: a failed sync prints and moves on. Losing a
commit because a task tracker is unreachable would be a worse failure than the one being fixed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

CLOSES = re.compile(r"^\s*(?:closes|fixes|resolves)\s+#(\d+)\s*$", re.I | re.M)
REFS = re.compile(r"^\s*refs\s+#(\d+)(?:\s+(\d{1,3})\s*%?)?\s*$", re.I | re.M)
NO_TASK = re.compile(r"^\s*no-task:\s*\S+", re.I | re.M)
VERIFIED = re.compile(r"^\s*verified:\s*(\S.*)$", re.I | re.M)


def parse(msg: str) -> dict:
    """Task intents in a commit message. Pure — this is the part worth testing."""
    body = "\n".join(ln for ln in msg.splitlines() if not ln.lstrip().startswith("#"))
    return {
        "closes": [int(n) for n in CLOSES.findall(body)],
        "refs": [(int(n), int(p) if p else None) for n, p in REFS.findall(body)],
        "no_task": bool(NO_TASK.search(body)),
        "verified": (VERIFIED.search(body).group(1).strip() if VERIFIED.search(body) else None),
    }


def _api():
    """(base_url, token) from the environment, else the jarvis-memory MCP's own config."""
    url, tok = os.environ.get("MEMORY_API_URL"), os.environ.get("MEMORY_API_TOKEN")
    if url and tok:
        return url.rstrip("/"), tok
    try:
        cfg = json.loads((Path.home() / ".claude.json").read_text())
        for server in _walk_mcp(cfg):
            env = server.get("env") or {}
            if env.get("MEMORY_API_URL") and env.get("MEMORY_API_TOKEN"):
                return env["MEMORY_API_URL"].rstrip("/"), env["MEMORY_API_TOKEN"]
    except Exception:  # noqa: BLE001 — never break a commit over config discovery
        pass
    return None, None


def _walk_mcp(node):
    """Yield every mcpServers entry, wherever it is nested."""
    if isinstance(node, dict):
        for key, val in node.items():
            if key == "mcpServers" and isinstance(val, dict):
                yield from (v for v in val.values() if isinstance(v, dict))
            else:
                yield from _walk_mcp(val)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_mcp(item)


def _post(path: str, body: dict) -> dict | None:
    base, tok = _api()
    if not base:
        print("task-hook: no MEMORY_API_URL/TOKEN — skipping Jarvis sync", file=sys.stderr)
        return None
    req = urllib.request.Request(
        f"{base}{path}", data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"task-hook: Jarvis unreachable ({exc}) — task NOT updated", file=sys.stderr)
        return None


def changed_files(sha: str = "HEAD") -> list[str]:
    out = subprocess.run(["git", "show", "--name-only", "--pretty=format:", sha],
                         capture_output=True, text=True, timeout=20)
    return [f for f in out.stdout.split("\n") if f.strip()]


#: The tree CI lints (`ruff check core adapters api jobs` in .github/workflows/ci.yml). The hook
#: MUST mirror it. Linting more than CI does means a commit that CI would pass gets its task held
#: at 90%, and a gate that fires on work the repo does not gate is noise — which is how a hook
#: gets ignored, and an ignored hook is the rule it replaced. Found by using it: the #436 commit
#: touched scripts/, which carries pre-existing lint debt CI has never enforced.
_LINTED_ROOTS = ("core/", "adapters/", "api/", "jobs/")


def cheap_gates(files: list[str]) -> tuple[bool, str]:
    """Lint the changed Python that CI lints. Fast (~1s), and a genuine signal.

    Deliberately NOT the coverage gate — R7. CI runs that on every push and is the real verdict.
    """
    py = [f for f in files
          if f.endswith(".py") and f.startswith(_LINTED_ROOTS) and Path(f).exists()]
    if not py:
        return True, "no CI-linted python changed"
    ruff = Path(".venv/bin/ruff")
    if not ruff.exists():
        return True, "ruff not installed — skipped"
    out = subprocess.run([str(ruff), "check", *py], capture_output=True, text=True, timeout=120)
    if out.returncode == 0:
        return True, f"ruff clean on {len(py)} file(s)"
    return False, out.stdout.strip().splitlines()[-1] if out.stdout else "ruff failed"


def apply(intents: dict, sha: str, subject: str) -> None:
    """Push the intents to Jarvis. Never raises — a sync failure must not lose a commit."""
    ok, why = cheap_gates(changed_files(sha))
    for tid in intents["closes"]:
        if ok:
            r = _post(f"/task/{tid}/done", {})
            if r:
                print(f"task-hook: closed #{tid} ({why}) — {sha[:8]} {subject[:60]}")
        else:
            # A red gate is not a reason to lose the link between commit and task; it is a reason
            # not to call it finished.
            _post(f"/task/{tid}/pct", {"pct": 90})
            print(f"task-hook: #{tid} left OPEN at 90% — gate failed: {why}", file=sys.stderr)
    for tid, pct in intents["refs"]:
        if pct is not None:
            r = _post(f"/task/{tid}/pct", {"pct": max(0, min(100, pct))})
            if r:
                print(f"task-hook: #{tid} -> {pct}%")


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        # commit-msg hook: validate the message, block a bad one.
        msg = Path(sys.argv[2]).read_text()
        subject = next((ln for ln in msg.splitlines() if ln.strip()
                        and not ln.lstrip().startswith("#")), "")
        # Git generates these itself and there is no task to name: a merge restates the branch's
        # trailers, a revert restates the original's, and a fixup is folded before it lands.
        # Blocking them would make `git merge` fail for a rule about authored work.
        if (subject.startswith(("Merge ", "Revert ", "fixup!", "squash!", "amend!"))
                or Path(".git/MERGE_HEAD").exists()):
            return 0
        intents = parse(msg)
        if not (intents["closes"] or intents["refs"] or intents["no_task"]):
            print(
                "\nR6.3: this commit references no task.\n"
                "  Add ONE of:\n"
                "    Closes #<id>          finished it\n"
                "    Refs #<id> 60%        progress\n"
                "    No-Task: <reason>     deliberately not task work\n"
                "\nSix tasks describing already-shipped work were found on 2026-08-02 because this\n"
                "was left to memory. Say which task, or say there isn't one.\n", file=sys.stderr)
            return 1
        if intents["closes"] and not intents["verified"]:
            ids = ", ".join(f"#{i}" for i in intents["closes"])
            print(
                f"\nClosing {ids} requires a `Verified:` line stating what you actually ran.\n"
                "  e.g. Verified: pytest tests/api/test_estimator_f2.py -k Split (19 passed), "
                "ruff clean\n"
                "\nA hook cannot read a task's acceptance criteria — they are prose. It can insist\n"
                "the evidence is written down next to the claim.\n", file=sys.stderr)
            return 1
        return 0

    # post-commit hook: apply intents for the commit just made.
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    msg = subprocess.run(["git", "log", "-1", "--pretty=%B"], capture_output=True, text=True).stdout
    subject = msg.splitlines()[0] if msg.strip() else ""
    if subject.startswith("Merge "):
        return 0          # a merge re-states the branch's trailers; do not re-close
    try:
        apply(parse(msg), sha, subject)
    except Exception as exc:  # noqa: BLE001
        print(f"task-hook: sync failed ({exc}) — commit kept", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
