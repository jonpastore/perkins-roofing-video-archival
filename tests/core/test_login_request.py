from core.login_request import LOGIN_COPY, login_email_html, send_login_request


def test_login_email_names_knowify_and_the_dashboard():
    subject, html = login_email_html("knowify")
    assert "Knowify" in subject
    assert "Data sources" in html
    assert "video-archival-and-content-gen.web.app" in html


def test_companycam_is_not_a_login_integration():
    assert "companycam" not in LOGIN_COPY


def test_send_login_request_skips_gated_and_sends_allowed(monkeypatch):
    sent = []

    class _Dec:
        def __init__(self, allowed):
            self.allowed = allowed

    monkeypatch.setattr("core.email_gate.decide", lambda to: _Dec(to.endswith("degenito.ai")))
    monkeypatch.setattr("adapters.resend.send", lambda **kw: sent.append(kw) or "id-1")
    ids = send_login_request("knowify", tenant_id=1)
    assert ids == ["id-1"]
    assert sent[0]["to"] == "jon@degenito.ai"
    assert sent[0]["send_type"] == "login_request"
    assert sent[0]["metadata"]["integration"] == "knowify"
