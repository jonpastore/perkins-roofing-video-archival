"""v2 FastAPI serving surface — auth-gated (Firebase ID token + core.authz role matrix).
This is the PROD entrypoint (replaces the unauthenticated app/api.py). Search/ask require an
authenticated sales|admin caller; /internal/promote is the Cloud Scheduler target, protected
at the Cloud Run IAM layer (scheduler-sa OIDC, run.invoker)."""
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.audit_mw import AuditMiddleware
from api.auth import current_claims, get_db_session, require_internal_tenants, require_role, require_role_db
from api.middleware.cors import DynamicCORSMiddleware
from api.routes.admin_metrics import router as admin_metrics_router
from api.routes.archive import router as archive_router
from api.routes.articles import router as articles_router
from api.routes.audit import router as audit_router
from api.routes.clips import router as clips_router
from api.routes.comments import router as comments_router
from api.routes.config import router as config_router
from api.routes.contract_faq import router as contract_faq_router
from api.routes.customers import router as customers_router
from api.routes.dashboard import router as dashboard_router
from api.routes.email import router as email_router
from api.routes.estimator import router as estimator_router
from api.routes.faq import router as faq_router
from api.routes.invoices import router as invoices_router
from api.routes.knowify import router as knowify_router
from api.routes.logs import router as logs_router
from api.routes.measurements import router as measurements_router
from api.routes.payments import router as payments_router
from api.routes.price_book import router as price_book_router
from api.routes.pricing_configs import router as pricing_configs_router
from api.routes.proposal_gen import router as proposal_gen_router
from api.routes.proposals import router as proposals_router
from api.routes.quotes import router as quotes_router
from api.routes.scheduling import router as scheduling_router
from api.routes.squares import router as squares_router
from api.routes.suggestions import router as suggestions_router
from api.routes.topics import router as topics_router
from api.routes.users import me_router
from api.routes.users import router as users_router
from api.routes.video import router as video_router
from app import answer as A
from app import retrieval as R
from app.config import settings
from app.observability import Cost

app = FastAPI(title="Perkins Video Intelligence API", version="2.0")


@app.on_event("startup")
def _assert_rls_enforceable() -> None:
    """H2 fail-closed guard: RLS is a silent no-op if the app DB role is SUPERUSER/
    BYPASSRLS. The prod `app` role is verified NOSUPERUSER NOBYPASSRLS (Cloud SQL
    created it that way; confirmed 2026-07-09 against 29 RLS-FORCED tables), so this
    check passes at boot and now REFUSES TO SERVE if the role ever regains bypass.
    No-op on SQLite (dev/test).

    Fail-closed contract (deepsec C2): the RuntimeError raised by
    assert_rls_enforceable(refuse_to_serve=True) — the role CAN bypass RLS — MUST
    propagate and crash the revision. Only transient import/connection errors are
    swallowed, so a DB blip at boot doesn't crash-loop the service."""
    import logging
    try:
        from app.models import engine
        from core.tenant import assert_rls_enforceable
    except Exception:  # noqa: BLE001 — import failure: can't verify, proceed (non-fatal)
        logging.getLogger(__name__).warning("RLS enforceability check skipped (import)", exc_info=True)
        return
    try:
        assert_rls_enforceable(engine, refuse_to_serve=True)
    except RuntimeError:
        raise  # deliberate fail-closed — role can bypass RLS; abort startup
    except Exception:  # noqa: BLE001 — transient DB/connection blip: log, don't block boot
        logging.getLogger(__name__).warning("RLS enforceability check skipped (transient)", exc_info=True)


app.add_middleware(DynamicCORSMiddleware)

# Audit every mutating request (migration 0036). Added here rather than per-route: there are
# 86 mutating endpoints across 25 modules, and hand-instrumenting them covers 86 and misses
# the 87th the day it is added. Fail-open by construction — see api/audit_mw.py.
app.add_middleware(AuditMiddleware)


@app.middleware("http")
async def _reset_cost_per_request(request, call_next):
    # The llm.py per-run guardrail counts against a process-global Cost counter. Cloud Run Jobs
    # are fresh processes (one run each), but this long-lived API would accumulate forever and
    # eventually trip the cap on EVERY request — a self-DoS. Scope the counter to one request.
    Cost.reset()
    return await call_next(request)
