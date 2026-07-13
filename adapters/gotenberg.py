"""Gotenberg PDF rendering adapter (I/O — coverage-omitted).

Calls the internal Gotenberg Cloud Run service to convert HTML → PDF.
Auth: OIDC token fetched from the GCP metadata server (Cloud Run identity).

Uses email.mime for correct multipart/form-data construction — avoids the
byte-splice/string-concat antipattern that corrupts binary PDF attachment bytes.

Public API:
    html_to_pdf(html: str, attachment_pdf_bytes: bytes | None = None) -> bytes
"""
from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.request
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from typing import Optional

GOTENBERG_URL = os.getenv("GOTENBERG_URL", "")

# Timeout for HTML → PDF conversion. Large proposals with many line items
# may require a couple of seconds of Chromium render time; 60s is generous.
_CONVERT_TIMEOUT_S = int(os.getenv("GOTENBERG_TIMEOUT", "60"))

# Number of retries on transient 5xx / network error (not on 4xx — those are
# caller bugs and retrying won't help).
_MAX_RETRIES = 2


def _oidc_token(audience: str) -> str:
    """Fetch an OIDC identity token from the GCP metadata server.

    Only works inside a Cloud Run container. Tests mock this function.
    """
    url = (
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts"
        f"/default/identity?audience={audience}"
    )
    req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.read().decode()
    except Exception:
        # Local/dev fallback for one-off scripts and smoke probes. Cloud Run uses the
        # metadata-server path above.
        try:
            return subprocess.check_output(
                ["gcloud", "auth", "print-identity-token", f"--audiences={audience}"],
                timeout=15,
                stderr=subprocess.DEVNULL,
            ).decode().strip()
        except Exception:
            return subprocess.check_output(
                ["gcloud", "auth", "print-identity-token"],
                timeout=15,
                stderr=subprocess.DEVNULL,
            ).decode().strip()


def _build_multipart(
    html: str,
    attachment_pdf_bytes: Optional[bytes],
) -> tuple[bytes, str]:
    """Build a multipart/form-data body for Gotenberg HTML conversion.

    Returns (body_bytes, content_type_header_value).

    Uses email.mime for correct RFC-2046 boundary handling — never string-concat
    binary data because PDF bytes can contain byte sequences that break a naive
    boundary delimiter search.
    """
    msg = MIMEMultipart("form-data")

    html_part = MIMEBase("text", "html")
    html_part.add_header(
        "Content-Disposition",
        'form-data; name="files"; filename="index.html"',
    )
    html_part.set_payload(html.encode("utf-8"))
    msg.attach(html_part)

    if attachment_pdf_bytes is not None:
        pdf_part = MIMEBase("application", "pdf")
        pdf_part.add_header(
            "Content-Disposition",
            'form-data; name="files"; filename="attachment.pdf"',
        )
        pdf_part.set_payload(attachment_pdf_bytes)
        msg.attach(pdf_part)

    raw = msg.as_bytes()
    # email.mime serialises headers with \n (not \r\n).
    # The header block ends at the first \n\n; everything after is the body.
    sep = b"\n\n"
    idx = raw.index(sep)
    body = raw[idx + len(sep):]

    # msg["Content-Type"] returns only "multipart/form-data" without the boundary
    # parameter (Python email.mime limitation). The full Content-Type including the
    # boundary= parameter is only available in the serialised header block, where it
    # may be folded across two lines (RFC 2822 header folding).
    # Unfold continuation lines (lines starting with whitespace) then extract.
    header_block = raw[:idx].decode("ascii", errors="replace")
    # Unfold: join continuation lines (starting with space/tab) to the previous line
    unfolded = header_block.replace("\n ", " ").replace("\n\t", " ")
    content_type = "multipart/form-data"
    for line in unfolded.splitlines():
        if line.lower().startswith("content-type:"):
            content_type = line.split(":", 1)[1].strip()
            break

    return body, content_type


def html_to_pdf(
    html: str,
    attachment_pdf_bytes: Optional[bytes] = None,
) -> bytes:
    """Render *html* to PDF via Gotenberg.

    Optionally appends *attachment_pdf_bytes* (e.g. a T&C PDF) as an
    additional file in the multipart form; Gotenberg merges it with the
    rendered HTML PDF automatically when multiple files are provided.

    Args:
        html: Full HTML document to render.
        attachment_pdf_bytes: Raw bytes of a PDF to merge after the HTML render,
            or None if no attachment is needed.

    Returns:
        Raw PDF bytes (starts with b'%PDF').

    Raises:
        RuntimeError: If GOTENBERG_URL is not set, or Gotenberg returns a
            non-2xx response after all retries are exhausted.
    """
    url = GOTENBERG_URL.rstrip("/")
    if not url:
        raise RuntimeError(
            "GOTENBERG_URL environment variable is not set. "
            "Set it to the internal Cloud Run URL for the Gotenberg service."
        )

    token = _oidc_token(url)
    body, content_type = _build_multipart(html, attachment_pdf_bytes)
    endpoint = f"{url}/forms/chromium/convert/html"

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": content_type,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_CONVERT_TIMEOUT_S) as r:
                pdf_bytes = r.read()
            if not pdf_bytes.startswith(b"%PDF"):
                raise RuntimeError(
                    f"Gotenberg response does not look like a PDF "
                    f"(first bytes: {pdf_bytes[:8]!r})"
                )
            return pdf_bytes
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                raw = exc.read().decode(errors="replace")
                raise RuntimeError(
                    f"Gotenberg client error {exc.code}: {raw}"
                ) from exc
            last_exc = exc
        except OSError as exc:
            last_exc = exc

    raise RuntimeError(
        f"Gotenberg request failed after {_MAX_RETRIES + 1} attempts: {last_exc}"
    ) from last_exc
