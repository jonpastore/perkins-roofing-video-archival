from core.invite_email import build_invite_email


def _build(**over):
    kw = dict(
        recipient_name="Vlad",
        role="admin",
        sign_in_url="https://app.perkinsroofing.net",
    )
    kw.update(over)
    return build_invite_email(**kw)


def test_returns_subject_and_full_html_document():
    subject, html = _build()
    assert "Perkins Roofing" in subject
    # Wrapped via the shared branded email template (full document).
    assert html.startswith("<!DOCTYPE html>")


def test_logo_rendered_on_white_header():
    _, html = _build()
    # Logo image present, and the header band is white (dark wordmark needs it).
    assert 'src="https://app.perkinsroofing.net/perkins-logo.png"' in html
    assert "background-color:#ffffff" in html


def test_logo_url_overridable():
    _, html = _build(logo_url="https://cdn.example.com/acme.png")
    assert 'src="https://cdn.example.com/acme.png"' in html


def test_includes_signin_url_in_button_and_fallback():
    _, html = _build(sign_in_url="https://app.perkinsroofing.net/go")
    # Appears in the CTA button href AND the paste-able fallback link.
    assert html.count("https://app.perkinsroofing.net/go") >= 2
    assert "Sign In to Perkins Roofing" in html


def test_role_is_shown_with_friendly_label():
    _, html = _build(role="web_admin")
    assert "Web Administrator" in html
    _, html2 = _build(role="admin")
    assert "Administrator" in html2


def test_unknown_role_falls_back_to_titlecased():
    _, html = _build(role="field_manager")
    assert "Field Manager" in html


def test_recipient_name_is_html_escaped():
    _, html = _build(recipient_name="<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_greeting_generic_when_no_name():
    _, html = _build(recipient_name=None)
    assert "Hello," in html


def test_inviter_name_included_and_escaped_when_present():
    _, html = _build(inviter_name="Jon <boss>")
    assert "Jon &lt;boss&gt; has added you" in html
    assert "Jon <boss>" not in html


def test_generic_added_line_when_no_inviter():
    _, html = _build(inviter_name=None)
    assert "You've been added" in html


def test_company_name_customizable():
    subject, html = _build(company_name="Acme Roofing")
    assert "Acme Roofing" in subject
    assert "Acme Roofing" in html