app.include_router(email_router)
app.include_router(video_router)
app.include_router(archive_router)
app.include_router(articles_router)
app.include_router(scheduling_router)
app.include_router(topics_router)
app.include_router(estimator_router)
app.include_router(pricing_configs_router)
app.include_router(invoices_router)
app.include_router(payments_router)
app.include_router(dashboard_router)
app.include_router(knowify_router)
app.include_router(quotes_router)
app.include_router(price_book_router)
app.include_router(proposal_gen_router)
app.include_router(measurements_router)
app.include_router(faq_router)
app.include_router(contract_faq_router)
app.include_router(config_router)
app.include_router(users_router)
app.include_router(me_router)
app.include_router(suggestions_router)
app.include_router(clips_router)
app.include_router(comments_router)
app.include_router(logs_router)
app.include_router(customers_router)
app.include_router(proposals_router)
app.include_router(squares_router)
app.include_router(admin_metrics_router)
app.include_router(audit_router)


class Query(BaseModel):
    query: str
    k: int = 8


@app.get("/healthz")
@app.get("/health")
def healthz():
    # /healthz is swallowed by Google Frontend on Cloud Run (reserved path — GFE
    # returns an HTML 404 without ever reaching the container). /health is the
    # probe URL that works in prod; /healthz kept for local/container use.
    return {"ok": True}


@app.get("/me")
def me(claims=Depends(current_claims)):
    """Effective identity for the signed-in user — the SPA reads its role from here so
    default-admins resolve server-side (the source of truth), not from the raw token claim."""
    return {"email": claims.get("email"), "role": claims.get("role") or None}


# ── F5: per-tenant settings (Marketing + KB) + brand-kit upload URL ──────────
# tenants.settings is a PLATFORM-level table (RLS-exempt), so these use a
# platform-scoped session + the caller's resolved tenant_id from verified claims.
# Merge is Python-side (read dict → update sub-key → write back) so it works on
# both SQLite (tests) and Postgres, preserving all other keys (F3 deposit etc.).
# Authz: marketing_articles / kb_archive_manage are held by admin(*) + web_admin
# and NOT by sales — the correct gate without inventing new §11 actions (R2: bless).

def _tenant_settings_read(tenant_id: int) -> dict:
    from app.models import PlatformSessionLocal, Tenant
    with PlatformSessionLocal() as db:
        db.info["platform_scope"] = True
        row = db.get(Tenant, tenant_id)
        return dict(row.settings or {}) if row else {}


def _tenant_settings_merge(tenant_id: int, sub_key: str, sub_value: dict) -> dict:
    from app.models import PlatformSessionLocal, Tenant
    with PlatformSessionLocal() as db:
        db.info["platform_scope"] = True
        row = db.get(Tenant, tenant_id)
        if row is None:
            raise HTTPException(404, "tenant not found")
        merged = dict(row.settings or {})
        merged[sub_key] = {**(merged.get(sub_key) or {}), **sub_value}
        row.settings = merged
        db.commit()
        return merged


def _require_tenant(claims) -> int:
    """Resolve the caller's tenant_id from verified claims, or 403 (deepsec H3).

    Never falls back to tenant 1: a platform_admin with no impersonation context has
    tenant_id=None and must NOT silently read/write Perkins' (tenant 1) settings."""
    tid = claims.get("tenant_id")
    if tid is None:
        raise HTTPException(403, "no tenant context (impersonate a tenant to manage its settings)")
    return tid


@app.get("/admin/tenant/settings")
def get_tenant_settings(claims=Depends(require_role_db("marketing_articles"))):
    from core.tenant_settings import TenantSettings
    raw = _tenant_settings_read(_require_tenant(claims))
    return TenantSettings.load(raw).model_dump()


@app.put("/admin/tenant/settings/marketing")
def put_marketing_settings(body: dict, claims=Depends(require_role_db("marketing_articles"))):
    # social_accounts is read-only via this path (OAuth tokens live in Secret Manager).
    body.pop("social_accounts", None)
    merged = _tenant_settings_merge(_require_tenant(claims), "marketing", body)
    return {"marketing": merged.get("marketing", {})}


@app.put("/admin/tenant/settings/kb")
def put_kb_settings(body: dict, claims=Depends(require_role_db("kb_archive_manage"))):
    merged = _tenant_settings_merge(_require_tenant(claims), "kb", body)
    return {"kb": merged.get("kb", {})}


