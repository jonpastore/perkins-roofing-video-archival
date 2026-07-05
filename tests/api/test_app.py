from fastapi.testclient import TestClient

from api import app as appmod
from api.auth import set_verifier
from app import retrieval as R


def test_healthz_open():
    assert TestClient(appmod.app).get("/healthz").json() == {"ok": True}


def test_search_requires_auth():
    assert TestClient(appmod.app).post("/search", json={"query": "x"}).status_code == 401


def test_search_with_sales_token(monkeypatch):
    set_verifier(lambda t: {"uid": "u", "email": "e", "role": "sales"})
    monkeypatch.setattr(R, "search", lambda q, k=8: [{"ok": 1}])
    r = TestClient(appmod.app).post("/search", json={"query": "roof"},
                                    headers={"Authorization": "Bearer x"})
    assert r.status_code == 200 and r.json() == [{"ok": 1}]


def test_promote_calls_promoter(monkeypatch):
    # the Cloud Scheduler target must exist (not 404) and invoke the promoter
    import jobs.promote_job as pj
    monkeypatch.setattr(pj, "run", lambda: {"promoted": 3, "errored": 0})
    r = TestClient(appmod.app).post("/internal/promote")
    assert r.status_code == 200 and r.json()["promoted"] == 3


def test_social_calls_social_job(monkeypatch):
    # the Cloud Scheduler social target must exist and invoke social_job.run
    import jobs.social_job as sj
    monkeypatch.setattr(sj, "run", lambda: {"published": 2, "skipped": 0, "errored": 0})
    r = TestClient(appmod.app).post("/internal/social")
    assert r.status_code == 200 and r.json()["published"] == 2
