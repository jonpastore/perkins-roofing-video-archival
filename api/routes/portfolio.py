"""Avada Portfolio admin routes (#384 — backend/publisher already existed as
scripts/portfolio_publish.py + scripts/portfolio_prefill.py; this is the admin UI's API).

Export ``router`` only; do NOT create a FastAPI app here. Mount this router onto the
main app in api/app.py with ``app.include_router(router)``.

Role requirements (from core.authz, same grants as api/routes/articles.py):
  - article_read      → sales, web_admin, admin (GET)
  - manage_articles   → web_admin, admin (POST publish)

Projects are ROWS (portfolio_projects, migration 0050) — full CRUD. They began as
scripts.portfolio_prefill.CANDIDATES (transcribed from
Wendy's projects doc — see that module's docstring for provenance). There is no DB table for
portfolio projects; WordPress itself is the status source of truth (checked live via
adapters.wordpress.find_portfolio_post).

Permission gate: Avada portfolio write-ups need three client permissions (name the property,
use photos, use video) before they can go out. These were hardcoded False with no way to record
a real answer; they now persist per project in ``portfolio_curation`` (migration 0048) along
with the curated media selection, so an editor can clear a project and publish it.

Media curation (2026-07-29): GET /portfolio/{slug}/media returns the mirrored CompanyCam media
for the project (jobs/companycam_sync.py), the current selection, and the SEO/AIO score;
PUT /portfolio/{slug}/curation records the selection. Media is filtered by permission on the
way out AND re-filtered at publish, so revoking a permission drops the media from the page.
"""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth import get_db_session, require_role
from core.portfolio import map_to_post, needs_human
from core.portfolio_content import (
    build_faq,
    build_meta,
    build_project_jsonld,
    build_write_up,
    project_full_graph_kwargs,
)
from core.portfolio_criteria import check_project, failing, publishable
from core.portfolio_criteria import summary as criteria_summary
from core.portfolio_facts import scope_for_dominant_client
from core.portfolio_media import (
    companycam_project_id,
    gallery_html,
    publishable_media,
    score_project,
    validate_selection,
)
from core.portfolio_projects import seed_records, unique_slug, validate_record

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

class SelectionItem(BaseModel):
    kind: str = Field(description="'photo' or 'video'")
    id: str
    alt: str = ""


class CurationIn(BaseModel):
    permission_property: bool = False
    permission_photos: bool = False
    permission_video: bool = False
    selections: list[SelectionItem] = Field(default_factory=list)


class ProjectIn(BaseModel):
    """Editable project fields. Everything else about a project is derived or curated.

    max_length MIRRORS the DB columns (migration 0050). Without it an oversized field reaches
    Postgres and 500s — SQLite silently accepts any length, so tests cannot catch it and the
    repo has a schema-bounds guard that does (tests/api/test_negative_maxlength.py).
    """
    name: str = Field(max_length=300)
    city: str = Field(default="", max_length=120)
    section: str = Field(default="commercial", max_length=40)
    companycam_url: str = Field(default="", max_length=500)
    youtube_url: str = Field(default="", max_length=500)
    date_start: str = Field(default="", max_length=60)
    date_end: str = Field(default="", max_length=60)
    notes: str = ""
    search_terms: list[str] = Field(default_factory=list)


def _ensure_seeded(db: Session) -> None:
    """First call migrates the 13 hardcoded candidates into the table, once.

    Idempotent and keyed by slug, so it can never duplicate a project or overwrite an edit an
    editor has already made to one.
    """
    from app.models import PortfolioProject  # noqa: PLC0415

    if db.query(PortfolioProject.id).first() is not None:
        return
    for record in seed_records():
        db.add(PortfolioProject(tenant_id=1, **record))
    db.commit()
    logger.info("portfolio: seeded %d project records from the candidate list",
                len(seed_records()))


def _projects(db: Session, *, include_archived: bool = False):
    from app.models import PortfolioProject  # noqa: PLC0415

    _ensure_seeded(db)
    q = db.query(PortfolioProject)
    if not include_archived:
        q = q.filter(PortfolioProject.archived_at.is_(None))
    return q.order_by(PortfolioProject.name).all()


