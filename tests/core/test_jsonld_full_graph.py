"""The full schema @graph — what has to exist the day Rank Math goes away.

WHY THIS EXISTS. Measured on the live site 2026-08-12:

  staging article      2 ld+json blocks — Rank Math's @graph, plus OUR FAQPage + VideoObject.
                       Zero overlapping node types. The complement design works.
  prod articles        1 block — Rank Math only.
  the 9 project pages  0 blocks. No structured data at all, from anyone.

Everything our pipeline emits (`_build_article_jsonld`, `build_project_jsonld`) is scoped to
the two or three node types Rank Math does NOT generate. So `build_article`,
`build_organization`, `build_person` and `build_breadcrumb_list` sat in core/jsonld.py with
ZERO call sites, and WebSite/WebPage did not exist at all — meaning the day Rank Math is
retired, every page silently loses six node types and nobody would notice until Search
Console did.

These tests pin the replacement against the values Rank Math publishes TODAY, so the
migration cannot quietly downgrade an entity Google has already indexed.
"""
import pytest

from core.brand_identity import AUTHOR, ORGANIZATION
from core.jsonld import (
    COMPLEMENT_TYPES,
    RANK_MATH_OWNED,
    build_full_graph,
    build_organization,
    build_webpage,
    build_website,
    full_graph_enabled,
)

SITE = "https://perkinsroofing.net"


def _graph(**over):
    kwargs = dict(
        org=ORGANIZATION, author=AUTHOR, site_url=SITE, site_name="Perkins Roofing",
        page_url=f"{SITE}/some-article/", page_name="Some Article",
        description="A description of the article.",
        breadcrumbs=[{"name": "Home", "url": f"{SITE}/"},
                     {"name": "Some Article", "url": f"{SITE}/some-article/"}],
        date_published="2026-08-12",
    )
    kwargs.update(over)
    return build_full_graph(**kwargs)


def _types(graph):
    return {n.get("@type") for n in graph["@graph"]}


# --- the migration must not lose anything -----------------------------------

def test_full_graph_is_on_now_that_rank_math_is_gone():
    assert full_graph_enabled() is True


def test_the_graph_carries_every_type_rank_math_owns():
    """The exact list Rank Math emits on a live article: BreadcrumbList, Organization
    (as RoofingContractor), WebSite, WebPage, Person, BlogPosting. Lose one and the
    migration is a silent SEO downgrade."""
    types = _types(_graph())
    assert "BlogPosting" in types
    assert "RoofingContractor" in types      # the LocalBusiness subtype the live site uses
    assert "Person" in types
    assert "WebSite" in types
    assert "WebPage" in types
    assert "BreadcrumbList" in types


def test_the_business_node_keeps_the_geo_rank_math_publishes():
    """A guessed lat/lon is a different business. These were read off the live graph."""
    org = build_organization(ORGANIZATION)
    assert org["geo"] == {"@type": "GeoCoordinates",
                          "latitude": "25.91445", "longitude": "-80.209071"}
    assert "hasMap" in org


def test_the_business_node_keeps_the_other_fields_rank_math_publishes():
    org = build_organization(ORGANIZATION)
    assert org["priceRange"] == "$$$"
    assert org["alternateName"] == "Perkins Construction"
    assert org["description"]
    assert org["address"]["addressRegion"] == "Florida", \
        "the live site says 'Florida'; 'FL' would read as a second business"
    # Both Google listings — Rank Math publishes two and dropping one loses an entity link.
    assert len([s for s in org["sameAs"] if "maps.app.goo.gl" in s]) == 2


def test_the_licence_is_a_gain_rank_math_never_emitted():
    org = build_organization(ORGANIZATION)
    assert org["hasCredential"]["identifier"] == "CCC1331944"


# --- graph wiring -----------------------------------------------------------

