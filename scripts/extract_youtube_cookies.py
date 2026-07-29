#!/usr/bin/env python3
"""Extract a MINIMAL YouTube cookie jar from a browser profile, for archive_job.

Why this exists: YouTube bot-blocks datacenter egress, so jobs/archive_job.py cannot download
from Cloud Run without an authenticated cookie jar ("Sign in to confirm you're not a bot").
`--cookies-from-browser` needs a browser profile, which a container does not have, so the jar
has to be a file mounted from Secret Manager.

Why it is not a one-liner: `yt-dlp --cookies-from-browser X --cookies out.txt` writes the
ENTIRE browser cookie database. Run against a daily-driver profile that was 1803 cookies
across 439 domains — including 1password.com. Nobody should be hand-rolling that filter at the
moment they are about to paste the result into a secret.

⚠️ Even filtered, the result IS a full Google session: SID/SAPISID are scoped to .google.com,
so the same jar authenticates Gmail, Drive and Cloud Console. Extract ONLY from a profile
signed in as the channel-owning account, never a personal one. This script prints the account
it found so you can check before storing.

Usage:
    .venv/bin/python scripts/extract_youtube_cookies.py --browser "chrome:Profile 1" -o jar.txt
    gcloud secrets versions add youtube-cookies --data-file=jar.txt
    shred -u jar.txt
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Only these domains. Everything else in the browser's jar is dropped.
KEEP = re.compile(r"(^|\.)(youtube\.com|youtu\.be|googlevideo\.com|ytimg\.com|google\.com)$")

# Without at least one of these the jar is anonymous and will not clear the bot check.
AUTH_COOKIES = ("SID", "SAPISID", "__Secure-1PSID")

PROBE_VIDEO = "https://www.youtube.com/watch?v=eOumjl2jZ-8"


def extract_raw(browser: str, dst: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--cookies-from-browser", browser,
         "--cookies", str(dst), "--skip-download", "--no-warnings", PROBE_VIDEO],
        check=True, capture_output=True, timeout=300,
    )


def filter_jar(src: Path, dst: Path) -> tuple[int, int, set[str]]:
    kept, dropped, domains = [], 0, set()
    for line in src.read_text(errors="replace").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        domain = line.split("\t")[0].lstrip(".")
        if KEEP.search(domain):
            kept.append(line)
            domains.add(domain)
        else:
            dropped += 1
    dst.write_text("# Netscape HTTP Cookie File\n" + "\n".join(kept) + "\n")
    dst.chmod(0o600)
    return len(kept), dropped, domains


def account_for(jar: Path) -> str | None:
    """Ask YouTube who this jar authenticates. None if it is anonymous."""
    out = subprocess.run(
        ["curl", "-s", "-b", str(jar), "-A", "Mozilla/5.0",
         "https://www.youtube.com/account"],
        capture_output=True, timeout=90,
    ).stdout.decode("utf-8", "replace")
    hits = set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}", out))
    return sorted(hits)[0] if hits else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", required=True,
                    help='yt-dlp browser spec, e.g. "chrome:Profile 1"')
    ap.add_argument("-o", "--out", required=True, help="destination for the filtered jar")
    args = ap.parse_args()

    out = Path(args.out)
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.txt"
        extract_raw(args.browser, raw)
        raw_n = sum(1 for ln in raw.read_text(errors="replace").splitlines()
                    if ln.strip() and not ln.startswith("#"))
        kept, dropped, domains = filter_jar(raw, out)

    text = out.read_text()
    present = [c for c in AUTH_COOKIES if re.search(rf"\t{c}\t", text)]

    print(f"raw jar      : {raw_n} cookies")
    print(f"kept         : {kept} across {len(domains)} domains")
    print(f"dropped      : {dropped}")
    print(f"auth cookies : {', '.join(present) if present else 'NONE'}")
    print(f"account      : {account_for(out) or 'NOT SIGNED IN'}")
    print(f"written      : {out} (mode 600)")

    if not present:
        print("\nFAIL: no session cookie — this jar is anonymous and will not clear the bot "
              "check. Load youtube.com in that profile and confirm the avatar shows the "
              "channel account.", file=sys.stderr)
        return 1
    print("\nCheck the account above IS the channel owner before storing. Then:\n"
          f"  gcloud secrets versions add youtube-cookies --data-file={out}\n"
          f"  shred -u {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