def _project_or_404(db: Session, slug: str):
    from app.models import PortfolioProject  # noqa: PLC0415

    _ensure_seeded(db)
    row = db.query(PortfolioProject).filter(PortfolioProject.slug == slug).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="portfolio project not found")
    return row


def _candidate_or_404(db: Session, slug: str) -> dict:
    return _project_or_404(db, slug).as_record()


def _curation_row(db: Session, slug: str):
    from app.models import PortfolioCuration  # noqa: PLC0415
    return db.query(PortfolioCuration).filter(PortfolioCuration.slug == slug).one_or_none()


def _permissions(row) -> dict[str, bool]:
    return {
        "permission_property": bool(row.permission_property) if row else False,
        "permission_photos": bool(row.permission_photos) if row else False,
        "permission_video": bool(row.permission_video) if row else False,
    }


def _available_media(db: Session, cc_project_id: str | None, perms: dict[str, bool]) -> dict:
    """Mirrored CompanyCam media for this project, filtered to what may be published.

    Only media a crew TAGGED for publication is offered — "Projects" for photos,
    "ProjectsVideo" for clips. A project's mirror holds everything the crew shot, including
    tear-off, damage and progress frames that were never meant for a public gallery
    (Building 77: 9 of 312 photos and 2 of 22 videos carry the tags).

    Newest capture FIRST: Wendy wants the gallery to read finished roof -> job start.

    The tag test runs in Python rather than SQL because `tags` is JSON and the containment
    operators differ between Postgres and the SQLite test dialect; one project's media is a
    few hundred rows, already fetched by project_id.
    """
    from adapters.companycam import projects_tag_id, projects_video_tag_id  # noqa: PLC0415
    from app.models import CompanyCamPhoto, CompanyCamVideo  # noqa: PLC0415

    if not cc_project_id:
        return {"photos": [], "videos": []}

    photo_tag, video_tag = projects_tag_id(), projects_video_tag_id()

    def _tagged(row, tag: str) -> bool:
        return tag in [str(t) for t in (row.tags or [])]

    photos = [
        {"companycam_photo_id": p.companycam_photo_id, "url": p.url,
         "captured_at": p.captured_at.isoformat() if p.captured_at else None}
        for p in db.query(CompanyCamPhoto)
        .filter(CompanyCamPhoto.project_id == str(cc_project_id))
        .order_by(CompanyCamPhoto.captured_at.desc().nullslast(),
                  CompanyCamPhoto.id.desc()).all()
        if _tagged(p, photo_tag)
    ]
    videos = [
        {"companycam_video_id": v.companycam_video_id, "url": v.url,
         "thumbnail_url": v.thumbnail_url, "internal": bool(v.internal),
         "captured_at": v.captured_at.isoformat() if v.captured_at else None}
        for v in db.query(CompanyCamVideo)
        .filter(CompanyCamVideo.project_id == str(cc_project_id))
        .order_by(CompanyCamVideo.captured_at.desc().nullslast(),
                  CompanyCamVideo.id.desc()).all()
        if _tagged(v, video_tag)
    ]
    return publishable_media(
        photos, videos,
        permission_photos=perms["permission_photos"],
        permission_video=perms["permission_video"],
    )


def _slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _wp_admin_url_for(wp_post_id: int | None) -> str | None:
    if not wp_post_id:
        return None
    from adapters.wordpress import resolved_wp_url  # noqa: PLC0415
    base = resolved_wp_url()
    return f"{base}/wp-admin/post.php?post={wp_post_id}&action=edit" if base else None


