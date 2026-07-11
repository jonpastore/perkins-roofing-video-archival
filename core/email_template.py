"""Pure HTML email wrapper builder (no I/O, 100% coverage required).

Builds a full email-safe HTML document from a TinyMCE-produced body fragment,
an optional branded header HTML block, and brand tokens. All layout uses a
single 600px table with inline CSS — email clients strip <style> blocks
unevenly, so no class-based styling is used anywhere.
"""

from __future__ import annotations


def wrap_email(
    body_html: str,
    header_html: str = "",
    company_name: str = "Perkins Roofing",
    brand_navy: str = "#1b2a52",
    brand_red: str = "#ef3c1a",
    font_family: str = "system-ui, 'Segoe UI', Roboto, Arial, sans-serif",
    header_bg: str = "",
) -> str:
    """Return a complete, email-safe HTML document wrapping *body_html*.

    Args:
        body_html:    The composed email body (HTML fragment from TinyMCE).
        header_html:  Optional platform header HTML block (e.g. logo banner).
                      When empty the header band still renders with company_name.
        company_name: Display name used in the header band and footer.
        brand_navy:   Hex colour for the header background band.
        brand_red:    Hex colour for the footer accent line.
        font_family:  CSS font-family stack for body text.
        header_bg:    Header band background colour. Defaults to ``brand_navy``.
                      Pass a light colour (e.g. ``#ffffff``) when the header holds a
                      dark logo. A thin bottom rule keeps the band separated from the
                      body on light backgrounds (invisible on the navy default).

    Returns:
        A self-contained HTML string suitable for sending as an email body.
    """
    band_bg = header_bg or brand_navy
    header_content: str
    if header_html:
        header_content = header_html
    else:
        header_content = (
            f'<p style="margin:0; font-size:18px; font-weight:700; color:#ffffff;">'
            f"{company_name}"
            f"</p>"
        )

    return (
        "<!DOCTYPE html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        "</head>"
        '<body style="margin:0; padding:0; background-color:#f7f8fa;">'
        # Outer centering table
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
        ' style="background-color:#f7f8fa;">'
        "<tr><td align=\"center\" style=\"padding:32px 16px;\">"
        # Inner 600px content card
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0"'
        ' style="max-width:600px; width:100%; background-color:#ffffff;'
        ' border-radius:8px; overflow:hidden;'
        ' box-shadow:0 2px 8px rgba(16,24,40,0.08);">'
        # Header band
        "<tr>"
        f'<td style="background-color:{band_bg}; padding:20px 28px;'
        ' border-bottom:1px solid #edf0f3;">'
        f"{header_content}"
        "</td>"
        "</tr>"
        # Body
        "<tr>"
        f'<td style="padding:28px 28px 24px; font-family:{font_family};'
        f" font-size:15px; line-height:1.6; color:#1a202c;\">"
        f"{body_html}"
        "</td>"
        "</tr>"
        # Footer
        "<tr>"
        f'<td style="border-top:3px solid {brand_red}; padding:16px 28px;'
        f" font-family:{font_family}; font-size:12px; color:#667085;\">"
        f"{company_name} &mdash; Licensed &amp; Insured Roofing Contractor"
        "</td>"
        "</tr>"
        "</table>"
        "</td></tr>"
        "</table>"
        "</body>"
        "</html>"
    )