@app.post("/admin/tenant/brand/upload-url")
def brand_upload_url(body: dict, claims=Depends(require_role_db("marketing_articles"))):
    """Issue a V4 pre-signed GCS PUT URL so the browser uploads brand assets directly
    to GCS (never through Cloud Run). The client separately PUTs the returned gcs_uri
    into settings.brand via /admin/tenant/settings/marketing."""
    import os

    from core.brand_kit import brand_upload_signed_url
    asset_name = body.get("asset_name")
    content_type = body.get("content_type", "application/octet-stream")
    if not asset_name:
        raise HTTPException(422, "asset_name required")
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    if not project:
        raise HTTPException(503, "GCS not configured (GOOGLE_CLOUD_PROJECT unset)")
    from google.cloud import storage  # noqa: PLC0415 — heavy import, endpoint-local
    tid = _require_tenant(claims)
    url = brand_upload_signed_url(
        tid, asset_name, content_type,
        storage.Client(), f"{project}-media",
    )
    gcs_uri = f"gs://{project}-media/tenants/{tid}/brand/{asset_name}"
    return {"upload_url": url, "gcs_uri": gcs_uri}


@app.post("/search")
def search(q: Query, _claims=Depends(require_role("search")),
           db: Session = Depends(get_db_session)):
    return R.search(q.query, q.k, db=db)


@app.post("/ask")
def ask(q: Query, _claims=Depends(require_role("ask")),
        db: Session = Depends(get_db_session)):
    return A.ask(q.query, q.k, db=db)


@app.get("/ask/suggest")
def ask_suggest(
    q: str,
    _claims=Depends(require_role("ask")),
    db: Session = Depends(get_db_session),
):
    """Return up to 3 previously-cached questions similar to q (debounce-friendly).

    Postgres: pgvector cosine ANN restricted to the 0.85–0.95 suggestion band.
    SQLite (dev): prefix/substring match on question_norm as a cheap stand-in.

    Response: [{question, answer, similarity}]

    Pre-seeding from faq_entries is a follow-up; the cache self-populates from /ask traffic.
    """
    import numpy as np
    from sqlalchemy import text

    from app.llm import embed
    from app.models import AskCache
    from core.ask_cache import normalize_question, should_suggest

    if not q or not q.strip():
        return []

    norm = normalize_question(q)
    is_pg = settings.DB_URL.startswith("postgres")

    if is_pg:
        from pgvector.psycopg import register_vector
        register_vector(db.connection().connection.driver_connection)
        q_vec = np.array(embed([q])[0], dtype=np.float32)
        rows = db.execute(
            text(
                "SELECT id, "
                "1 - (embedding::halfvec(3072) <=> CAST(:q AS halfvec(3072))) AS sim "
                "FROM ask_cache "
                "ORDER BY embedding::halfvec(3072) <=> CAST(:q AS halfvec(3072)) "
                "LIMIT 10"
            ),
            {"q": q_vec},
        ).fetchall()
        results = []
        for row in rows:
            sim = float(row.sim)
            if not should_suggest(sim):
                continue
            entry = db.get(AskCache, row.id)
            if entry:
                results.append({
                    "question": entry.question,
                    "answer": entry.answer_json,
                    "similarity": round(sim, 4),
                })
            if len(results) >= 3:
                break
        return results

    # SQLite dev fallback: substring match on question_norm
    entries = (
        db.query(AskCache)
        .filter(AskCache.question_norm.contains(norm[:40]))
        .limit(3)
        .all()
    )
    return [
        {"question": e.question, "answer": e.answer_json, "similarity": 1.0}
        for e in entries
    ]


def _require_internal(x_internal_secret: str = Header(default="")):
    """Guard for /internal/* cron targets. The service is GCP-IAM-open so the browser SPA can
    reach the Firebase-authed routes; the internal cron routes are protected here by a shared
    secret (INTERNAL_SECRET env, set on the scheduler headers). Denies if unset/mismatched."""
    import hmac
    import os
    expected = os.getenv("INTERNAL_SECRET", "")
    if not expected or not hmac.compare_digest(x_internal_secret or "", expected):
        raise HTTPException(status_code=403, detail="forbidden")


@app.post("/internal/promote", dependencies=[Depends(_require_internal)])
def promote():
    """Cloud Scheduler target (guarded by INTERNAL_SECRET). Promotes due scheduled_content."""
    from jobs.promote_job import run
    return run()


@app.post("/internal/social", dependencies=[Depends(_require_internal)])
def social():
    """Cloud Scheduler target (guarded by INTERNAL_SECRET). Publishes awaiting_social reels."""
    from jobs.social_job import run
    return run()