def _candidate_summary(candidate: dict, wp_by_title: dict | None = None,
                       curation_by_slug: dict | None = None) -> dict:
    preview = map_to_post(
        {"name": candidate["name"], "city": candidate["city"], "section": candidate["section"]},
        content_html="",
    )
    wp_post = None
    if wp_by_title is not None:
        wp_post = wp_by_title.get(preview["title"].strip().lower())
    else:
        from adapters.wordpress import find_portfolio_post  # noqa: PLC0415
        try:
            wp_post = find_portfolio_post(candidate["name"])
        except Exception as exc:  # noqa: BLE001 — WP unreachable must not break the list
            logger.warning("wp lookup failed for portfolio candidate %s: %s", candidate["name"], exc)

    slug = candidate.get("slug") or _slugify(candidate["name"])
    row = (curation_by_slug or {}).get(slug)
    perms = _permissions(row)
    gate = {
        "Permission to name property": perms["permission_property"],
        "Permission to use photos": perms["permission_photos"],
        "Permission to use video": perms["permission_video"],
    }
    selections = list(row.selections or []) if row else []

    return {
        "slug": slug,
        "name": candidate["name"],
        "city": candidate["city"],
        "property_type": preview["category"],
        "roof_type": preview["skills"][0] if preview["skills"] else None,
        "companycam_url": candidate.get("companycam_url") or None,
        "youtube_url": candidate.get("youtube_url") or None,
        "curated_photos": sum(1 for s in selections if s.get("kind") == "photo"),
        "curated_videos": sum(1 for s in selections if s.get("kind") == "video"),
        **perms,
        "missing_permissions": needs_human(gate),
        "wp_post_id": wp_post["id"] if wp_post else None,
        "wp_status": wp_post["status"] if wp_post else None,
        "wp_admin_url": _wp_admin_url_for(wp_post["id"] if wp_post else None),
        # Why this project is refused, from the last time the gate ran on a write (0051).
        # None = never gated, [] = gated and clean — the list view must not show those alike.
        "gate_failures": candidate.get("gate_failures"),
        "gate_checked_at": candidate.get("gate_checked_at"),
    }


def _media_by_id(available: dict) -> dict:
    return {
        **{f"photo:{p['companycam_photo_id']}": p for p in available.get("photos", [])},
        **{f"video:{v['companycam_video_id']}": v for v in available.get("videos", [])},
    }


def _scope_lines(db: Session, candidate: dict) -> list[str]:
    """Scope descriptions Perkins actually sold on this project, from the Knowify mirror.

    Three ORM steps (projects -> contracts -> deliverables) rather than raw SQL: it keeps RLS
    obviously in force and stays inside the tenancy gate's rules.

    Matches on ProjectName ONLY. The pre-existing matcher ILIKEs the whole JSON payload, which
    is how the search term "7900" matched a generic "Tile Re-Roof" whose dollar amount happened
    to contain those digits — attaching another customer's scope to a public page is worse than
    having no scope at all.

    Change-order projects are excluded: they are extras negotiated later, and letting them in
    meant "Isola" returned hoist/railing lines and never reached the main re-roof contract.
    """
    from app.models import KnowifyRawRecord  # noqa: PLC0415

    K = KnowifyRawRecord
    name = K.payload["ProjectName"].as_string()
    rows: list[dict] = []

    for term in candidate.get("search_terms") or []:
        try:
            projects = db.query(
                K.payload["Id"].as_string(), K.payload["ClientId"].as_string(), name,
            ).filter(
                K.entity == "projects", K.is_present.is_(True),
                name.ilike(f"%{term}%"), ~name.ilike("%change order%"),
            ).limit(50).all()
            if not projects:
                continue
            by_pid = {pid: (client, pname) for pid, client, pname in projects}

            contracts = db.query(
                K.payload["Id"].as_string(), K.payload["ProjectId"].as_string(),
            ).filter(
                K.entity == "contracts", K.is_present.is_(True),
                K.payload["ProjectId"].as_string().in_(list(by_pid)),
            ).limit(200).all()
            if not contracts:
                continue
            by_cid = {cid: by_pid[pid] for cid, pid in contracts if pid in by_pid}

            deliverables = db.query(
                K.payload["ContractId"].as_string(), K.payload["Description"].as_string(),
            ).filter(
                K.entity == "deliverables", K.is_present.is_(True),
                K.payload["ContractId"].as_string().in_(list(by_cid)),
            ).limit(400).all()

            for cid, description in deliverables:
                client, pname = by_cid[cid]
                rows.append({"client_id": client, "project_name": pname,
                             "description": description})
        except Exception as exc:  # noqa: BLE001 — no scope is a degraded page, not an error
            logger.warning("knowify scope lookup failed for %r: %s", term, exc)
            continue

    return scope_for_dominant_client(rows)


