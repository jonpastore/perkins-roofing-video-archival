"""GCP spend helper — miss paths must not raise."""
from __future__ import annotations

import json
from urllib.error import HTTPError

from core import cloud_spend


class _Resp:
    def __init__(self, raw: bytes):
        self._raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._raw


def test_fetch_cloud_spend_import_error(monkeypatch):
    def _boom():
        raise ImportError("no")

    monkeypatch.setattr(cloud_spend, "_adc_token", _boom)
    out = cloud_spend.fetch_cloud_spend()
    assert out["ok"] is False
    assert "google-auth" in out["error"]


def test_fetch_cloud_spend_http_403(monkeypatch):
    monkeypatch.setattr(cloud_spend, "_adc_token", lambda: "t")

    def _boom(req, timeout=12):
        raise HTTPError(req.full_url, 403, "forbidden", hdrs=None, fp=None)

    monkeypatch.setattr(cloud_spend.urllib.request, "urlopen", _boom)
    out = cloud_spend.fetch_cloud_spend()
    assert out["ok"] is False
    assert "403" in out["error"]
    assert "billing.budgets.viewer" in out["hint"]


def test_fetch_cloud_spend_parses_budget(monkeypatch):
    monkeypatch.setattr(cloud_spend, "_adc_token", lambda: "t")
    payload = {
        "budgets": [{
            "displayName": "monthly cap",
            "amount": {"specifiedAmount": {"units": "250", "currencyCode": "USD"}},
        }],
    }
    monkeypatch.setattr(
        cloud_spend.urllib.request, "urlopen",
        lambda *a, **k: _Resp(json.dumps(payload).encode()),
    )
    out = cloud_spend.fetch_cloud_spend()
    assert out["ok"] is True
    assert out["amount"] == 250
    assert out["display_name"] == "monthly cap"


def test_fetch_cloud_spend_empty_budgets(monkeypatch):
    monkeypatch.setattr(cloud_spend, "_adc_token", lambda: "t")
    monkeypatch.setattr(
        cloud_spend.urllib.request, "urlopen",
        lambda *a, **k: _Resp(b"{}"),
    )
    out = cloud_spend.fetch_cloud_spend()
    assert out["ok"] is True
    assert out["amount"] is None
    assert "no budgets" in out["note"]


def test_fetch_cloud_spend_adc_fail(monkeypatch):
    def _fail():
        raise RuntimeError("no adc")

    monkeypatch.setattr(cloud_spend, "_adc_token", _fail)
    out = cloud_spend.fetch_cloud_spend()
    assert out["ok"] is False
    assert "adc" in out["error"]


def test_fetch_cloud_spend_urlopen_fail(monkeypatch):
    monkeypatch.setattr(cloud_spend, "_adc_token", lambda: "t")

    def _fail(*a, **k):
        raise TimeoutError("timeout")

    monkeypatch.setattr(cloud_spend.urllib.request, "urlopen", _fail)
    out = cloud_spend.fetch_cloud_spend()
    assert out["ok"] is False
    assert "timeout" in out["error"]


def test_fetch_cloud_spend_bad_units(monkeypatch):
    monkeypatch.setattr(cloud_spend, "_adc_token", lambda: "t")
    payload = {"budgets": [{"amount": {"specifiedAmount": {"units": "x"}}}]}
    monkeypatch.setattr(
        cloud_spend.urllib.request, "urlopen",
        lambda *a, **k: _Resp(json.dumps(payload).encode()),
    )
    out = cloud_spend.fetch_cloud_spend()
    assert out["ok"] is True
    assert out["amount"] is None


def test_adc_token_refreshes(monkeypatch):
    class _Creds:
        token = "abc"

        def refresh(self, _req):
            self.token = "xyz"

    import google.auth
    import google.auth.transport.requests

    monkeypatch.setattr(google.auth, "default", lambda scopes=None: (_Creds(), None))
    monkeypatch.setattr(google.auth.transport.requests, "Request", lambda: None)
    assert cloud_spend._adc_token() == "xyz"
