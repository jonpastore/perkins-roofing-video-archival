from core import content_cadence as cc
from core.content_cadence import should_stop_dump


def test_stop_dump_at_configured_fraction():
    assert should_stop_dump(generated=50, potential=100, fraction=0.5) is True
    assert should_stop_dump(generated=49, potential=100, fraction=0.5) is False


def test_stop_dump_empty_potential():
    assert should_stop_dump(generated=0, potential=0, fraction=0.5) is True


def test_read_mode_int_float_from_env(monkeypatch):
    monkeypatch.setattr(cc, "_read_raw", lambda key: {
        "CONTENT_GEN_MODE": "dump",
        "CONTENT_DUMP_PER_RUN": "3",
        "CONTENT_TARGET_FRACTION": "0.25",
        "CONTENT_DUMP_CLUSTERS": "nope",
        "CONTENT_FRESHNESS_PER_DAY": None,
        "CONTENT_FRESHNESS_BUDGET": "-1",
    }.get(key))
    assert cc.read_mode() == "dump"
    assert cc.read_int("CONTENT_DUMP_PER_RUN", 10) == 3
    assert cc.read_int("CONTENT_DUMP_CLUSTERS", 2) == 2
    assert cc.read_int("CONTENT_FRESHNESS_PER_DAY", 1) == 1
    assert cc.read_int("CONTENT_FRESHNESS_BUDGET", 10) == 0
    assert cc.read_float("CONTENT_TARGET_FRACTION", 0.5) == 0.25


def test_read_mode_unknown_falls_back(monkeypatch):
    monkeypatch.setattr(cc, "_read_raw", lambda key: "nope")
    assert cc.read_mode() == "off"
    monkeypatch.setattr(cc, "_read_raw", lambda key: "freshness")
    assert cc.read_mode() == "off"
    monkeypatch.setattr(cc, "_read_raw", lambda key: "1.5")
    assert cc.read_float("CONTENT_TARGET_FRACTION", 0.5) == 1.0
    monkeypatch.setattr(cc, "_read_raw", lambda key: "not-a-float")
    assert cc.read_float("CONTENT_TARGET_FRACTION", 0.5) == 0.5


def test_cadence_enabled_when_dump(monkeypatch):
    monkeypatch.setattr(cc, "_read_raw", lambda key: "dump" if key == "CONTENT_GEN_MODE" else None)
    got = cc.cadence()
    assert got["mode"] == "dump" and got["enabled"] is True


def test_read_raw_falls_back_to_env_when_db_blows(monkeypatch):
    def _boom():
        raise RuntimeError("no db")
    monkeypatch.setattr("app.models.PlatformSessionLocal", _boom, raising=False)
    # Import path inside _read_raw — force the except by breaking the import target
    import app.models as models
    monkeypatch.setattr(models, "PlatformSessionLocal", _boom)
    monkeypatch.setenv("CONTENT_GEN_MODE", "  freshness  ")
    assert cc._read_raw("CONTENT_GEN_MODE") == "freshness"
    monkeypatch.delenv("CONTENT_GEN_MODE")
    assert cc._read_raw("CONTENT_GEN_MODE") is None


def test_read_raw_prefers_platform_config(monkeypatch):
    class _Row:
        value = "dump"

    class _DB:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        info = {}
        def get(self, _cls, key):
            return _Row() if key == "CONTENT_GEN_MODE" else None

    monkeypatch.setattr("app.models.PlatformSessionLocal", lambda: _DB())
    monkeypatch.setattr("app.models.PlatformConfig", object)
    assert cc._read_raw("CONTENT_GEN_MODE") == "dump"