def _location_slugs() -> list[str]:
    """Slugs of the location pages that actually exist, so an internal link never 404s.

    Best-effort: WordPress being unreachable costs the location link, not the page."""
    from adapters.wordpress import list_location_page_slugs  # noqa: PLC0415
    try:
        return list_location_page_slugs()
    except Exception as exc:  # noqa: BLE001
        logger.warning("wp location page lookup failed: %s", exc)
        return []


def _render_project(candidate: dict, selections: list, available: dict,
                    db: Session | None = None) -> tuple[str, list]:
    """(body_html, jsonld) for a project — the SAME render the score is taken of and the one
    publish ships, so a score can never describe a page that was never built."""
    media = _media_by_id(available)
    _apply_sanitized_urls(selections, media)
    photos = sum(1 for s in selections if s.get("kind") == "photo")
    videos = sum(1 for s in selections if s.get("kind") == "video")
    scope = _scope_lines(db, candidate) if db is not None else []
    body = build_write_up(
        candidate,
        gallery_html=gallery_html(selections, media),
        known_location_slugs=_location_slugs(),
        photo_count=photos,
        video_count=videos,
        scope_lines=scope,
    )
    faq = build_faq(candidate, photo_count=photos, video_count=videos, scope_lines=scope)
    from core.brand_identity import ORGANIZATION  # noqa: PLC0415
    return body, build_project_jsonld(
        candidate, selections, media, faq=faq,
        organization_id=ORGANIZATION.get("id"),
        full_graph=project_full_graph_kwargs(candidate),
    )


def _placeholder_content(candidate: dict) -> str:
    """Minimal draft body when no LLM-grounded write-up exists yet (see
    scripts/portfolio_prefill.py for the full grounded-generation pipeline — out of scope
    here). The post is created as a WP *draft*; an editor finishes it in WordPress."""
    notes = (candidate.get("notes") or "").strip()
    if notes:
        return f"<p>{notes}</p>"
    city = candidate.get("city") or "South Florida"
    return f"<p>{candidate['name']} — a {candidate['section']} roofing project in {city}.</p>"


@router.get("")
def list_portfolio(
    db: Session = Depends(get_db_session),
    claims=Depends(require_role("article_read")),
):
    from adapters.wordpress import list_portfolio_posts  # noqa: PLC0415
    from app.models import PortfolioCuration  # noqa: PLC0415

    curation_by_slug = {r.slug: r for r in db.query(PortfolioCuration).all()}
    projects = [p.as_record() for p in _projects(db)]
    # One WP fetch, matched locally — 13 sequential authed searches crawled on slow WP.
    try:
        wp_by_title = {p["title"].lower(): p for p in list_portfolio_posts()}
    except Exception as exc:  # noqa: BLE001 — WP unreachable must not break the list
        logger.warning("wp portfolio list fetch failed: %s", exc)
        wp_by_title = {}
    return [_candidate_summary(c, wp_by_title, curation_by_slug) for c in projects]