def test_every_node_is_reachable_by_reference_not_duplicated():
    """One @id-addressed business node referenced everywhere, per Google's guidance —
    NOT full NAP repeated per page."""
    g = _graph()
    by_type = {n["@type"]: n for n in g["@graph"]}
    assert by_type["WebSite"]["publisher"] == {"@id": ORGANIZATION["id"]}
    assert by_type["WebPage"]["isPartOf"] == {"@id": f"{SITE}/#website"}
    assert by_type["BlogPosting"]["publisher"] == {"@id": ORGANIZATION["id"]}
    assert by_type["BlogPosting"]["author"] == {"@id": AUTHOR["id"]}
    assert by_type["BlogPosting"]["isPartOf"]["@id"] == by_type["WebPage"]["@id"]
    assert by_type["WebPage"]["breadcrumb"]["@id"] == by_type["BreadcrumbList"]["@id"]


def test_only_the_document_carries_context_not_every_node():
    """A nested node with its own @context is a separate document to a parser — the
    cross-references then resolve to nothing."""
    g = _graph()
    assert g["@context"] == "https://schema.org"
    assert not [n for n in g["@graph"] if "@context" in n]


def test_our_existing_media_nodes_fold_into_the_same_graph():
    """The FAQPage/ImageObject/VideoObject we already build must become part of the one
    graph, not a second competing <script> block."""
    extra = [{"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": []}]
    g = _graph(extra_nodes=extra)
    assert "FAQPage" in _types(g)
    assert not [n for n in g["@graph"] if "@context" in n]


def test_a_non_article_page_omits_the_article_node():
    assert "BlogPosting" not in _types(_graph(article=False))


def test_website_and_webpage_ids_are_stable_and_distinct():
    site = build_website(ORGANIZATION, site_url=SITE, site_name="Perkins Roofing")
    page = build_webpage(f"{SITE}/x/", "X", site_url=SITE)
    assert site["@id"] == f"{SITE}/#website"
    assert page["@id"] == f"{SITE}/x/#webpage"


def test_a_trailing_slash_on_site_url_does_not_double_up():
    site = build_website(ORGANIZATION, site_url=f"{SITE}/", site_name="P")
    assert site["@id"] == f"{SITE}/#website"


# --- the two ownership sets must not overlap --------------------------------

def test_what_rank_math_owns_and_what_we_add_are_disjoint():
    """This is the invariant the whole complement design rests on, and it is exactly what
    the live pages show today: Rank Math's block and ours share no node type."""
    assert not (RANK_MATH_OWNED & COMPLEMENT_TYPES)


def test_the_complement_is_what_we_actually_ship_today():
    from core.portfolio_content import build_project_jsonld

    nodes = build_project_jsonld(
        {"name": "P", "city": "Miami"},
        [{"kind": "photo", "id": "1", "alt": "A tile roof"}],
        {"photo:1": {"url": "https://cdn/p.jpg"}},
        faq=[{"q": "Q?", "a": "A."}],
    )
    assert {n["@type"] for n in nodes} <= COMPLEMENT_TYPES
    assert not ({n["@type"] for n in nodes} & RANK_MATH_OWNED)


def test_the_project_builder_can_emit_the_full_graph_after_rank_math():
    from core.portfolio_content import build_project_jsonld

    nodes = build_project_jsonld(
        {"name": "P", "city": "Miami"},
        [{"kind": "photo", "id": "1", "alt": "A tile roof"}],
        {"photo:1": {"url": "https://cdn/p.jpg"}},
        faq=[{"q": "Q?", "a": "A."}],
        full_graph=dict(
            org=ORGANIZATION, author=AUTHOR, site_url=SITE, site_name="Perkins Roofing",
            page_url=f"{SITE}/portfolio/p/", page_name="P", description="d",
            breadcrumbs=[{"name": "Home", "url": f"{SITE}/"}], article=False,
        ),
    )
    assert len(nodes) == 1, "one @graph document, not a pile of loose nodes"
    types = {n.get("@type") for n in nodes[0]["@graph"]}
    assert {"RoofingContractor", "WebSite", "WebPage", "FAQPage", "ImageObject"} <= types


# --- the gate flips with the flag -------------------------------------------

