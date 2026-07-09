"""Drip-publish engine (Track D) — Cloud Scheduler target or run directly.

Drains due/ready articles from Postgres using SELECT … FOR UPDATE SKIP LOCKED so
concurrent runs cannot double-publish. Publishes pillar before its supports, up to
`target` articles per run (drip rate = target per scheduler tick; publishing is
synchronous so there is no cross-tick in-flight state). Activates the next cluster's
pillar when the active cluster completes. Commits per-row so one failure never rolls
back prior successes (same contract as promote_job.py).

NO Redis — Postgres queue only (D4).

Run: .venv/bin/python -m jobs.publish_job
"""
from __future__ import annotations

from datetime import datetime, timezone

import adapters.wordpress as wordpress
from adapters.safety import run_gate
from app.models import Article, Cluster, SessionLocal
from core.publish_planner import next_cluster, publish_order

# How many articles to keep in-flight at once.  Configurable via env if needed.
_TARGET_IN_FLIGHT = 5


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _run_for_tenant(db, tenant_id: int, target: int = _TARGET_IN_FLIGHT, now: datetime | None = None) -> dict[str, int]:
    """Per-tenant publish body. Called by for_each_tenant via run()."""
    now = now or _utcnow()
    published = blocked = errored = 0

    candidates = (
        db.query(Article)
        .filter(
            Article.status.in_(["ready", "scheduled"]),
            Article.scheduled_at <= now,
        )
        .with_for_update(skip_locked=True)
        .order_by(Article.cluster_id.nullslast(), Article.priority.nullslast())
        .all()
    )

    if not candidates:
        return {"published": 0, "blocked": 0, "errored": 0}

    cluster_groups: dict[int | None, list[dict]] = {}
    for a in candidates:
        cluster_groups.setdefault(a.cluster_id, []).append(
            {"_orm": a, "slug": a.slug, "role": a.role or "support",
             "priority": a.priority, "cluster_id": a.cluster_id}
        )

    dispatch_queue: list[Article] = []
    for cid, group in cluster_groups.items():
        ordered = publish_order(group)
        dispatch_queue.extend(item["_orm"] for item in ordered)

    to_publish = dispatch_queue[:max(0, target)]

    for article in to_publish:
        try:
            text = article.content_md or ""
            gate_result = run_gate(text, "article")
            if not gate_result.passed:
                article.status = "blocked"
                db.add(article)
                db.commit()
                blocked += 1
                print(
                    f"[publish] BLOCKED {article.slug}: gate failed — "
                    f"{gate_result.reason[:120] if gate_result.reason else 'no reason'}"
                )
                continue

            if article.wp_post_id:
                wordpress.update_status(article.wp_post_id, "publish")

            article.status = "published"
            db.add(article)
            db.commit()
            published += 1
            print(f"[publish] published {article.slug} (cluster={article.cluster_id})")

        except Exception as e:  # noqa: BLE001
            db.rollback()
            article.status = "error"
            db.add(article)
            db.commit()
            errored += 1
            print(f"[error] publish {article.slug}: {str(e)[:120]}")

    _maybe_activate_next_cluster(db, now)
    return {"published": published, "blocked": blocked, "errored": errored}


def run(target: int = _TARGET_IN_FLIGHT, now: datetime | None = None) -> dict[str, int]:
    """Iterate active tenants and drain due articles for each."""
    from core.tenant_loop import for_each_tenant  # noqa: PLC0415

    totals: dict = {"published": 0, "blocked": 0, "errored": 0}

    def _fn(db, tenant_id: int) -> None:
        r = _run_for_tenant(db, tenant_id, target=target, now=now)
        for k in totals:
            totals[k] += r.get(k, 0)

    for_each_tenant(SessionLocal, _fn)
    return totals


def _maybe_activate_next_cluster(s, now: datetime) -> None:
    """If the active cluster is complete, activate the next pending cluster's pillar."""
    active_clusters = s.query(Cluster).filter(Cluster.status == "active").all()
    for cluster in active_clusters:
        # A cluster is complete when all its articles are published (or blocked/error)
        remaining = (
            s.query(Article)
            .filter(
                Article.cluster_id == cluster.id,
                Article.status.notin_(["published", "blocked", "error"]),
            )
            .count()
        )
        if remaining == 0:
            # Mark this cluster complete
            cluster.status = "complete"
            s.add(cluster)
            s.commit()
            print(f"[publish] cluster {cluster.id} ({cluster.pillar_topic!r}) complete")

            # Find and activate the next pending cluster
            all_clusters = s.query(Cluster).all()
            nxt = next_cluster([
                {"id": c.id, "status": c.status, "position": c.position}
                for c in all_clusters
            ])
            if nxt:
                nxt_orm = s.get(Cluster, nxt["id"])
                nxt_orm.status = "active"
                s.add(nxt_orm)

                # Schedule the pillar article of the newly active cluster immediately
                pillar = (
                    s.query(Article)
                    .filter(
                        Article.cluster_id == nxt_orm.id,
                        Article.role == "pillar",
                        Article.status == "ready",
                    )
                    .first()
                )
                if pillar:
                    pillar.scheduled_at = now
                    s.add(pillar)

                s.commit()
                print(
                    f"[publish] activated cluster {nxt_orm.id} "
                    f"({nxt_orm.pillar_topic!r}) at position {nxt_orm.position}"
                )


if __name__ == "__main__":
    print(run())
