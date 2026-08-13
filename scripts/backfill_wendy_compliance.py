#!/usr/bin/env python3
"""Apply Wendy's 2026-07-28 review to the articles ALREADY in the database.

The compliance gate (`core.article_criteria`) only guards NEW generation. Every article written
before 2026-07-28 was generated under the old rules — two of which told the generator to do the
opposite of what she now wants — so the back catalogue still carries all of it. Measured:

    375 articles   112 published · 262 SCHEDULED · 1 draft
    375  carry the retired youtube.com/channel/UChJZ... URL
    300  carry an in-content <div class="toc"> block
    289  carry more VideoObject nodes than embedded players
    239  carry a bare <table> with no border
     90  carry an unlinked "Learn more:" paragraph

The 262 scheduled ones matter most, and fixing the rows here is NOT enough for them: promote_job
only flips the WordPress STATUS (`wordpress.update_status`) — it never sends the body. A corrected
row with a stale WP body therefore publishes the very defect this script just repaired. Scheduled
rows need --repush-scheduled; already-published rows need --repush. --apply alone touches only the
database.

Reuses the exact same pure functions the generator's ensures use, so the backfill and the gate
cannot drift apart.

Usage: DB_URL=... PYTHONPATH=. .venv/bin/python scripts/backfill_wendy_compliance.py \
           [--apply] [--repush] [--repush-scheduled] [--repush-limit N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter

_HREF_RE = re.compile(r'href="([^"]+)"')
# Imported so this script counts blocks exactly as the gate and the fixer do. A local
# re-spelling here is how a backfill reports "clean" on content the gate still rejects.
from core.article_repair import RELATED_BLOCK_RE as _REL_RE  # noqa: E402

_EMBED_RE = re.compile(r"<iframe\b[^>]*\bsrc=[\"'][^\"']*(?:youtube\.com|youtu\.be)", re.IGNORECASE)


def _fix_content(content: str, valid_slugs=frozenset(), pillar_map=None) -> str:
    """Every deterministic ensure Wendy's review added, in the generator's own order."""
    from core.article_repair import (
        _repair_relative_links,
        _repair_tel_hrefs,
        _tidy_related_links,
    )
    from core.brand_identity import YOUTUBE_CHANNEL_URL, YOUTUBE_CHANNEL_URL_LEGACY
    from jobs.article_job import _ensure_learn_more_links, _ensure_table_borders, _strip_toc

    # Anchors FIRST: a slashless href is stripped by WordPress, so the anchor arrives dead. Rooting
    # or unwrapping it before the "Learn more" pass means a pointer that CAN be saved is kept
    # rather than dropped for looking unlinked.
    c, _ = _repair_tel_hrefs(content or "")
    c, _ = _repair_relative_links(c, set(valid_slugs), dict(pillar_map or {}))
    c = _ensure_table_borders(_ensure_learn_more_links(_strip_toc(c)))
    c = _tidy_related_links(c)
    # The channel moved to the @handle; the old channel-ID URL is retired, not merely alternative.
    return c.replace(YOUTUBE_CHANNEL_URL_LEGACY, YOUTUBE_CHANNEL_URL).replace(
        "https://youtube.com/channel/UChJZpBYXOuR0j1EHJugv5hg", YOUTUBE_CHANNEL_URL)


def _fix_jsonld(jsonld, content: str):
    """Drop VideoObject nodes with no matching embedded player (Google's rule)."""
    nodes = jsonld if isinstance(jsonld, list) else json.loads(jsonld or "[]")
    n_embeds = len(_EMBED_RE.findall(content or ""))
    kept, seen_vo = [], 0
    for n in nodes:
        if isinstance(n, dict) and n.get("@type") == "VideoObject":
            if seen_vo >= n_embeds:
                continue
            seen_vo += 1
        kept.append(n)
    return kept



def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write (otherwise print and exit)")
    ap.add_argument("--repush", action="store_true",
                    help="also push updated bodies to WordPress for ALREADY-PUBLISHED articles")
    ap.add_argument("--limit", type=int, default=0, help="cap rows processed (0 = all)")
    ap.add_argument("--repush-scheduled", action="store_true",
                    help="also push bodies for articles still awaiting publication, keeping "
                         "their current WP status (they publish the stale body otherwise)")
    ap.add_argument("--repush-limit", type=int, default=0,
                    help="cap the repush (0 = all) — use 1 to smoke-test one live post first")
    args = ap.parse_args()

    from sqlalchemy import select

    from app.models import Article, SessionLocal
    from core.article_criteria import (
        _BARE_TABLE_RE,
        _DEAD_ANCHOR_RE,
        _LEARN_MORE_P_RE,
        _TOC_BLOCK_RE,
        _is_linked,
    )
    from core.internal_links import SERVICE_SLUGS
    from jobs.article_job import _repair_inputs

    s = SessionLocal()
    s.info["tenant_id"] = 1
    inputs = _repair_inputs(s)
    valid_slugs = set(inputs["valid_slugs"]) | set(SERVICE_SLUGS)
    pillar_map = inputs["pillar_map"]
    rows = s.execute(select(Article)).scalars().all()
    if args.limit:
        rows = rows[:args.limit]

    stats, changed = Counter(), []
    for a in rows:
        before, before_jl = a.content_md or "", a.jsonld_json
        after = _fix_content(before, valid_slugs, pillar_map)
        after_jl = _fix_jsonld(before_jl, after)

        if _TOC_BLOCK_RE.search(before):
            stats["toc_block"] += 1
        if [x for x in _LEARN_MORE_P_RE.findall(before) if not _is_linked(x)]:
            stats["unlinked_learn_more"] += 1
        if _DEAD_ANCHOR_RE.search(before):
            stats["dead_anchor"] += 1
        if _BARE_TABLE_RE.search(before):
            stats["bare_table"] += 1
        if "UChJZpBYXOuR0j1EHJugv5hg" in before:
            stats["legacy_yt_url"] += 1
        blocks = _REL_RE.findall(before)
        if len(blocks) > 1:
            stats["multi_related_blocks"] += 1     # Wendy, 2026-08-04: "repeated 3 times"
        if blocks:
            h = [x.rstrip("/").lower() for x in _HREF_RE.findall(blocks[0])]
            if len(h) != len(set(h)):
                stats["dupe_related"] += 1
        n_old = sum(1 for n in (before_jl if isinstance(before_jl, list) else [])
                    if isinstance(n, dict) and n.get("@type") == "VideoObject")
        if n_old > sum(1 for n in after_jl
                       if isinstance(n, dict) and n.get("@type") == "VideoObject"):
            stats["excess_videoobject"] += 1

        if after != before or after_jl != (before_jl or []):
            changed.append(a)
            stats[f"status_{a.status or 'none'}"] += 1
            if args.apply:
                a.content_md = after
                a.jsonld_json = after_jl

    print(f"{len(rows)} articles scanned, {len(changed)} would change")
    for k, v in sorted(stats.items()):
        print(f"  {k:<24} {v}")

    if not args.apply:
        s.rollback()
        print("\n(dry run — nothing written; pass --apply to commit)")
        s.close()
        return

    s.commit()
    print(f"\nwrote {len(changed)} articles")

    if args.repush:
        from adapters.wordpress import resolved_wp_url, update
        from jobs.article_job import _markdown_to_html, split_featured_image

        # Every PUBLISHED row, not just the ones this run changed. Fixing the rows and pushing
        # them are separate steps, and the backfill is idempotent — so on the run where you
        # actually push, `changed` is already empty and keying off it would push nothing.
        # --repush-scheduled also pushes rows still waiting to publish. Their WP bodies are
        # just as stale as the live ones, and jobs/promote_job only flips the STATUS — it
        # never sends the body. So promoting them without this publishes the very defect the
        # backfill just fixed, on every one of them. Those rows are pushed with status=None,
        # which leaves WordPress's own status untouched — see the update() call below.
        want = ("published", "scheduled") if args.repush_scheduled else ("published",)
        targets = [
            {"slug": a.slug, "wp_post_id": a.wp_post_id, "title": a.title,
             "meta": a.meta, "jsonld": list(a.jsonld_json or []),
             "content_md": a.content_md or "", "status": a.status or "",
             "focus_keyword": getattr(a, "focus_keyword", None)}
            for a in rows
            if (a.status or "") in want and getattr(a, "wp_post_id", None)
        ]
        if args.repush_limit:
            targets = targets[:args.repush_limit]

        # DETACH from the database before the network phase. Pushing ~470 posts takes ~15
        # minutes, and holding the session open across it leaves an idle transaction that
        # prod kills at 5 minutes (idle_in_transaction_session_timeout) — every push then
        # succeeds and the script still exits 1 on teardown, which reads exactly like a failed
        # backfill. Measured 2026-08-12: 473 pushed, 0 failed, exit 1. Same rule as
        # jobs/companycam_sync: commit before any network call.
        base = resolved_wp_url()
        s.close()

        print(f"\nrepushing {len(targets)} articles to {base} …")
        pushed = failed = 0
        for a in targets:
            try:
                body, _ = split_featured_image(a["content_md"])
                # status MUST be passed explicitly: adapters.wordpress.update defaults it to
                # "draft", so omitting it would UNPUBLISH every live article this touches.
                # title/meta are required too — omitting them would blank the post.
                # Hard-coding "publish" is right for a live article and catastrophic for one
                # that is not — it would publish every scheduled draft the moment its body was
                # fixed. For anything not already published, send status=None: adapters.
                # wordpress.update then omits the field entirely and WordPress leaves the
                # status alone. That is also the ONLY safe option for a post in "future" —
                # per that function's own docstring, sending "future" without a `date`
                # publishes it immediately.
                wp_status = "publish" if a["status"] == "published" else None
                update(
                    a["wp_post_id"],
                    title=a["title"] or a["slug"],
                    html=_markdown_to_html(body),
                    meta_description=a["meta"] or "",
                    jsonld=a["jsonld"],
                    status=wp_status,
                    focus_keyword=a["focus_keyword"],
                )
                pushed += 1
                print(f"  ok {a['slug']}")
            except Exception as exc:                      # noqa: BLE001
                failed += 1
                print(f"  repush FAILED {a['slug']}: {exc}", file=sys.stderr)
        print(f"repushed {pushed} articles ({failed} failed)")
        if failed:
            sys.exit(1)
        return
    else:
        n_pub = sum(1 for a in changed if (a.status or "") == "published")
        if n_pub:
            print(f"\n⚠️  {n_pub} of these are ALREADY PUBLISHED — the DB is fixed but the live "
                  f"pages are not. Re-run with --repush to push the updated bodies.")
    s.close()


if __name__ == "__main__":
    main()
