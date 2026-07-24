"""Post-batch cross-article QC pass over every article we control. Fixes the things the
per-article generative loop structurally can't:

  1. RELATIVIZE absolute perkinsroofing.net internal links -> host-portable /path (on staging the
     absolute ones bounce reviewers to prod).
  2. REPOINT each cluster->pillar link + its pillar_slug to the pillar's REAL slug (the LLM slug
     is non-deterministic, so the intended _slugify(pillar_keyword) usually 404s).
  3. Add pillar->cluster DOWN-links so the hub is bidirectional.

Re-publishes only the articles whose content changed (WP update + DB row), PRESERVING status
(published stays published). Dry by default; --apply to write. Idempotent. Run after each batch.
"""
import argparse
import re
import sys
from collections import defaultdict

sys.path.insert(0, "/home/jon/projects/perkins-roofing/video-archival")
from sqlalchemy import text  # noqa: E402

from adapters.wordpress import update  # noqa: E402
from api.routes.articles import _slugify  # noqa: E402
from app.models import Article, SessionLocal  # noqa: E402
from jobs.article_job import _markdown_to_html, _relativize_internal_links  # noqa: E402


def _title_case(s: str) -> str:
    return " ".join(w.capitalize() for w in (s or "").replace("-", " ").split())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    with SessionLocal() as db:
        db.info["tenant_id"] = 1
        rows = db.execute(text(
            "SELECT slug,title,content_md,focus_keyword,role,pillar_slug,wp_post_id,meta,"
            "jsonld_json,status FROM articles")).fetchall()

    our = {r[0] for r in rows}
    by_slug = {r[0]: list(r) for r in rows}
    pillar_real = {}   # intended pillar slug -> real pillar slug
    for r in rows:
        if r[4] == "pillar":
            pillar_real[_slugify(r[3] or r[0])] = r[0]
    clusters_by_pillar = defaultdict(list)
    cluster_repoint = {}   # cluster slug -> real pillar slug
    for r in rows:
        slug, _t, _c, fk, role, pslug, *_ = r
        if role != "cluster" or not pslug:
            continue
        real = pillar_real.get(pslug) or pillar_real.get(_slugify(pslug))
        if real and real in our:
            clusters_by_pillar[real].append((slug, r[1]))
            if pslug != real:
                cluster_repoint[slug] = real

    # accumulate content edits per slug, then publish once
    new_content = {s: r[2] or "" for s, r in by_slug.items()}
    new_pillar = {}

    # 1) relativize every article
    for s in new_content:
        new_content[s] = _relativize_internal_links(new_content[s])

    # 2) repoint cluster->pillar links + pillar_slug
    for cslug, real in cluster_repoint.items():
        old = by_slug[cslug][5]
        new_content[cslug] = re.sub(rf'href="/{re.escape(old)}/?"', f'href="/{real}"', new_content[cslug])
        new_pillar[cslug] = real

    # 3) pillar -> cluster down-links (idempotent)
    for pslug, kids in clusters_by_pillar.items():
        content = new_content[pslug]
        links = [f'<a href="/{ks}">{_title_case(kt or ks)}</a>'
                 for ks, kt in kids if f'href="/{ks}"' not in content]
        if not links:
            continue
        block = ('<h2>Related in This Guide</h2>\n<ul class="cluster-links">'
                 + "".join(f"<li>{a}</li>" for a in links) + "</ul>")
        if "youtube.com/@perkinsroofingcorp" in content:  # place before the subscribe footer
            i = content.rfind("<p>")
            content = content[:i] + block + "\n" + content[i:] if i != -1 else content + "\n" + block
        else:
            content = content + "\n" + block
        new_content[pslug] = content

    changed = [s for s in by_slug if new_content[s] != (by_slug[s][2] or "") or s in new_pillar]
    print(f"QC pass: {len(cluster_repoint)} cluster links to repoint, "
          f"{sum(1 for _ in clusters_by_pillar)} pillars to down-link, "
          f"{len(changed)} articles changed ({'APPLY' if args.apply else 'DRY'})")
    if not args.apply:
        for s in changed[:12]:
            tags = []
            if s in new_pillar:
                tags.append(f"repoint->{new_pillar[s]}")
            if _ABS := re.search(r'perkinsroofing\.net/', by_slug[s][2] or ""):
                tags.append("relativized")
            print(f"    {s[:46]:48} {tags}")
        return

    n = 0
    for s in changed:
        r = by_slug[s]
        wp, title, meta, jsonld, status = r[6], r[1], r[7], r[8], r[9]
        wp_status = "publish" if status == "published" else "draft"
        if wp:
            update(wp, title=title, html=_markdown_to_html(new_content[s]), meta_description=meta or "",
                   jsonld=jsonld or [], status=wp_status)
        wdb = SessionLocal(); wdb.info["tenant_id"] = 1
        try:
            row = wdb.get(Article, s)
            row.content_md = new_content[s]
            if s in new_pillar:
                row.pillar_slug = new_pillar[s]
            wdb.add(row); wdb.commit()
        finally:
            wdb.close()
        n += 1
    print(f"rewrote {n} articles (relativized + repointed + down-linked), status preserved.")


if __name__ == "__main__":
    main()