def _sanitize_selected_photos(selections: list, available: dict) -> int | None:
    """Sanitize selected photos to WP-hosted copies, recording the result ON each selection.

    Writes ``wp_url``/``wp_media_id`` into the selection dicts and points ``available`` at the
    sanitized url, so the caller may persist the selections and every later render — preview,
    review and publish alike — resolves to the same WP copy without re-uploading.

    Returns the WP media id of the first selected photo, for the featured image (WP wants an
    attachment and the sanitized upload already is one, so it is the same round trip).

    A photo that fails to sanitize keeps its CDN url, which the ``media_sanitized`` blocker then
    refuses. That is deliberate: a failure here must not be able to publish the original.
    """
    from adapters.wordpress import sanitize_photo_to_media  # noqa: PLC0415

    by_id = {str(p.get("companycam_photo_id")): p for p in available.get("photos", [])}
    featured: int | None = None
    for sel in selections:
        if sel.get("kind") != "photo":
            continue
        row = by_id.get(str(sel.get("id")))
        if not row or not row.get("url"):
            continue
        if sel.get("wp_url") and sel.get("wp_media_id"):  # already sanitized on a previous save
            row["url"] = sel["wp_url"]
            featured = featured if featured is not None else sel["wp_media_id"]
            continue
        try:
            attachment = sanitize_photo_to_media(row["url"], "photo", str(sel["id"]))
        except Exception as exc:  # noqa: BLE001 — any failure must fall through to the gate
            logger.warning("photo sanitize failed for %s: %s", sel.get("id"), exc)
            continue
        sel["wp_url"] = row["url"] = attachment.get("source_url", row["url"])
        sel["wp_media_id"] = attachment.get("id")
        if featured is None:
            featured = attachment.get("id")
    return featured


def _apply_sanitized_urls(selections: list, media: dict) -> None:
    """Point the media map at the sanitized WP copy recorded when the selection was saved.

    Without this the curation PREVIEW would render CompanyCam urls while publish rendered WP
    ones, so ``media_sanitized`` would sit permanently red in the UI and
    web/src/pages/Portfolio.tsx would keep the publish button disabled forever — a gate nobody
    can satisfy is the same as no feature. _gate promises it evaluates the html that ships; this
    is what makes that true for every caller rather than for publish alone.
    """
    for sel in selections:
        row = media.get(f"{sel.get('kind')}:{sel.get('id')}")
        if row and sel.get("wp_url"):
            row["url"] = sel["wp_url"]


def _record_gate_failures(db: Session, slug: str, failures: list[dict]) -> None:
    """Persist WHY this project is refused, so the reason outlives the response.

    Without this the verdict exists only in a 422 body: nobody can later ask "why is this one
    not published?" without re-running the gate, and no correction loop can pick up the work.
    Stores the gate's own failing criteria (keys included) rather than a sentence, because a
    rendered summary is not machine-correctable and would drift from the checklist that decides.

    Takes the failures as dicts so a caller that has ALREADY run the gate can hand its result
    straight over — re-running it would mean a second full render plus scope lookup per save.
    """
    from app.models import PortfolioProject  # noqa: PLC0415
    from core.companycam.mirror import _utcnow  # noqa: PLC0415

    row = (db.query(PortfolioProject)
           .filter(PortfolioProject.slug == slug, PortfolioProject.archived_at.is_(None))
           .one_or_none())
    if row is None:
        return
    row.gate_failures = list(failures)
    row.gate_checked_at = _utcnow()
    db.commit()


def _gate(db: Session, candidate: dict, selections: list, available: dict,
          perms: dict[str, bool]) -> tuple[list, str, list]:
    """(criteria, body_html, jsonld) for a project — the gate applied to the REAL page.

    Publish and the review view call this same function: a gate that evaluates anything other
    than the exact html being shipped is worse than no gate, because it reassures without
    checking.
    """
    body_html, jsonld = _render_project(candidate, selections, available, db)
    scope = _scope_lines(db, candidate)
    criteria = check_project(
        title=candidate.get("name", ""), city=candidate.get("city"),
        meta=build_meta(candidate), content_html=body_html, selections=selections,
        scope_lines=scope, jsonld=jsonld, permissions=perms,
        full_graph=True,
    )
    return criteria, body_html, jsonld


