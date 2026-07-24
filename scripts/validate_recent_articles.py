"""Validate the 12 most-recent DB articles against THE compliance checklist
(core.article_criteria) — the real persisted content, not a pipeline self-report."""
import sys

sys.path.insert(0, "/home/jon/projects/perkins-roofing/video-archival")
from sqlalchemy import text  # noqa: E402

from core.article_criteria import check_compliance, failing  # noqa: E402
from jobs.article_job import _repair_inputs, _stamped_session  # noqa: E402

with _stamped_session(1) as db:
    known = _repair_inputs(db)["known_video_ids"]
    rows = db.execute(text(
        "SELECT slug, title, meta, content_md, focus_keyword, faq_json, jsonld_json, "
        "role, pillar_slug, updated_at "
        "FROM articles ORDER BY updated_at DESC NULLS LAST, generated_at DESC LIMIT 12")).fetchall()

n_pass = 0
print(f"{'slug':<52} {'result':<8} failing")
print("-" * 100)
for r in rows:
    slug, title, meta, content, kw, faq, jsonld, role, pillar_slug, updated = r
    ctx = {"role": role, "pillar_slug": pillar_slug, "title": title or "", "slug": slug or ""}
    comp = check_compliance(content or "", meta or "", jsonld or [], faq or [],
                            ctx, kw or slug or "", known)
    fails = failing(comp)
    if not fails:
        n_pass += 1
    tag = "PASS" if not fails else "FAIL"
    detail = ", ".join(f"{c.key}({c.detail})" if c.detail else c.key for c in fails)
    print(f"{slug[:52]:<52} {tag:<8} {detail}")

print("-" * 100)
print(f"\n{n_pass}/{len(rows)} of the 12 most-recent DB articles pass ALL content checks.")
print("(Note: category + featured image are WP-post facts, checked separately below.)")
