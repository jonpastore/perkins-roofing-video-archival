"""Robustness suite for THE shared deterministic finalize (jobs.article_job.finalize_article).

Why this file exists. Before 2026-08-13 the article pipeline's finalize had exactly ONE test —
a slug assertion in tests/core/test_seo.py — while four different orchestrators each defined
their own order for the same ~28 transforms. Every defect found in that review lived in the
COMPOSITION rather than inside any single function, which is precisely what a suite of
single-function, single-call tests cannot see: 563 article tests were green throughout.

So the tests here are deliberately not unit tests. Each one pins a property of the whole
finalize:

  * every criterion advertising fixable=True is actually fixed by it     (the structural guard)
  * finalize(finalize(x)) == finalize(x) across adversarial inputs       (idempotency)
  * the ordering invariants that were previously held only by comments   (order)
  * salvageable content survives                                         (no silent data loss)
"""
from __future__ import annotations

import pytest

from core.article_criteria import check_compliance
from jobs.article_job import finalize_article

KW = "metal roofing"


def _fields(content: str, **over) -> dict:
    f = {
        "content_md": content,
        "faq_json": [{"q": f"What about {i}?", "a": "A full sentence answer."} for i in range(4)],
        "title": "Metal Roofing Costs In South Florida",
        "meta": "M" * 130,
        "slug": "metal-roofing-costs",
        "jsonld_json": [],
    }
    f.update(over)
    return f


def _ctx(**over) -> dict:
    c = {"role": "cluster", "pillar_slug": None}
    c.update(over)
    return c


def _criteria(fields: dict, ctx: dict, known=frozenset()) -> dict:
    return {c.key: c for c in check_compliance(
        fields["content_md"], fields["meta"], fields["jsonld_json"], fields["faq_json"],
        {**ctx, "title": fields["title"], "slug": fields["slug"]}, KW, set(known))}


# Criteria that genuinely cannot be satisfied without I/O: they need a Video row, retrieval, or
# the Gemini frame picker. finalize skips its repair pass entirely when db is None, and
# _ensure_video_link/_ensure_article_image degrade rather than fabricate. Listing them here is a
# deliberate, reviewed exemption — anything NOT on this list must be fixable offline.
NEEDS_IO = {"video_embed", "curated_image", "videoobject_schema", "valid_video_ids",
            "videoobject_only_embedded",
            # Rank Math vs full-graph publish mode — not fixable offline without tenant/WP settings.
            "schema_scoped"}

# One body per fixable criterion, each FAILING that criterion on the way in.
DEFECT_FIXTURES = {
    "no_blog": '<h2>Roofs</h2><p>Metal roofing and roof repair.</p>'
               '<p>See <a href="/blog/tile-roofing-company/">tile roofing</a>.</p>',
    "subscribe_cta": '<h2>Roofs</h2><p>Metal roofing and roof repair.</p>'
                     '<p>Sub: https://www.youtube.com/channel/UChJZpBYXOuR0j1EHJugv5hg</p>',
    "table_bordered": '<h2>Roofs</h2><p>Metal roofing and roof repair.</p>'
                      '<table><tr><td>cost</td></tr></table>',
    "no_toc_block": '<h2>Roofs</h2><div class="toc"><p><strong>In This Article</strong></p>'
                    '<ul><li><a href="#a">A</a></li></ul></div><p>Metal roofing.</p>',
    "learn_more_linked": '<h2>Roofs</h2><p>Metal roofing and roof repair.</p>'
                         '<p>Learn more: roof repair services</p>',
    "no_dead_anchors": '<h2>Roofs</h2><p>Metal roofing and <a>roof repair</a>.</p>',
    # TWO blocks, one of them prefix-less. The prefix-less form is the one the fixer's regex used
    # to be blind to, so it could neither merge into it nor collapse it — a state the gate
    # reported as fixable=True forever.
    "related_links_single_block": '<h2>Roofs</h2><p>Metal roofing and roof repair.</p>'
                                  '<p class="related-links"><a href="/metal-roofing-company/">M</a></p>'
                                  '<p class="related-links">Related: <a href="/tile-roofing-company/">T</a></p>',
    "meta_len": '<h2>Roofs</h2><p>Metal roofing and roof repair in South Florida.</p>',
    "faq_ge4": '<h2>Roofs</h2><p>Metal roofing and roof repair in South Florida.</p>',
}


@pytest.mark.parametrize("key", sorted(DEFECT_FIXTURES))
def test_every_fixable_criterion_is_actually_fixed_by_finalize(key):
    """A criterion that reports fixable=True and has no reachable fixer is an infinite loop.

    _compliance_gate re-runs the deterministic pass up to _COMPLIANCE_MAX_ITERS times for a
    failing fixable criterion, then BLOCKS the article. Three shipped in exactly that state —
    no_blog (nothing stripped the segment), subscribe_cta (the only rewrite lived in a backfill
    script), pillar_link (repair wrote the resolved slug while the gate searched for the topic
    key) — each burning four LLM iterations per article before giving up.
    """
    fields = _fields(DEFECT_FIXTURES[key])
    if key == "meta_len":
        fields["meta"] = "too short"
    if key == "faq_ge4":
        fields["faq_json"] = []
    ctx = _ctx()

    before = _criteria(fields, ctx)
    assert not before[key].ok, f"fixture for {key} must FAIL it on the way in, or it proves nothing"

    finalize_article(fields, ctx, KW, db=None)
    after = _criteria(fields, ctx)
    assert after[key].ok, (
        f"{key} is advertised fixable={before[key].fixable} but finalize did not fix it: "
        f"{after[key].detail!r}")


