"""Adversarial critique loop for generated articles — pure prompt/parse logic, no I/O.

Three critics read the article through deliberately different lenses, then a reviser applies
their findings. Repeat until clean or the round budget runs out.

Why three DIFFERENT lenses rather than three copies of one skeptic: redundant critics find
redundant problems. An SEO critic will never notice that a cost figure was invented, and a
grounding critic will never notice the article is boring. Each lens owns failure modes the
others are structurally blind to.

  SEO       — Rank Math surface: keyword, title, headings, density, links, alts
  GROUNDING — the moat: does every claim trace to Tim's videos? are the ?t= stamps real?
  READER    — is this worth a Florida homeowner's time, in Tim's voice, without filler?

The loop lives here as pure functions so it is testable without an LLM or a database;
jobs/article_job owns the wiring and the model calls.
"""
from __future__ import annotations

# Severity ranking. Only `blocker` and `major` force another revision round — `minor` findings
# are advisory, so a critic that always finds *something* can't spin the loop forever.
BLOCKING = ("blocker", "major")

CRITIQUE_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["blocker", "major", "minor"]},
                    "issue": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["severity", "issue", "fix"],
            },
        },
    },
    "required": ["findings"],
}

_COMMON = (
    "You are reviewing a published-quality article for a South Florida roofing contractor.\n"
    "Be specific and actionable. Do NOT rewrite the article — report findings only.\n"
    "Severity: 'blocker' = must not ship, 'major' = clearly wrong or missing, 'minor' = polish.\n"
    "If the article is genuinely good in your area, return an EMPTY findings list. Do not invent\n"
    "problems to look thorough — a false finding costs a revision round and makes the article\n"
    "worse.\n"
)

CRITICS: dict[str, str] = {
    "seo": _COMMON + (
        "\nYOUR LENS: SEO / Rank Math. Ignore prose quality — that is another reviewer's job.\n"
        "Check ONLY:\n"
        "- Focus keyword present in title, meta description, first paragraph, and ≥1 H2\n"
        "- Keyword density between 0.5% and 1.5% — flag stuffing as well as starvation\n"
        "- Title 30-65 chars, contains a number, and reads like a human wrote it\n"
        "- At least one image alt contains the keyword (only if the article HAS an image)\n"
        "- At least one internal (relative) link and one external link\n"
        "- Scannable structure: question-led H2s, short paragraphs\n"
    ),
    "grounding": _COMMON + (
        "\nYOUR LENS: factual grounding. This is the most important review.\n"
        "This article must be built from Tim's own videos, not from general knowledge.\n"
        "Check ONLY:\n"
        "- Every specific claim (costs, timeframes, materials, code requirements, measurements)\n"
        "  should be traceable to the SOURCE TRANSCRIPT below. Flag invented specifics as\n"
        "  'blocker' — a fabricated price or code reference is the worst failure this can have.\n"
        "- YouTube URLs and ?t= timestamps must be preserved exactly and must be relevant.\n"
        "- Flag anything stated as fact that the transcript does not support, and say what the\n"
        "  article should say instead (hedge it, attribute it, or cut it).\n"
        "- Florida-specific claims (HVHZ, insurance, permitting) get extra scrutiny.\n"
    ),
    "reader": _COMMON + (
        "\nYOUR LENS: the reader. A Florida homeowner with a roof problem is reading this.\n"
        "Ignore SEO mechanics entirely — another reviewer owns those.\n"
        "Check ONLY:\n"
        "- Does it answer the question it promises, early, without preamble?\n"
        "- Filler, hedging, throat-clearing, or the same point made twice in different words\n"
        "- Does it sound like an experienced roofer talking, or like generic AI content?\n"
        "- Is it actionable — can the reader do something after reading it?\n"
        "- Flag any section that could be cut with no loss as 'major'.\n"
    ),
}


def critique_prompt(lens: str, article: dict, transcript: str = "") -> str:
    """Build one critic's prompt. `lens` must be a key of CRITICS."""
    if lens not in CRITICS:
        raise ValueError(f"unknown critic lens {lens!r}; expected one of {sorted(CRITICS)}")
    parts = [
        CRITICS[lens],
        "\nReturn JSON: {\"findings\": [{\"severity\": ..., \"issue\": ..., \"fix\": ...}]}\n",
        f"\nFOCUS KEYWORD: {article.get('focus_keyword', '')}",
        f"\nTITLE: {article.get('title', '')}",
        f"\nMETA: {article.get('meta', '')}",
    ]
    if lens == "grounding" and transcript:
        parts.append(f"\n\nSOURCE TRANSCRIPT (Tim's videos — the ONLY acceptable basis for "
                     f"specific claims):\n{transcript}")
    parts.append(f"\n\nARTICLE:\n{article.get('content_md', '')}")
    return "".join(parts)


def parse_findings(parsed: object) -> list[dict]:
    """Normalise a critic's parsed JSON into a findings list, dropping malformed entries.

    Fail-closed on shape but not on content: an unparseable critic yields no findings rather
    than an exception, so one bad critic can't abort the whole revision.
    """
    if not isinstance(parsed, dict):
        return []
    out = []
    for f in parsed.get("findings") or []:
        if not isinstance(f, dict):
            continue
        sev = str(f.get("severity", "")).lower().strip()
        issue = str(f.get("issue", "")).strip()
        if sev not in ("blocker", "major", "minor") or not issue:
            continue
        out.append({"severity": sev, "issue": issue, "fix": str(f.get("fix", "")).strip()})
    return out


def blocking(findings: list[dict]) -> list[dict]:
    """Findings serious enough to justify another revision round."""
    return [f for f in findings if f.get("severity") in BLOCKING]


def revise_prompt(article: dict, findings: list[dict], word_goal: int) -> str:
    """Build the reviser prompt from the critics' blocking findings."""
    by_sev = sorted(findings, key=lambda f: BLOCKING.index(f["severity"])
                    if f["severity"] in BLOCKING else 9)
    lines = "\n".join(f"- [{f['severity'].upper()}] {f['issue']}\n    FIX: {f['fix']}"
                      for f in by_sev)
    return (
        "You are revising a South Florida roofing article to address reviewer findings.\n\n"
        "RULES:\n"
        f"- The revision must be at least {word_goal} words. Do NOT shorten the article.\n"
        "- Keep every YouTube URL and ?t= timestamp EXACTLY as written — they are citations.\n"
        "- Fix every finding below. If a finding is wrong, keep the original text rather than\n"
        "  damaging the article to satisfy it.\n"
        "- Do not invent facts to satisfy a finding. If a claim cannot be supported, cut or\n"
        "  hedge it instead.\n"
        "- Return the SAME JSON shape you were given: title, slug, metaDescription, content, faq\n\n"
        f"REVIEWER FINDINGS:\n{lines}\n\n"
        f"CURRENT TITLE: {article.get('title', '')}\n"
        f"CURRENT META: {article.get('meta', '')}\n"
        f"CURRENT ARTICLE:\n{article.get('content_md', '')}\n"
        f"CURRENT FAQ: {article.get('faq_json', [])}"
    )