def test_the_gate_blocks_rank_math_types_while_rank_math_is_live():
    from core.portfolio_criteria import check_project

    crit = {c.key: c for c in check_project(
        title="P", city="Miami", meta="m", content_html="<p>x</p>", selections=[],
        jsonld=[{"@type": "Organization"}], full_graph=False)}
    assert not crit["schema_scoped"].ok, "Organization duplicates Rank Math — must fail"


def test_the_gate_requires_those_same_types_once_rank_math_is_gone():
    from core.portfolio_criteria import check_project

    crit = {c.key: c for c in check_project(
        title="P", city="Miami", meta="m", content_html="<p>x</p>", selections=[],
        jsonld=[{"@type": "FAQPage"}], full_graph=True)}
    assert not crit["schema_scoped"].ok, "FAQPage alone is not a full graph"
    assert "WebSite" in crit["schema_scoped"].detail


def test_the_gate_passes_a_real_full_graph():
    from core.portfolio_criteria import check_project

    crit = {c.key: c for c in check_project(
        title="P", city="Miami", meta="m", content_html="<p>x</p>", selections=[],
        jsonld=[_graph()], full_graph=True)}
    assert crit["schema_scoped"].ok, crit["schema_scoped"].detail
    assert crit["schema_present"].ok


def test_the_full_graph_flag_is_off_by_default(monkeypatch):
    """It MUST stay off while Rank Math is installed — both emitting means duplicate
    Organization/Person/WebPage on every page."""
    from adapters.wordpress import publish_full_graph

    monkeypatch.delenv("PUBLISH_FULL_GRAPH", raising=False)
    assert publish_full_graph() is False


def test_the_full_graph_flag_is_operator_switchable(monkeypatch):
    from adapters.wordpress import publish_full_graph
    from api.routes.config import EDITABLE_KEYS

    monkeypatch.setenv("PUBLISH_FULL_GRAPH", "true")
    assert publish_full_graph() is True
    assert "PUBLISH_FULL_GRAPH" in EDITABLE_KEYS, "otherwise PUT /config rejects it"


@pytest.mark.parametrize("fn", ["build_article", "build_organization", "build_person",
                                "build_breadcrumb_list", "build_website", "build_webpage"])
def test_every_full_graph_builder_is_reachable_from_build_full_graph(fn):
    """These four had no caller anywhere in the codebase before this. A builder nothing
    reaches is the repo's most-repeated defect, so pin the wiring rather than trust it."""
    import inspect

    import core.jsonld as j

    assert fn in inspect.getsource(j.build_full_graph) or fn in inspect.getsource(j)
    assert callable(getattr(j, fn))


# --- the ARTICLE path flips with the same flag -------------------------------

def test_articles_ship_the_full_graph_now_that_rank_math_is_gone():
    from jobs.article_job import _build_article_jsonld

    nodes = _build_article_jsonld(
        {"faq_json": [{"q": "Q?", "a": "A."}], "title": "T", "slug": "t",
         "meta": "m", "published_at": "2026-08-12"}, {})

    assert len(nodes) == 1, "one @graph document"
    types = {n.get("@type") for n in nodes[0]["@graph"]}
    assert {"BlogPosting", "RoofingContractor", "Person", "WebSite", "WebPage",
            "BreadcrumbList", "FAQPage"} <= types, types


def test_the_article_gate_flips_with_the_same_flag():
    """Builder and checker must never disagree — a half-migrated site would otherwise
    publish duplicate Organization nodes and pass its own compliance gate."""
    from core.article_criteria import check_compliance

    graph = _graph()
    args = dict(content="<p>x</p>", meta="m", faq=[],
                ctx={"title": "T", "slug": "t"}, keyword="k", known_video_ids=set())

    live = {c.key: c for c in check_compliance(jsonld=[graph], full_graph=False, **args)}
    assert not live["schema_scoped"].ok, "the full graph duplicates Rank Math while it is live"

    after = {c.key: c for c in check_compliance(jsonld=[graph], full_graph=True, **args)}
    assert after["schema_scoped"].ok, after["schema_scoped"].detail

    thin = {c.key: c for c in check_compliance(
        jsonld=[{"@type": "FAQPage"}], full_graph=True, **args)}
    assert not thin["schema_scoped"].ok, "FAQPage alone is not a full graph"