def test_no_criterion_is_left_failing_and_fixable_after_finalize():
    """The sweep: over a body carrying EVERY defect at once, finalize must leave nothing that
    is both failing and fixable. This is the guard that would have caught the whole class.

    The body is deliberately article-length. `seo_ranking` (Rank Math) and `question_heading`
    are computed from real prose — keyword density, word count, headings — so a three-sentence
    synthetic stub fails them for reasons that have nothing to do with the defects under test,
    and exempting them would blind the sweep to two genuinely fixable criteria.
    """
    prose = ("Metal roofing is the most durable choice for South Florida homes, and metal "
             "roofing costs less over its lifetime than three shingle replacements. ")
    dirty = (
        '<div class="toc"><p><strong>In This Article</strong></p><ul><li><a href="#a">A</a></li></ul></div>'
        f'<h2 id="a">Metal roofing costs</h2><p>{prose * 12}</p>'
        f'<h2>Metal roofing installation</h2><p>{prose * 12}</p>'
        f'<h2>Metal roofing maintenance</h2><p>{prose * 12}</p>'
        '<p>Learn more: roof repair services</p>'
        '<p>Dead <a>anchor</a> and a <a href="tile-roofing-company">slashless one</a>.</p>'
        '<p>See <a href="/blog/tile-roofing-company/">tile</a>.</p>'
        '<p>Sub: https://www.youtube.com/channel/UChJZpBYXOuR0j1EHJugv5hg</p>'
        '<table><tr><td>cost</td></tr></table>'
        '<p class="related-links"><a href="/metal-roofing-company/">Metal</a></p>'
    )
    fields, ctx = _fields(dirty), _ctx()
    finalize_article(fields, ctx, KW, db=None)

    stuck = [c.key for c in _criteria(fields, ctx).values()
             if not c.ok and c.fixable and c.key not in NEEDS_IO]
    assert not stuck, f"failing AND fixable after finalize — the gate will loop then block: {stuck}"


# ── idempotency across adversarial shapes ────────────────────────────────────

IDEMPOTENCY_SEEDS = {
    "absolute prose link": '<h2>R</h2><p>Metal roofing. '
                           '<a href="https://perkinsroofing.net/roof-repair-services/">Repair</a></p>',
    "existing related block": '<h2>R</h2><p>Metal roofing and roof repair.</p>'
                              '<p class="related-links">Related: <a href="/metal-roofing-company/">M</a></p>',
    "prefix-less related block": '<h2>R</h2><p>Metal roofing and roof repair.</p>'
                                 '<p class="related-links"><a href="/metal-roofing-company/">M</a></p>',
    "pre-existing toc": '<div class="toc"><p><strong>In This Article</strong></p>'
                        '<ul><li><a href="#a">A</a></li></ul></div><h2 id="a">R</h2><p>Metal roofing.</p>',
    "slashless learn more": '<h2>R</h2><p>Metal roofing.</p>'
                            '<p>Learn more: <a href="roof-repair-services">Repair</a></p>',
    "bare learn more": '<h2>R</h2><p>Metal roofing.</p>\nLearn more: roof repair\n',
    "bare table": '<h2>R</h2><p>Metal roofing.</p><table><tr><td>x</td></tr></table>',
    "no h2 at all": '<p>Metal roofing and roof repair across South Florida.</p>',
    "keyword-free headings": '<h2>Overview</h2><p>Shingles and tile for Florida homes.</p>',
    "blog path": '<h2>R</h2><p>Metal roofing.</p><p><a href="/blog/x/">x</a></p>',
    "legacy youtube url": '<h2>R</h2><p>Metal roofing. '
                          'https://www.youtube.com/channel/UChJZpBYXOuR0j1EHJugv5hg</p>',
    "href-less anchor": '<h2>R</h2><p>Metal roofing and <a>repair</a>.</p>',
    "empty body": "",
}


@pytest.mark.parametrize("label", sorted(IDEMPOTENCY_SEEDS))
def test_finalize_is_idempotent(label):
    """finalize(finalize(x)) == finalize(x).

    Non-idempotence is a LIVE bug here, not a theoretical one: finalize runs 2-3 times per
    article (generate, the compliance-gate re-pass, and any reprocess/backfill run). The
    2026-08 duplicate-related-links defect — 2-4 blocks on 183 of 183 articles — was exactly
    this, and no test in the suite applied any transform twice.
    """
    fields, ctx = _fields(IDEMPOTENCY_SEEDS[label]), _ctx()
    finalize_article(fields, ctx, KW, db=None)
    once = {k: fields[k] for k in ("content_md", "title", "slug", "meta")}
    finalize_article(fields, ctx, KW, db=None)
    for k, v in once.items():
        assert fields[k] == v, f"{label}: finalize changed {k} on the second pass"