@app.post("/internal/crawl-comments", dependencies=[Depends(_require_internal)])
def crawl_comments_cron():
    """Cloud Scheduler target (guarded by INTERNAL_SECRET). Crawls YouTube comments for a
    bounded batch of the least-recently-crawled videos and drafts replies — the cron rotates
    through the whole catalog over successive runs (see jobs/crawl_comments rotation).

    Bounded (50 videos / 25 drafts) and INTERNAL_SECRET-gated (not user-reachable); the upsert
    is race-safe (per-comment SAVEPOINT) so an overlapping run can't corrupt the batch.

    Limit raised from 15→50 videos per run: at every-2h cadence (12 runs/day) and 841 videos
    this covers the full catalog in ~1.4 days vs the prior ~2.8 days, ensuring KPIs stay fresh."""
    from jobs.crawl_comments import run
    return run(limit=50, max_drafts=25)


@app.get("/internal/tenants")
def internal_tenants(audit=Depends(require_internal_tenants)):
    """Platform-admin tenant listing (F4b stub — full management API is F6 scope).
    Gated by require_internal_tenants: verified EXACT platform_admin claim (H6 —
    admin '*' does not satisfy it) + optional X-Tenant-ID impersonation (audited).
    Uses PlatformSessionLocal directly (a plain context manager) — NOT the
    get_platform_db_session FastAPI dependency, which is a generator and would
    raise on `with ... as db` (architect H5)."""
    from app.models import PlatformSessionLocal, Tenant, TenantDefaultAdmin
    with PlatformSessionLocal() as db:
        db.info["platform_scope"] = True
        rows = db.query(Tenant).order_by(Tenant.id).all()
        out = []
        for t in rows:
            admin = (db.query(TenantDefaultAdmin)
                     .filter(TenantDefaultAdmin.tenant_id == t.id)
                     .first())
            out.append({
                "id": t.id, "name": t.name, "slug": t.slug, "status": t.status,
                "admin_email": (admin.email if admin else None),
                "created_at": (t.created_at.isoformat() if t.created_at else None),
                "mau": None,  # populated once GCIP usage metering lands (F6+)
            })
        return out


def _gcip_tenant_id_for(db, tenant_id: int) -> str | None:
    """Look up the GCIP tenant id for a platform tenant_id via tenant_gcip_map."""
    from app.models import TenantGcipMap
    row = (db.query(TenantGcipMap)
           .filter(TenantGcipMap.tenant_id == tenant_id)
           .first())
    return row.gcip_tenant if row else None


@app.post("/internal/tenants", status_code=201)
def provision_tenant_route(body: dict, audit=Depends(require_internal_tenants)):
    """platform_admin: provision a new tenant end-to-end (DB row + GCIP tenant +
    seed configs + invite). F6 §3.2. GCIP tenant creation is a live Admin SDK call;
    tests mock core.provision.provision_tenant."""
    import adapters.gcip as gcip_client
    import core.provision as provision
    from app.models import PlatformSessionLocal
    name, slug, admin_email = body.get("name"), body.get("slug"), body.get("admin_email")
    if not (name and slug and admin_email):
        raise HTTPException(422, "name, slug, admin_email required")
    with PlatformSessionLocal() as db:
        db.info["platform_scope"] = True
        try:
            result = provision.provision_tenant(name, slug, admin_email, db, gcip_client)
            db.commit()
            return {"id": result["tenant_id"], "status": "active",
                    "invite_link": result.get("invite_link")}
        except provision.SlugConflictError as e:
            db.rollback()
            raise HTTPException(409, f"slug '{slug}' already exists") from e
        except provision.ProvisioningError as e:
            # Persist the 'provisioning_failed' status + error so the status
            # endpoint can surface it; provision_tenant wrote them before raising.
            db.commit()
            raise HTTPException(500, f"provisioning failed: {e}") from e


@app.get("/internal/tenants/{tenant_id}/status")
def tenant_status_route(tenant_id: int, audit=Depends(require_internal_tenants)):
    from app.models import PlatformSessionLocal, Tenant
    with PlatformSessionLocal() as db:
        db.info["platform_scope"] = True
        t = db.get(Tenant, tenant_id)
        if t is None:
            raise HTTPException(404, "tenant not found")
        return {"status": t.status,
                "error": (t.settings or {}).get("provisioning_error")}


