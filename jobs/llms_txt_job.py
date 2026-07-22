"""Rebuild + push the /llms.txt manifest from the published-article index.

The live site carries a hand-authored llms.txt (Wendy's, June 2026). That prose is
the PREAMBLE, stored once in PlatformConfig LLMS_TXT_PREAMBLE (platform scope — seed
it with scripts/seed_llms_preamble.py). This job appends the machine-maintained
'## Articles' section and pushes the result to WordPress via the perkins-jsonld
plugin route. FAIL-SAFE: if no preamble is configured, the job SKIPS the push —
never overwrite the hand-written file with a generated default.

Run: .venv/bin/python -m jobs.llms_txt_job
Also triggered best-effort from jobs/promote_job.py after each successful promotion run.
"""
import adapters.wordpress as wordpress
from core.llms_txt import article_entries, with_preamble


def _preamble() -> str:
    """Hand-written llms.txt prose from PlatformConfig LLMS_TXT_PREAMBLE ('' if unset)."""
    try:
        from app.models import PlatformConfig, PlatformSessionLocal  # noqa: PLC0415
        with PlatformSessionLocal() as pdb:
            pdb.info["platform_scope"] = True
            row = pdb.get(PlatformConfig, "LLMS_TXT_PREAMBLE")
            if row and (row.value or "").strip():
                return row.value
    except Exception:  # noqa: BLE001 — treated as unset; run() skips the push
        pass
    return ""


def run(tenant_id: int = 1) -> dict:
    """Build preamble + published-article index and push to WP. Never raises on a
    push failure (returns {"ok": False, ...}) — callers are cron/promotion paths
    where llms.txt staleness must not abort anything."""
    preamble = _preamble()
    if not preamble.strip():
        return {"skipped": "no LLMS_TXT_PREAMBLE configured — refusing to overwrite the hand-written llms.txt"}

    base_url = wordpress.resolved_wp_url()
    if not base_url:
        return {"skipped": "WP_URL not configured"}

    from app.models import Article  # noqa: PLC0415
    from jobs.article_job import _stamped_session  # noqa: PLC0415
    with _stamped_session(tenant_id) as db:
        rows = (
            db.query(Article)
            .filter(Article.status == "published", Article.wp_post_id.isnot(None))
            .order_by(Article.slug)
            .all()
        )
        entries = article_entries(
            base_url,
            [{"title": a.title, "slug": a.slug, "meta_description": a.meta} for a in rows],
        )

    content = with_preamble(preamble, entries)
    try:
        result = wordpress.push_llms_txt(content)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200], "articles": len(entries)}
    return {"ok": True, "articles": len(entries), **result}


if __name__ == "__main__":
    print(run())