def test_finalize_converges_and_stays_converged_over_many_cycles():
    """Four cycles, not two — a defect that adds one block per cycle is invisible at two."""
    from core.article_repair import RELATED_BLOCK_RE

    fields, ctx = _fields('<h2>R</h2><p>Metal roofing and roof repair in South Florida.</p>'), _ctx()
    seen = []
    for _ in range(4):
        finalize_article(fields, ctx, KW, db=None)
        seen.append(fields["content_md"])
        assert len(RELATED_BLOCK_RE.findall(fields["content_md"])) <= 1
    assert seen[1] == seen[3] == seen[2], "body must be stable from the second cycle on"


# ── ordering invariants that used to be held only by comments ────────────────

def test_salvageable_learn_more_anchor_is_rooted_not_deleted():
    """A slashless href is a pointer that CAN be saved; deleting the paragraph loses body copy.

    This decided the outcome by pass ORDER: scripts/backfill_wendy_compliance repaired anchors
    first and kept the copy, the compliance gate ran _ensure_learn_more_links first and produced
    ''. Rooting inside the ensure removes the dependency rather than documenting it.
    """
    fields, ctx = _fields('<h2>R</h2><p>Metal roofing.</p>'
                          '<p>Learn more: <a href="roof-repair-services">Roof repair</a></p>'), _ctx()
    finalize_article(fields, ctx, KW, db=None)
    assert "Learn more:" in fields["content_md"], "salvageable copy must survive"
    assert 'href="/roof-repair-services/"' in fields["content_md"], "and be rooted"


def test_unlinked_learn_more_pointer_is_still_dropped():
    """The counterpart: rooting must not resurrect a pointer that was never a link at all."""
    fields, ctx = _fields('<h2>R</h2><p>Metal roofing.</p>\nLearn more: roof repair\n'), _ctx()
    finalize_article(fields, ctx, KW, db=None)
    assert _criteria(fields, ctx)["learn_more_linked"].ok


def test_toc_anchors_are_stamped_even_though_the_visible_block_is_removed():
    """ensure_toc THEN _strip_toc: step 2 deletes what step 1 built, and that is intended —
    only the <h2 id> anchors are wanted, because the theme's sidebar TOC links to them. Reads
    like dead work to a refactorer; it is the reason their sidebar has anything to point at.

    Needs 3+ H2s: ensure_toc deliberately no-ops below that ("a TOC on a 2-section article is
    noise", core/seo.py), and that no-op also means no ids — so a short article legitimately
    has no anchors and this invariant only applies to real ones.
    """
    body = ('<h2>Metal roofing costs</h2><p>Metal roofing in South Florida.</p>'
            '<h2>Installation</h2><p>Standing seam panels go on with clips.</p>'
            '<h2>Maintenance</h2><p>Rinse the panels and check the fasteners.</p>')
    fields, ctx = _fields(body), _ctx()
    finalize_article(fields, ctx, KW, db=None)
    assert 'id="' in fields["content_md"], "H2 anchors must survive for the sidebar TOC"
    assert _criteria(fields, ctx)["no_toc_block"].ok, "the visible block must not"


def test_internal_links_are_relative_after_finalize():
    """_ensure_internal_links must precede _relativize_internal_links. That undocumented pair
    IS the 183/183 bug: relativize erases the absolute BASE_URL string _append_service_links
    guards on. Rank Math's rm_internal_link also only counts relative hrefs."""
    from core.internal_links import BASE_URL

    fields, ctx = _fields('<h2>R</h2><p>Metal roofing and roof repair in South Florida.</p>'), _ctx()
    finalize_article(fields, ctx, KW, db=None)
    assert f'href="{BASE_URL}' not in fields["content_md"], "internal hrefs must be relativized"


def test_finalize_never_empties_a_real_body():
    """A finalize that returns '' has destroyed the article. Guard every seed."""
    for label, body in IDEMPOTENCY_SEEDS.items():
        if not body:
            continue
        fields, ctx = _fields(body), _ctx()
        finalize_article(fields, ctx, KW, db=None)
        assert fields["content_md"].strip(), f"{label}: finalize emptied the body"


def test_finalize_preserves_prose_it_did_not_author():
    """Transforms may add, rewrite links, and drop dead pointers — never edit body sentences."""
    sentence = "Standing seam panels resist uplift better than exposed-fastener panels."
    fields, ctx = _fields(f'<h2>Metal roofing</h2><p>{sentence}</p>'), _ctx()
    finalize_article(fields, ctx, KW, db=None)
    assert sentence in fields["content_md"]


def test_finalize_tolerates_missing_and_empty_fields():
    """Called from four orchestrators over DB rows with NULL columns; must not raise."""
    fields = {"content_md": "", "faq_json": None, "title": "", "meta": None,
              "slug": "", "jsonld_json": None}
    finalize_article(fields, _ctx(), KW, db=None)
    assert fields["slug"], "a slug must be derived from the keyword when the row has none"
    assert isinstance(fields["faq_json"], list)