@router.post("", status_code=201)
def create_portfolio_project(
    body: ProjectIn,
    db: Session = Depends(get_db_session),
    claims=Depends(require_role("manage_articles")),
):
    """Create a project. Refuses PII at the door — see core.portfolio_projects.validate_record."""
    from app.models import PortfolioProject  # noqa: PLC0415

    record = body.model_dump()
    problems = validate_record(record)
    if problems:
        raise HTTPException(status_code=422, detail={"problems": problems})

    taken = [p.slug for p in _projects(db, include_archived=True)]
    row = PortfolioProject(
        tenant_id=1, slug=unique_slug(record["name"], taken),
        updated_by=(claims or {}).get("email"), **record,
    )
    db.add(row)
    db.commit()
    return _candidate_summary(row.as_record())


@router.put("/{slug}")
def update_portfolio_project(
    slug: str,
    body: ProjectIn,
    db: Session = Depends(get_db_session),
    claims=Depends(require_role("manage_articles")),
):
    """Edit a project. The SLUG never changes: it is the join key for curation and the
    WordPress lookup, so renaming the slug would orphan an editor's media selection."""
    row = _project_or_404(db, slug)
    record = body.model_dump()
    problems = validate_record(record)
    if problems:
        raise HTTPException(status_code=422, detail={"problems": problems})

    for field, value in record.items():
        setattr(row, field, value)
    row.updated_by = (claims or {}).get("email")
    db.commit()
    return _candidate_summary(row.as_record())


@router.delete("/{slug}")
def archive_portfolio_project(
    slug: str,
    db: Session = Depends(get_db_session),
    claims=Depends(require_role("manage_articles")),
):
    """Archive (soft delete). A published project must stay findable, or nobody can locate the
    WordPress page to take it down."""
    from core.companycam.mirror import _utcnow  # noqa: PLC0415

    row = _project_or_404(db, slug)
    row.archived_at = _utcnow()
    row.updated_by = (claims or {}).get("email")
    db.commit()
    return {"slug": slug, "archived": True}


@router.post("/{slug}/restore")
def restore_portfolio_project(
    slug: str,
    db: Session = Depends(get_db_session),
    claims=Depends(require_role("manage_articles")),
):
    row = _project_or_404(db, slug)
    row.archived_at = None
    row.updated_by = (claims or {}).get("email")
    db.commit()
    return _candidate_summary(row.as_record())


@router.get("/{slug}/media")
def get_portfolio_media(
    slug: str,
    db: Session = Depends(get_db_session),
    claims=Depends(require_role("article_read")),
):
    """Curation view: what media exists for this project, what's selected, and how it scores.

    Media comes from the CompanyCam mirror (jobs/companycam_sync.py), filtered by the client
    permissions recorded for this project — so an uncleared project shows an empty gallery
    rather than photos an editor could accidentally publish.
    """
    candidate = _candidate_or_404(db, slug)
    row = _curation_row(db, slug)
    perms = _permissions(row)
    cc_id = (row.companycam_project_id if row and row.companycam_project_id
             else companycam_project_id(candidate.get("companycam_url")))
    available = _available_media(db, cc_id, perms)
    selections = list(row.selections or []) if row else []

    preview = map_to_post(
        {"name": candidate["name"], "city": candidate["city"], "section": candidate["section"]},
        content_html="",
    )
    criteria, body_html, jsonld = _gate(db, candidate, selections, available, perms)
    score = score_project(
        title=preview["title"], meta=build_meta(candidate),
        content_html=body_html, selections=selections,
        has_jsonld=bool(jsonld), permissions=perms,
        faq=build_faq(
            candidate,
            photo_count=sum(1 for s in selections if s.get("kind") == "photo"),
            video_count=sum(1 for s in selections if s.get("kind") == "video"),
            scope_lines=_scope_lines(db, candidate),
        ),
    )
    return {
        "slug": slug,
        "name": candidate["name"],
        "companycam_project_id": cc_id,
        "companycam_url": candidate.get("companycam_url") or None,
        "youtube_url": (row.youtube_url if row and row.youtube_url
                        else candidate.get("youtube_url")) or None,
        **perms,
        "available": available,
        "selections": selections,
        "score": score,
        # The EXACT html publish will ship, so an editor reviews the page rather than trusting
        # a number. Same render, same call — see _render_project.
        "preview_html": body_html,
        "scope_lines": _scope_lines(db, candidate),
        # The publish gate, evaluated on the html above. `publishable` false means the POST
        # /publish will refuse — the UI must not offer a button that cannot work.
        "gate": criteria_summary(criteria),
    }


