"""v2 FastAPI serving surface — auth-gated (Firebase ID token + core.authz role matrix).
This is the PROD entrypoint (replaces the unauthenticated app/api.py). Search/ask require an
authenticated sales|admin caller; /internal/promote is the Cloud Scheduler target, protected
at the Cloud Run IAM layer (scheduler-sa OIDC, run.invoker)."""
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.auth import current_claims, require_internal_tenants, require_role, require_role_db
from api.routes.archive import router as archive_router
from api.routes.articles import router as articles_router
from api.routes.clips import router as clips_router
from api.routes.comments import router as comments_router
from api.routes.config import router as config_router
from api.routes.customers import router as customers_router
from api.routes.email import router as email_router
from api.routes.estimator import router as estimator_router
from api.routes.faq import router as faq_router
from api.routes.logs import router as logs_router
from api.routes.measurements import router as measurements_router
from api.routes.pricing_configs import router as pricing_configs_router
from api.routes.proposals import router as proposals_router
from api.routes.scheduling import router as scheduling_router
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
    """H2 fail-open guard: RLS is a silent no-op if the app DB role is SUPERUSER/
    BYPASSRLS. Log CRITICAL if so — do NOT hard-refuse yet: the ALTER ROLE
    NOSUPERUSER NOBYPASSRLS in migration 0018 is Jon-applied and still pending.
    Flip refuse_to_serve=True once it lands, before tenant #2. No-op on SQLite."""
    try:
        from app.models import engine
        from core.tenant import assert_rls_enforceable
        assert_rls_enforceable(engine, refuse_to_serve=False)
    except Exception:  # noqa: BLE001 — an advisory guard must never block startup
        import logging
        logging.getLogger(__name__).warning("RLS enforceability check skipped", exc_info=True)


app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.CORS_ORIGINS),
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)


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
app.include_router(measurements_router)
app.include_router(faq_router)
app.include_router(config_router)
app.include_router(users_router)
app.include_router(me_router)
app.include_router(suggestions_router)
app.include_router(clips_router)
app.include_router(comments_router)
app.include_router(logs_router)
app.include_router(customers_router)
app.include_router(proposals_router)


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


@app.get("/admin/tenant/settings")
def get_tenant_settings(claims=Depends(require_role_db("marketing_articles"))):
    from core.tenant_settings import TenantSettings
    raw = _tenant_settings_read(claims.get("tenant_id") or 1)
    return TenantSettings.load(raw).model_dump()


@app.put("/admin/tenant/settings/marketing")
def put_marketing_settings(body: dict, claims=Depends(require_role_db("marketing_articles"))):
    # social_accounts is read-only via this path (OAuth tokens live in Secret Manager).
    body.pop("social_accounts", None)
    merged = _tenant_settings_merge(claims.get("tenant_id") or 1, "marketing", body)
    return {"marketing": merged.get("marketing", {})}


@app.put("/admin/tenant/settings/kb")
def put_kb_settings(body: dict, claims=Depends(require_role_db("kb_archive_manage"))):
    merged = _tenant_settings_merge(claims.get("tenant_id") or 1, "kb", body)
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
    url = brand_upload_signed_url(
        claims.get("tenant_id") or 1, asset_name, content_type,
        storage.Client(), f"{project}-media",
    )
    gcs_uri = f"gs://{project}-media/tenants/{claims.get('tenant_id') or 1}/brand/{asset_name}"
    return {"upload_url": url, "gcs_uri": gcs_uri}


@app.post("/search")
def search(q: Query, _claims=Depends(require_role("search"))):
    return R.search(q.query, q.k)


@app.post("/ask")
def ask(q: Query, _claims=Depends(require_role("ask"))):
    return A.ask(q.query, q.k)


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
def list_sso_route(claims=Depends(require_role_db("admin_users"))):
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
def add_sso_route(body: dict, claims=Depends(require_role_db("admin_users"))):
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
def delete_sso_route(idp_id: str, claims=Depends(require_role_db("admin_users"))):
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
    from jobs.proposal_reminders import run_reminders
    return run_reminders()


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
def status(_claims=Depends(require_role("view_status"))):
    """Admin observability (Req 6): corpus + pipeline + content counts, last errors,
    scheduled-content breakdown (articles vs social by platform), and action counters."""
    from sqlalchemy import func

    from app.models import Article, Chunk, FaqEntry, IngestionRun, ScheduledContent, SessionLocal, Video
    from core.status import action_counters, scheduled_breakdown
    s = SessionLocal()
    try:
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
            "scheduled_content": s.query(func.count(ScheduledContent.id)).scalar(),
            # Scheduled-content split: articles vs social posts grouped by platform
            "scheduled_breakdown": breakdown,
            # Action counters: items needing attention
            "content_opportunities": counters["content_opportunities"],
            "comments_pending": counters["comments_pending"],
            "videos_pending": counters["videos_pending"],
            "failed_stages": errors,
            "queue": queue,
        }
    finally:
        s.close()


class RetryRequest(BaseModel):
    video_id: str
    stage: str


@app.post("/status/retry")
def status_retry(body: RetryRequest, _claims=Depends(require_role("view_status"))):
    """Reset a failed IngestionRun back to pending so the next ingest run reprocesses it.

    Finds all IngestionRun rows matching video_id + stage with status='error',
    clears last_error, and sets status='pending'. Returns {reset: <count>}.
    404 if no matching error row exists.
    """
    from app.models import IngestionRun, SessionLocal

    with SessionLocal() as s:
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
        s.commit()

    return {"reset": len(rows)}