@app.delete("/internal/tenants/{tenant_id}")
def offboard_tenant_route(tenant_id: int, audit=Depends(require_internal_tenants)):
    """platform_admin: offboard a tenant (RLS-scoped cascade + GCS delete + audit).
    Delegates to core.offboard.offboard_tenant (tenant 1 is protected)."""
    import os

    import adapters.gcip as gcip_client
    import core.offboard as offboard
    from app.models import PlatformSessionLocal
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    with PlatformSessionLocal() as db:
        db.info["platform_scope"] = True
        gcs_client = None
        try:
            from google.cloud import storage  # noqa: PLC0415
            gcs_client = storage.Client()
        except Exception:  # noqa: BLE001 — GCS optional in non-prod/test
            pass
        try:
            offboard.offboard_tenant(tenant_id, audit.get("email", "platform_admin"),
                                     db, gcs_client, f"{project}-media",
                                     gcip_client=gcip_client)
            db.commit()
        except offboard.ProtectedTenantError as e:
            db.rollback()
            raise HTTPException(409, "tenant 1 (Perkins) is protected") from e
        except ValueError as e:
            db.rollback()
            raise HTTPException(404, str(e)) from e
    return {"ok": True, "status": "offboarded"}


@app.post("/internal/tenants/{tenant_id}/resend-invite")
def resend_invite_route(tenant_id: int, audit=Depends(require_internal_tenants)):
    import adapters.gcip as gcip_client
    import core.provision as provision
    from app.models import PlatformSessionLocal, Tenant, TenantDefaultAdmin
    with PlatformSessionLocal() as db:
        db.info["platform_scope"] = True
        t = db.get(Tenant, tenant_id)
        if t is None:
            raise HTTPException(404, "tenant not found")
        gcip_id = _gcip_tenant_id_for(db, tenant_id)
        admin = (db.query(TenantDefaultAdmin)
                 .filter(TenantDefaultAdmin.tenant_id == tenant_id).first())
        if gcip_id is None or admin is None:
            raise HTTPException(404, "tenant has no GCIP tenant / admin to invite")
        link = provision.resend_invite(gcip_id, admin.email, gcip_client)
    return {"invite_link": link}


# ── F6: per-tenant SSO (GCIP SAML/OIDC IdP config for the caller's own tenant) ──

@app.get("/admin/sso/providers")
def list_sso_route(claims=Depends(require_role_db("manage_sso"))):
    import adapters.gcip as gcip_client
    import core.provision as provision
    from app.models import PlatformSessionLocal
    with PlatformSessionLocal() as db:
        db.info["platform_scope"] = True
        gcip_id = _gcip_tenant_id_for(db, claims.get("tenant_id") or 1)
    if gcip_id is None:
        return []  # tenant 1 (Perkins) uses the project-level pool; no per-tenant IdPs
    return provision.list_sso_providers(gcip_id, gcip_client)


@app.post("/admin/sso/providers", status_code=201)
def add_sso_route(body: dict, claims=Depends(require_role_db("manage_sso"))):
    import adapters.gcip as gcip_client
    import core.provision as provision
    from app.models import PlatformSessionLocal
    tenant_id = claims.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "no tenant context")
    with PlatformSessionLocal() as db:
        db.info["platform_scope"] = True
        gcip_id = _gcip_tenant_id_for(db, tenant_id)
    if gcip_id is None:
        raise HTTPException(404, "no GCIP tenant for the caller's tenant")
    provider_type = body.get("type")
    try:
        return provision.add_sso_provider(gcip_id, provider_type, body, gcip_client)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.delete("/admin/sso/providers/{idp_id}")
def delete_sso_route(idp_id: str, claims=Depends(require_role_db("manage_sso"))):
    import adapters.gcip as gcip_client
    import core.provision as provision
    from app.models import PlatformSessionLocal
    tenant_id = claims.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "no tenant context")
    with PlatformSessionLocal() as db:
        db.info["platform_scope"] = True
        gcip_id = _gcip_tenant_id_for(db, tenant_id)
    if gcip_id is None:
        raise HTTPException(404, "no GCIP tenant for the caller's tenant")
    try:
        provision.remove_sso_provider(gcip_id, idp_id, gcip_client)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"ok": True}


@app.post("/internal/proposal-reminders", dependencies=[Depends(_require_internal)])
def proposal_reminders_cron():
    """Cloud Scheduler target (guarded by INTERNAL_SECRET). Sends due proposal reminder
    nudges per tenant cadence (jobs/proposal_reminders — SKIP LOCKED, idempotent).
    Scheduled daily 09:00 UTC via infra/gotenberg.tf."""
    from jobs.proposal_reminders import run
    return run()


