#!/usr/bin/env python3
"""Render docs/PRICING_RULES.md to a PDF Tim can read without a git account.

The markdown file is the source of truth and stays reviewable in the repo; this only produces the
copy that goes out as an email attachment. Styled to match the proposal PDFs — Perkins navy
(#2A3C73) and light blue (#41B1E5), not the DeGenito red.

Usage: PYTHONPATH=. .venv/bin/python scripts/render_pricing_rules_pdf.py
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs/PRICING_RULES.md"
OUT = Path.home() / "perkins-corpus/worked-examples/Perkins-pricing-rules-2026-07-27.pdf"

CSS = """
@page { size: Letter; margin: 14mm 15mm 16mm; }
body { font-family: Aptos, Calibri, Helvetica, Arial, sans-serif; font-size: 10pt;
       line-height: 1.45; color: #1a1a1a; }
h1 { font-size: 21pt; color: #2A3C73; margin: 0 0 4pt; border-bottom: 3px solid #41B1E5;
     padding-bottom: 6pt; }
h2 { font-size: 14pt; color: #2A3C73; margin: 20pt 0 6pt; padding-top: 4pt;
     border-top: 1px solid #d8dde8; page-break-after: avoid; }
h3 { font-size: 11.5pt; color: #2A3C73; margin: 13pt 0 4pt; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 9pt;
        page-break-inside: avoid; }
th { background: #2A3C73; color: #fff; text-align: left; padding: 4pt 6pt; font-weight: 600; }
td { border-bottom: 1px solid #e3e7ef; padding: 3.5pt 6pt; vertical-align: top; }
tr:nth-child(even) td { background: #f7f9fc; }
blockquote { margin: 8pt 0 8pt 4pt; padding: 6pt 10pt; border-left: 3px solid #41B1E5;
             background: #f4f9fd; font-style: italic; page-break-inside: avoid; }
pre { background: #f5f6f8; border: 1px solid #e0e4ea; border-radius: 3px; padding: 7pt 9pt;
      font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: 8.5pt; line-height: 1.4;
      white-space: pre-wrap; page-break-inside: avoid; }
code { font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: 8.5pt;
       background: #f0f2f5; padding: 0 2px; border-radius: 2px; }
pre code { background: none; padding: 0; }
strong { color: #16233f; }
hr { border: 0; border-top: 1px solid #d8dde8; margin: 14pt 0; }
ul, ol { margin: 5pt 0 5pt 16pt; padding: 0; }
li { margin: 2pt 0; }
a { color: #2A3C73; }
"""


def main() -> None:
    html = markdown.markdown(SRC.read_text(), extensions=["tables", "fenced_code", "sane_lists"])
    doc = (f"<!doctype html><html><head><meta charset='utf-8'>"
           f"<title>Perkins Roofing — how a price is built</title>"
           f"<style>{CSS}</style></head><body>{html}</body></html>")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "rules.html"
        src.write_text(doc)
        # --print-to-pdf writes relative to cwd on some builds; pass an absolute path.
        subprocess.run(
            ["google-chrome", "--headless", "--disable-gpu", "--no-sandbox",
             "--no-pdf-header-footer", f"--print-to-pdf={OUT}", src.as_uri()],
            check=True, capture_output=True, timeout=180)
    if not OUT.exists() or OUT.stat().st_size < 10_000:
        raise SystemExit(f"render produced nothing usable at {OUT}")
    print(f"{OUT}  ({OUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
