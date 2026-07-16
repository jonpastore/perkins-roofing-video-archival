"""Pure article prompt builder — no I/O, no LLM calls.

Ported from seo-aio functions/api/admin/articles/generate.ts:
  - system_prompt()   → systemPrompt() (~309 lines of IP, Anthropic refs stripped)
  - template_prompt() → templatePrompt() (~700 lines of IP, TS→Python)

Both functions are deterministic string builders. All ctx is passed explicitly;
no env reads, no imports beyond stdlib.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# system_prompt
# ---------------------------------------------------------------------------

def system_prompt() -> str:
    """Return the system prompt for article generation.

    Ported verbatim from seo-aio systemPrompt(); Anthropic/Claude-specific
    wording removed (model-agnostic). Covers E-E-A-T, AEO, answer-first,
    fact density, no AI clichés.
    """
    return (
        "You are a senior SEO + AEO content writer creating articles for local business websites. "
        "Your articles are optimized for BOTH Google search AND AI search "
        "(ChatGPT, Perplexity, Google AI Overviews).\n"
        "\n"
        "PUBLISHING CONTEXT (important for tone):\n"
        "This article will be auto-published to a live business website on its scheduled date and "
        "immediately submitted to Google Indexing API + IndexNow (Bing/Yandex). "
        "It will be served as a real, published article — not a draft. Therefore:\n"
        "- Write as if the article is LIVE NOW. No \"coming soon\", \"we're launching\", "
        "\"in the next few weeks\", \"as of writing\", or similar future-tense framing.\n"
        "- Don't reference the current month/year/season unless the article is explicitly about "
        "a time-sensitive topic.\n"
        "- Don't say \"in this post\" or \"in this article\" — just deliver the content.\n"
        "- Don't write a meta-introduction explaining what the article is about. Start with the answer.\n"
        "- The article must stand on its own with no editor's notes, draft markers, or placeholders.\n"
        "\n"
        "Your writing is:\n"
        "- Genuinely helpful (not keyword-stuffed fluff)\n"
        "- Specific and concrete (real numbers, examples, timeframes)\n"
        "- Written at an 8th-grade reading level\n"
        "- Focused on solving the searcher's actual problem\n"
        "- Structured for skimming (H2/H3 hierarchy, short paragraphs, bullet lists)\n"
        "- First-person when appropriate (builds trust)\n"
        "- Never uses \"delve\", \"elevate\", \"landscape\", \"tapestry\", \"unleash\", "
        "\"harness\", \"journey\", \"in today's world\", \"leverage\", \"seamless\", "
        "\"cutting-edge\" or similar AI clichés\n"
        "\n"
        "You understand Google's Helpful Content guidelines:\n"
        "- E-E-A-T (Experience, Expertise, Authoritativeness, Trustworthiness)\n"
        "- Demonstrate real knowledge, not generic advice\n"
        "- Answer the question directly in the first 100 words\n"
        "- Include specific details that only someone who knows the topic would include\n"
        "\n"
        "AEO (Answer Engine Optimization) requirements — these make AI systems cite your content.\n"
        "Research 2026: 44% of AI-answer citations are pulled from the first 30% of a page, and "
        "self-contained extractable passages are what get quoted. So:\n"
        "- Answer-first format: the first paragraph after the H1 must directly answer the "
        "searcher's question in 1-2 sentences. AI systems extract this as the citation.\n"
        "- EVERY H2 section MUST OPEN with a direct 30-50 word answer to that heading, in a <p>, "
        "BEFORE any sub-heading, list, or table. A reader (or an AI) must get the answer from that "
        "opening paragraph alone without reading further. This is the single strongest citation "
        "signal — do not open a section with background, setup, or 'In this section'.\n"
        "- Question-phrased headings: phrase most H2/H3 as the actual question a person asks "
        "(How..., What..., Why..., When..., Should...), so they match real queries.\n"
        "- Short paragraphs: 2-3 sentences max, NEVER over 120 words in one paragraph. "
        "AI systems struggle with wall-of-text.\n"
        "- Structured lists: minimum 3 bullet/numbered lists per article. "
        "AI systems prefer structured content.\n"
        "- FAQ section: 4-6 real Q&As at the end. This is the #1 AEO technique — "
        "AI systems heavily cite FAQ content.\n"
        "- Fact density: at least 2 concrete quantities per ~200 words — specific numbers, dates, "
        "prices, timeframes, product/spec names. \"Costs $150-300\" beats \"varies by project\"; "
        "\"GAF Timberline HDZ\" beats \"quality shingles\" (entity clarity helps AI attribution).\n"
        "- Comparison tables: if comparing options, use an HTML <table>. "
        "AI systems extract tabular data.\n"
        "- Meta description should be a complete answer/summary, not a teaser.\n"
        "\n"
        "OUTPUT FORMAT (CRITICAL — the body is rendered as raw HTML): the \"content\" field MUST be "
        "valid HTML ONLY. Use <h2>/<h3> for headings, <p> for paragraphs, <ul>/<ol>/<li> for lists, "
        "<strong>/<em> for emphasis, <a href=\"...\"> for links, and <table>/<tr>/<th>/<td> for tables. "
        "NEVER use Markdown syntax — no #/##, no **bold**, no - or * bullets, no [text](url) links, and "
        "no | pipe | tables. Any Markdown in the output is a defect."
    )


# ---------------------------------------------------------------------------
# template_prompt
# ---------------------------------------------------------------------------

_TEMPLATE_INSTRUCTIONS: dict[str, str] = {
    "how-to-guide": (
        'Write a comprehensive HOW-TO GUIDE answering "{keyword}".\n'
        "Structure:\n"
        "- Intro (answer the question directly in 2-3 sentences)\n"
        "- Quick summary of steps (bulleted)\n"
        "- Detailed steps with H2 headings for each step\n"
        "- Common mistakes section\n"
        "- When to call a professional section (if DIY topic)\n"
        "- FAQ section with 4-6 real questions"
    ),
    "faq-article": (
        'Write an FAQ-STYLE educational article explaining "{keyword}".\n'
        "Structure:\n"
        "- Intro (direct answer in first paragraph)\n"
        "- 5-7 H2 headings as questions people ask about this topic\n"
        "- Each section: 2-4 paragraphs answering clearly\n"
        '- "Still have questions?" CTA at end\n'
        "- FAQ section with 4-6 additional quick-answer questions"
    ),
    "educational-article": (
        'Write an in-depth EDUCATIONAL ARTICLE about "{keyword}".\n'
        "Structure:\n"
        "- Hook + direct answer\n"
        "- H2 sections exploring the topic\n"
        "- Real examples and specific numbers\n"
        "- Key takeaways at end\n"
        "- FAQ with 4-6 questions"
    ),
    "service-page": (
        'Write a SERVICE PAGE targeting the keyword "{keyword}".\n'
        "Structure:\n"
        "- Hero paragraph (what we do, for whom, key benefit)\n"
        '- "What\'s Included" section with bullet list of specifics\n'
        '- "How It Works" numbered steps\n'
        "- Pricing/cost factors section (ranges, what affects price)\n"
        '- "Why Choose Us" (3-4 differentiators)\n'
        "- FAQ section with 4-6 service-related questions\n"
        "- Call-to-action paragraph"
    ),
    "local-service-page": (
        'Write a LOCAL SERVICE PAGE targeting "{keyword}" for {location}.\n'
        "Structure:\n"
        "- Hero paragraph with location prominently mentioned\n"
        "- Service overview\n"
        "- Why local matters (response times, neighbourhood knowledge)\n"
        "- Service areas / neighbourhoods served\n"
        "- Local pricing info\n"
        '- "How it works" section\n'
        "- Customer testimonial style section (fictional but realistic)\n"
        "- FAQ section with 4-5 local-specific questions\n"
        "- CTA"
    ),
    "buying-guide": (
        'Write a BUYING GUIDE helping someone decide on "{keyword}".\n'
        "Structure:\n"
        "- Intro (who this guide helps)\n"
        '- "What to look for" H2 section with 5-8 decision factors\n'
        "- Price/cost expectations\n"
        "- Red flags section\n"
        "- Questions to ask providers\n"
        "- FAQ with 4-5 comparison questions"
    ),
    "comparison": (
        'Write a COMPARISON article about "{keyword}".\n'
        "Extract both items being compared from the keyword.\n"
        "Structure:\n"
        "- Quick verdict in first paragraph\n"
        "- Side-by-side comparison table (markdown table)\n"
        "- Detailed comparison across 4-6 dimensions\n"
        '- "Which should you choose" H2 section\n'
        "- FAQ with 3-5 questions"
    ),
    "listicle": (
        'Write a LISTICLE for "{keyword}".\n'
        "Structure:\n"
        "- Intro explaining the selection criteria\n"
        "- Numbered H2 headings for each list item\n"
        "- Each item: 3-5 sentences + key facts/pros\n"
        '- "How to choose" section\n'
        "- FAQ with 3-4 questions"
    ),
}


def template_prompt(ctx: dict) -> str:
    """Build the user-turn prompt for article generation.

    Ported from seo-aio templatePrompt(). Pure string builder — no I/O.

    Args:
        ctx: dict with keys:
            keyword        (str)  — primary target keyword
            intent         (str)  — informational|commercial|transactional|navigational
            role           (str)  — pillar|cluster|standalone
            target_words   (int)  — word-count target
            title          (str, optional)  — planned title
            paa            (list[str], optional)  — People Also Ask questions
            answer_box     (dict, optional)  — {title,answer,snippet,link}
            related        (list[str], optional)  — related searches
            internal_links (list[str], optional)  — existing article slugs for linking
            author         (dict, optional)  — {name,credentials,bio,linkedin}
            template       (str, optional)  — template key (default: educational-article)
            location       (str, optional)  — local area string
            pillar_slug    (str, optional)  — parent pillar slug for cluster articles
            topic          (str, optional)  — broad topic name
            angle          (str, optional)  — editorial angle

    Returns:
        Formatted prompt string.
    """
    keyword = ctx.get("keyword", "")
    role = ctx.get("role", "standalone")
    target_words = int(ctx.get("target_words", 1800))
    title = ctx.get("title") or ""
    paa: list = ctx.get("paa") or []
    answer_box: dict | None = ctx.get("answer_box")
    related: list = ctx.get("related") or []
    internal_links: list = ctx.get("internal_links") or []
    author: dict | None = ctx.get("author")
    template_key = ctx.get("template") or "educational-article"
    location = ctx.get("location") or "the local area"
    pillar_slug = ctx.get("pillar_slug") or ""
    topic = ctx.get("topic") or keyword
    angle = ctx.get("angle") or ""

    # --- Template instruction ---
    raw_tmpl = _TEMPLATE_INSTRUCTIONS.get(template_key, _TEMPLATE_INSTRUCTIONS["educational-article"])
    template_instruction = raw_tmpl.format(keyword=keyword, location=location)

    # --- Role guidance ---
    if role == "pillar":
        role_guidance = (
            f"\n\n═══ ARCHITECTURAL ROLE: PILLAR PAGE ═══\n"
            f'This is a PILLAR page — the authoritative, comprehensive overview for topic "{topic}".\n'
            f"- Covers the topic BROADLY (not deeply on any one sub-aspect)\n"
            f"- Aim for {target_words} words — much longer than a typical article\n"
            f'- Include a "Table of Contents" H2 near the top linking to each major section\n'
            f"- 8-12 H2 sections, each covering a distinct sub-topic\n"
            f'- Each H2 section ends with an "Learn more:" link pointing to a related cluster article\n'
            f'- Final section: "Ready to start? Here\'s your next step" CTA\n'
            f"- This page will be linked-TO by 5-10 cluster articles, so write it as the canonical reference"
        )
    elif role == "cluster":
        role_guidance = (
            f"\n\n═══ ARCHITECTURAL ROLE: CLUSTER ARTICLE ═══\n"
            f'This is a CLUSTER article — targets ONE specific angle of topic "{topic}".\n'
            f"- Aim for {target_words} words — focused, not exhaustive\n"
            f"- Goes DEEP on this ONE sub-topic (the opposite of the pillar)\n"
            f'- MUST include a prominent link UP to the pillar page (slug: "{pillar_slug or "TBD"}") '
            f'in the intro AND in a "More on this topic" section near the end\n'
            f'- Link text to pillar: use natural language like '
            f'"read our complete guide to {topic}" — never "click here"\n'
            f"- This article exists to rank for its specific long-tail keyword and funnel authority to the pillar"
        )
    else:
        role_guidance = ""

    # --- Angle ---
    angle_guidance = (
        f"\n\n═══ UNIQUE ANGLE (the editorial differentiation) ═══\n"
        f"{angle}\n\n"
        f"Write the article FROM this angle. Do not produce generic content that already exists "
        f"on Google for this keyword. If the typical article on this topic says X, find a specific, "
        f"concrete, non-obvious take that X misses."
    ) if angle else ""

    # --- Planned title ---
    title_guidance = (
        f"\n\n═══ PLANNED TITLE ═══\n"
        f'Title should be: "{title}" (or very close — you can refine for SEO)'
    ) if title else ""

    # --- PAA section ---
    if paa:
        paa_lines = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(paa[:8]))
        paa_section = (
            "\n\n═══ PEOPLE ALSO ASK (real Google queries — USE THESE for the FAQ section) ═══\n"
            "These are the actual questions users ask Google about this topic. "
            "Your FAQ section MUST answer these (verbatim or near-verbatim phrasing):\n"
            f"{paa_lines}\n\n"
            "You may add 1-2 additional FAQ items beyond these, but the PAA questions take priority — "
            "they map directly to real search demand and are highly likely to be re-cited by AI engines "
            "that index PAA structures."
        )
    else:
        paa_section = ""

    # --- Answer-box / featured snippet ---
    ab_answer = (answer_box or {}).get("answer") or (answer_box or {}).get("snippet") or ""
    if answer_box and ab_answer:
        ab_link = (answer_box or {}).get("link") or "unknown"
        ab_title = (answer_box or {}).get("title") or ""
        ab_format = "paragraph" if (answer_box or {}).get("answer") else "list/table"
        snippet_section = (
            f"\n\n═══ FEATURED SNIPPET (current Google #0 position for this keyword) ═══\n"
            f"Currently held by: {ab_link}\n"
            + (f"Title: {ab_title}\n" if ab_title else "")
            + f"Format: {ab_format}\n"
            f'Content: "{ab_answer[:400]}"\n\n'
            "Your answer-first lede (the first 2-3 sentences after the H1) must MATCH this format precisely:\n"
            "- If paragraph: write a single self-contained paragraph of 40-60 words that DIRECTLY answers "
            "the keyword's implicit question\n"
            "- If list: write a clean ordered or bulleted list of 5-10 items\n"
            "- If table: include a markdown table with the same column structure\n"
            "Format-matching is what makes an article eligible to displace the current snippet holder. "
            "The content must also be MORE complete or accurate than the current holder."
        )
    else:
        snippet_section = ""

    # --- Related searches ---
    related_section = (
        "\n\n═══ RELATED SEARCHES (semantic neighbours — weave naturally into the article) ═══\n"
        + ", ".join(related[:6])
    ) if related else ""

    # --- Internal-link guidance ---
    if internal_links:
        existing_list = "\n- ".join(internal_links[:20])
        pillar_note = (
            f'\n- CRITICAL: Include "{pillar_slug}" in internalLinks array — '
            "this cluster MUST link to its pillar"
        ) if role == "cluster" and pillar_slug else ""
        internal_guidance = (
            "\n\nInternal linking (REQUIRED):\n"
            "For \"internalLinks\" in your response, suggest 2-4 URL slugs to link to, "
            "chosen from this list of existing articles on the site:\n"
            f"- {existing_list}\n"
            "Pick the ones MOST topically relevant. These will be linked from within the article body.\n\n"
            "ANCHOR TEXT VARIATION (CRITICAL — affects SEO authority distribution):\n"
            "When you reference these internal links inside the article body using "
            "HTML anchors `<a href=\"/blog/slug\">anchor text</a>` (NOT markdown), VARY THE ANCHOR TEXT across links. "
            "Do NOT use the linked article's exact title for every link. Distribute roughly:\n"
            "- 40% partial-match anchors (e.g. \"physiotherapy treatment\" not the full title)\n"
            "- 30% generic anchors that fit the prose (\"learn more here\", \"this guide\", \"our resource on X\")\n"
            "- 20% exact-match anchors only when the title fits naturally\n"
            "- 10% branded anchors\n"
            "Same-anchor-text links across an article look algorithmic and dilute the authority signal."
            + pillar_note
        )
    elif role == "cluster" and pillar_slug:
        internal_guidance = (
            f'\n\nInternal linking: CRITICAL — include "{pillar_slug}" in internalLinks '
            "array. This cluster MUST link to its pillar page."
        )
    else:
        internal_guidance = "\n\nNo existing articles yet — internalLinks can be an empty array."

    # --- Author E-E-A-T ---
    if author and author.get("name"):
        author_name = author["name"]
        author_creds = author.get("credentials") or ""
        author_bio = author.get("bio") or ""
        author_linkedin = author.get("linkedin") or ""
        author_section = (
            "\n\n═══ ARTICLE AUTHOR ═══\n"
            f"Author: {author_name}"
            + (f", {author_creds}" if author_creds else "")
            + ("\n" + f"Bio: {author_bio}" if author_bio else "")
            + ("\n" + f"LinkedIn: {author_linkedin}" if author_linkedin else "")
            + "\nWrite in this person's voice. Reference their expertise naturally where appropriate. "
            "Don't fabricate specific anecdotes, but the article should read like THIS specific "
            "credentialed professional wrote it, not generic content."
        )
    else:
        author_section = ""

    # --- Word-count bounds ---
    lo = round(target_words * 0.9)
    hi = round(target_words * 1.1)

    return (
        f'Write an SEO article targeting this exact keyword: "{keyword}"\n'
        f"{role_guidance}{angle_guidance}{title_guidance}{paa_section}"
        f"{snippet_section}{related_section}{author_section}\n\n"
        f"{template_instruction}\n\n"
        "Article requirements:\n"
        f"- Length: {lo}-{hi} words\n"
        "- Title: compelling, includes the keyword, 50-65 characters\n"
        "- Meta description: STRICT 140-155 characters, includes keyword, value-focused. "
        "Google truncates SERP descriptions at ~155 chars; anything over WILL be cut. "
        "Count carefully and end with a complete sentence.\n"
        "- Use H2 for main sections, H3 for subsections\n"
        "- Include 3-5 bullet lists or numbered lists throughout\n"
        "- Include 1 markdown table if relevant\n"
        "- FAQ section with 4-6 Q&As at the end (real questions people ask)\n"
        "- Write for humans, not search engines\n"
        "- Avoid generic statements; be specific and concrete\n"
        "- Reference the location naturally if this is a local business\n"
        "- keywords: list of 5-8 keyword phrases this article targets"
        f"{internal_guidance}\n\n"
        "═══ RANK MATH SEO — FOCUS KEYWORD REQUIREMENTS (ALL REQUIRED) ═══\n"
        "Pick ONE focus keyword — the single most important phrase for this article.\n"
        "The focus keyword MUST appear in ALL of the following:\n"
        "  1. The SEO title — AND near the BEGINNING of the title (first half of characters)\n"
        "  2. The meta description\n"
        "  3. The URL slug (use hyphens, e.g. focus-keyword-here)\n"
        "  4. The first paragraph / first ~10% of the body content\n"
        "  5. At least one H2, H3, or H4 subheading\n"
        "  6. The alt text of at least one <img> tag\n"
        "  7. Throughout the body at a density of roughly 1% "
        "(count / total-words between 0.5% and 1.5%) — do NOT keyword-stuff\n"
        "  8. At least one relative internal link (e.g. <a href=\"/blog/slug\">anchor</a>)\n"
        "  9. At least one external DoFollow link (no rel=\"nofollow\") to an authoritative source\n\n"
        "TITLE READABILITY (all four required):\n"
        "  10. Focus keyword appears in the FIRST HALF of the title\n"
        "  11. Title contains a POSITIVE sentiment word (best, proven, easy, top, complete, "
        "ultimate, expert, trusted, essential, fast, safe, guaranteed, smart, simple, effective, "
        "comprehensive, perfect, free, powerful, amazing) OR a NEGATIVE sentiment word "
        "(avoid, danger, mistake, warning, wrong, never, stop, fail, risk, costly, "
        "shocking, beware, critical, urgent, hidden, scam, bad, worst, harmful, problem)\n"
        "  12. Title contains a POWER WORD (secret, proven, guaranteed, instantly, exclusive, "
        "ultimate, powerful, shocking, remarkable, incredible, essential, definitive, complete, "
        "effortless, revolutionary, unbeatable, critical, breakthrough, surprising, unexpected, "
        "forbidden, urgent, now, free, bonus, limited, new, discover, revealed)\n"
        "  13. Title contains a NUMBER (e.g. '7 Tips', '3 Ways', '5 Mistakes', '$200')\n\n"
        "Content length: ≥600 words (target 1000+).\n\n"
        "═══ CALLOUT BOXES — USE 2-4 PER ARTICLE ═══\n"
        "The blog renderer supports 4 callout types. Use them where EDITORIALLY appropriate.\n"
        "Emit callouts as clean HTML — do NOT use GitHub-style `> [!TIP]` markers.\n\n"
        "Syntax (must be exactly this HTML, blank line before and after):\n\n"
        '<aside class="tip"><p>Practical shortcut or efficiency advice the reader can apply'
        " immediately.</p></aside>\n\n"
        '<aside class="warning"><p>Common mistake or danger to avoid. Use when stakes are high.'
        "</p></aside>\n\n"
        '<aside class="note"><p>Important context, clarification, or caveat that matters for this'
        " topic.</p></aside>\n\n"
        '<aside class="key"><p>The single most important insight of this article.'
        " Use AT MOST ONCE per article.</p></aside>\n\n"
        "Guidelines:\n"
        "- Distribute 2-4 callouts throughout the article, not all at the top\n"
        "- Content INSIDE callouts should be 1-3 sentences, punchy, specific\n"
        "- Don't repeat the same callout type more than 2x per article\n"
        "- KEY takeaway goes near the top OR near the end, never in the middle\n"
        "- Callouts should add value, not restate what the surrounding paragraph said\n\n"
        "Return ONLY this JSON structure (no markdown fences):\n"
        "{\n"
        '  "title": "article title",\n'
        '  "slug": "url-slug-version",\n'
        '  "focusKeyword": "the single Rank Math focus keyword",\n'
        '  "metaDescription": "meta description text (140-155 chars MAX)",\n'
        '  "excerpt": "1-2 sentence summary for article listings",\n'
        '  "content": "# Title\\n\\nFull article in markdown...",\n'
        '  "faq": [\n'
        '    {"q": "Question?", "a": "Answer"}\n'
        "  ],\n"
        '  "internalLinks": ["related-article-slug-1"],\n'
        '  "keywords": ["primary keyword", "secondary keyword"],\n'
        '  "wordCount": 1750\n'
        "}"
    )