@router.put("/{slug}/curation")
def put_portfolio_curation(
    slug: str,
    body: CurationIn,
    db: Session = Depends(get_db_session),
    claims=Depends(require_role("manage_articles")),
):
    """Record the curated media selection and the client permissions.

    The selection is validated against what is actually publishable *under the permissions in
    this same request*, so an editor cannot clear photos, select images, and then un-clear
    photos while leaving the selection behind.
    """
    from app.models import PortfolioCuration  # noqa: PLC0415

    candidate = _candidate_or_404(db, slug)
    row = _curation_row(db, slug)
    cc_id = (row.companycam_project_id if row and row.companycam_project_id
             else companycam_project_id(candidate.get("companycam_url")))

    perms = {
        "permission_property": body.permission_property,
        "permission_photos": body.permission_photos,
        "permission_video": body.permission_video,
    }
    available = _available_media(db, cc_id, perms)
    selections = [s.model_dump() for s in body.selections]
    problems = validate_selection(selections, available)
    if problems:
        raise HTTPException(status_code=422, detail={"problems": problems})

    # Crop CompanyCam's burned-in GPS stamp off each selected photo and upload the clean copy to
    # WordPress NOW, recording wp_url/wp_media_id on the selection. Doing it on save rather than
    # at publish is what lets the curation preview show the same urls publish will ship, so the
    # media_sanitized blocker can actually go green. Only selected photos are fetched — the
    # mirror holds 155,997 and all but a handful are never published. Costs one download + crop +
    # upload per newly-selected photo; re-saving an unchanged selection re-uses the attachment.
    _sanitize_selected_photos(selections, available)

    if row is None:
        row = PortfolioCuration(slug=slug, companycam_project_id=cc_id)
        db.add(row)
    row.companycam_project_id = cc_id
    row.permission_property = body.permission_property
    row.permission_photos = body.permission_photos
    row.permission_video = body.permission_video
    row.selections = selections
    row.updated_by = (claims or {}).get("email")
    db.commit()

    # Record why this project is (still) refused, on the write the editor just made.
    # get_portfolio_media already runs the gate, so record from ITS result: computing it a
    # second time here would mean another full render plus Knowify scope lookup per save.
    response = get_portfolio_media(slug, db=db, claims=claims)
    _record_gate_failures(db, slug, (response.get("gate") or {}).get("failing", []))
    return response


@router.post("/{slug}/review")
def review_portfolio_project(
    slug: str,
    db: Session = Depends(get_db_session),
    claims=Depends(require_role("manage_articles")),
):
    """Run the three adversarial critics over the page that WOULD publish.

    The deterministic gate (returned as ``gate``) is what refuses a publish; these critics read
    the page the way a person would and catch what a regex cannot — an indirect identifier like
    "the corner unit above the tennis courts", a claim with no basis in the contract scope, a
    page that says nothing. Findings are ADVISORY: an LLM verdict is not reproducible enough to
    block on, but a blocker here should stop a human from pressing publish, and the UI shows it
    that way.

    Stateless: nothing is persisted, so a review always reflects the current curation rather
    than a stale verdict from before someone changed the gallery.
    """
    import re as _re  # noqa: PLC0415

    from adapters import llm as llm_mod  # noqa: PLC0415
    from core.portfolio_critique import (  # noqa: PLC0415
        CRITICS,
        CRITIQUE_SCHEMA,
        critique_prompt,
        merge,
        parse_findings,
    )

    candidate = _candidate_or_404(db, slug)
    row = _curation_row(db, slug)
    perms = _permissions(row)
    selections = list(row.selections or []) if row else []
    cc_id = (row.companycam_project_id if row and row.companycam_project_id
             else companycam_project_id(candidate.get("companycam_url")))
    available = _available_media(db, cc_id, perms)
    criteria, body_html, _jsonld = _gate(db, candidate, selections, available, perms)

    page = {
        "title": candidate.get("name", ""), "city": candidate.get("city", ""),
        "meta": build_meta(candidate), "content_html": body_html,
        "scope_lines": _scope_lines(db, candidate),
        # Alt text is pulled out separately: it publishes, a reader never sees it, and it is
        # where an identifier hides from everyone but a crawler.
        "alt_texts": _re.findall(r'<img[^>]*\balt="([^"]*)"', body_html),
    }

    findings: dict[str, list[dict]] = {}
    llm = llm_mod.get_default()
    for lens in CRITICS:
        try:
            parsed = llm.chat(critique_prompt(lens, page), want_json=True,
                              response_schema=CRITIQUE_SCHEMA)
            findings[lens] = parse_findings(parsed)
        except Exception as exc:  # noqa: BLE001 — one dead critic must not lose the others
            logger.warning("portfolio review: lens %s failed: %s", lens, exc)
            findings[lens] = []

    merged = merge(findings)
    return {
        "slug": slug,
        "gate": criteria_summary(criteria),
        "critique": merged,
        "critique_blockers": [f for f in merged if f.get("severity") in ("blocker", "major")],
        "lenses_run": sorted(findings),
    }


