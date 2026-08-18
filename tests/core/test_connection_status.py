from app.models import IntegrationStatus
from core import connection_status as CS


def test_mark_healthy_writes_row(monkeypatch):
    seen = []
    row = type("R", (), {
        "status": "broken",
        "last_ok": None,
        "last_checked": None,
        "last_error": "Knowify MCP token expired",
        "consecutive_failures": 3,
    })()

    class _Q:
        def filter(self, *a, **k):
            return self

        def first(self):
            return row

    class _Db:
        info = {}

        def query(self, *a):
            return _Q()

        def add(self, _row):
            seen.append("add")

        def commit(self):
            seen.append("commit")

        def close(self):
            seen.append("close")

    monkeypatch.setattr("app.models.PlatformSessionLocal", lambda: _Db())
    CS.mark_healthy("knowify")
    assert row.status == "healthy"
    assert row.last_error is None
    assert row.consecutive_failures == 0
    assert "commit" in seen
    assert "close" in seen


def test_mark_healthy_swallows_db_errors(monkeypatch):
    monkeypatch.setattr(
        CS, "_write", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    CS.mark_healthy("knowify")


def test_mark_healthy_creates_missing_row(monkeypatch):
    added = []

    class _Q:
        def filter(self, *a, **k):
            return self

        def first(self):
            return None

    class _Db:
        info = {}

        def query(self, *a):
            return _Q()

        def add(self, row):
            added.append(row)
            return None

        def commit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr("app.models.PlatformSessionLocal", lambda: _Db())
    monkeypatch.setattr("app.models.IntegrationStatus", IntegrationStatus)
    CS.mark_healthy("youtube_reply", tenant_id=1)
    assert added and added[0].status == "healthy"
    assert added[0].last_error is None
    assert added[0].consecutive_failures == 0