@app.post("/internal/poll-archive-kpis", dependencies=[Depends(_require_internal)])
def poll_archive_kpis_cron():
    """Cloud Scheduler target (guarded by INTERNAL_SECRET). Polls YouTube KPIs
    (views/likes/comment_count/kpis_polled_at) for all archived videos once daily.

    Complements crawl_comments (which only refreshes KPIs for the rotated batch).
    This endpoint ensures every archived video gets a KPI update every 24 h regardless
    of comment-crawl rotation position. Scheduled daily at 02:00 Chicago time."""
    from jobs.poll_archive_kpis import run
    return run()


@app.get("/status")
def status(_claims=Depends(require_role("view_status")), s: Session = Depends(get_db_session)):
    """Admin observability (Req 6): corpus + pipeline + content counts, last errors,
    scheduled-content breakdown (articles vs social by platform), and action counters.
    Uses the RLS-stamped session so all counts are the caller's tenant."""
    from sqlalchemy import func

    from app.models import Article, Chunk, FaqEntry, IngestionRun, ScheduledContent, Video
    from core.status import action_counters, scheduled_breakdown
    errors = [
        {
            "video_id": r.video_id,
            "stage": r.stage,
            "error": (r.last_error or "")[:200],
            "title": (v.title if v else None),
            "youtube_url": (v.url if v and v.url else f"https://youtu.be/{r.video_id}"),
        }
        for r, v in (
            s.query(IngestionRun, Video)
            .outerjoin(Video, Video.id == IngestionRun.video_id)
            .filter(IngestionRun.status == "error")
            .limit(20)
        )
    ]
    queue = [
        {
            "video_id": r.video_id,
            "title": (v.title if v else None),
            "stage": r.stage,
            "status": r.status,
        }
        for r, v in (
            s.query(IngestionRun, Video)
            .outerjoin(Video, Video.id == IngestionRun.video_id)
            .filter(IngestionRun.status.in_(["pending", "running"]))
            .order_by(IngestionRun.updated_at.desc())
            .limit(50)
        )
    ]
    breakdown = scheduled_breakdown(s)
    counters = action_counters(s)
    return {
        "videos": s.query(func.count(Video.id)).scalar(),
        "videos_embedded": s.query(func.count(func.distinct(Chunk.video_id))).scalar(),
        "videos_archived": s.query(func.count(Video.id)).filter(Video.archive_uri.isnot(None)).scalar(),
        "transcripts_done": s.query(func.count(IngestionRun.id)).filter(
            IngestionRun.stage == "transcript", IngestionRun.status == "done").scalar(),
        "articles": s.query(func.count(Article.slug)).scalar(),
        "faq_count": s.query(func.count(FaqEntry.id)).scalar(),
        # Active scheduled rows only (published/error/awaiting_social are history/state, not
        # upcoming content). Keep this consistent with scheduled_breakdown().
        "scheduled_content": (
            s.query(func.count(ScheduledContent.id))
            .filter(ScheduledContent.status == "scheduled")
            .scalar()
        ),
        # Scheduled-content split: articles vs social posts grouped by platform
        "scheduled_breakdown": breakdown,
        # Action counters: items needing attention
        "content_opportunities": counters["content_opportunities"],
        "comments_pending": counters["comments_pending"],
        "videos_pending": counters["videos_pending"],
        "failed_stages": errors,
        "queue": queue,
    }


class RetryRequest(BaseModel):
    video_id: str
    stage: str


@app.post("/status/retry")
def status_retry(body: RetryRequest, _claims=Depends(require_role("view_status")),
                 s: Session = Depends(get_db_session)):
    """Reset a failed IngestionRun back to pending so the next ingest run reprocesses it.

    Finds all IngestionRun rows matching video_id + stage with status='error',
    clears last_error, and sets status='pending'. Returns {reset: <count>}.
    404 if no matching error row exists. RLS-stamped session (caller's tenant).
    """
    from app.models import IngestionRun

    rows = (
        s.query(IngestionRun)
        .filter(
            IngestionRun.video_id == body.video_id,
            IngestionRun.stage == body.stage,
            IngestionRun.status == "error",
        )
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No failed stage found for that video_id + stage")
    for row in rows:
        row.status = "pending"
        row.last_error = None
    s.flush()

    return {"reset": len(rows)}