@router.post("/{slug}/publish")
def publish_portfolio_project(
    slug: str,
    db: Session = Depends(get_db_session),
    claims=Depends(require_role("manage_articles")),
):
    candidate = _candidate_or_404(db, slug)
    row = _curation_row(db, slug)
    perms = _permissions(row)

    # Publish the curated gallery with the write-up. Built from the SAME permission-filtered
    # media list the curation view showed, so a permission revoked after selection drops the
    # media here too rather than shipping it.
    selections = list(row.selections or []) if row else []
    cc_id = (row.companycam_project_id if row and row.companycam_project_id
             else companycam_project_id(candidate.get("companycam_url")))
    available = _available_media(db, cc_id, perms)

    # Swap every SELECTED photo's CompanyCam CDN url for a WP-hosted copy with the burned-in
    # GPS stamp cut off. Done here, before the render, because available[] is the one map both
    # the gallery html and the JSON-LD ImageObject read their urls from — sanitizing anywhere
    # downstream would clean one and leave the other. Only selected media is fetched: the
    # mirror holds 155,997 photos and all but a handful are never published.
    featured_media = _sanitize_selected_photos(selections, available)

    # THE GATE. Blockers are privacy and client permission; majors are quality problems that
    # make a page not worth having. Both refuse, and the response names every one so the editor
    # can fix them — this replaces the old permission-only check, which could not see an address
    # in an image alt or a customer name in the title.
    criteria, body_html, jsonld = _gate(db, candidate, selections, available, perms)
    _record_gate_failures(db, slug, [c.to_dict() for c in failing(criteria)])
    if not publishable(criteria):
        raise HTTPException(status_code=422, detail=criteria_summary(criteria))

    # JSON-LD goes to post-meta, NOT into the body: WordPress strips <script> from content on
    # an application-password write (verified by reading a published post back — the whole
    # block was gone, with no error). adapters.wordpress stores it and reports whether the
    # meta actually persisted.
    post = map_to_post(
        {"name": candidate["name"], "city": candidate["city"], "section": candidate["section"]},
        content_html=body_html,
    )
    import requests  # noqa: PLC0415

    from adapters.wordpress import publish_portfolio_post  # noqa: PLC0415
    try:
        # update_existing: every candidate already has a draft, so without this a curated
        # gallery would return 200 and change nothing on the page.
        result = publish_portfolio_post(post, update_existing=True, jsonld=jsonld,
                                        featured_media=featured_media)
    except requests.RequestException as exc:
        logger.warning("wp portfolio publish failed for %s: %s", candidate["name"], exc)
        raise HTTPException(status_code=502, detail=f"WordPress publish failed: {exc}") from exc

    return {**_candidate_summary(candidate, None, {slug: row} if row else None),
            "publish_result": result, "gate": criteria_summary(criteria)}
