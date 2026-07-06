#!/usr/bin/env python
"""One-time: obtain a YouTube reply refresh token (scope youtube.force-ssl).

Run locally and sign in as the Perkins YouTube channel owner. Prints a refresh token to store
as the ``youtube-oauth-refresh-token`` secret (see docs/YOUTUBE_REPLY_OAUTH.md). Reuses the
existing OAuth client. Requires ``http://localhost:8765/`` as an authorized redirect URI on it.

    export OAUTH_CLIENT_ID=...  OAUTH_CLIENT_SECRET=...
    .venv/bin/python scripts/youtube_oauth_setup.py
"""
import http.server
import json
import os
import urllib.parse
import urllib.request
import webbrowser

SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
REDIRECT = "http://localhost:8765/"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def main() -> None:
    client_id = os.environ["OAUTH_CLIENT_ID"]
    client_secret = os.environ["OAUTH_CLIENT_SECRET"]

    auth_params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    })

    captured: dict[str, str | None] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            query = urllib.parse.urlparse(self.path).query
            captured["code"] = urllib.parse.parse_qs(query).get("code", [None])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Authorized. You can close this tab and return to the terminal.")

        def log_message(self, *args):  # silence the default request logging
            pass

    print("Opening a browser for consent — sign in as the Perkins YouTube channel owner...")
    webbrowser.open(f"{AUTH_URL}?{auth_params}")
    server = http.server.HTTPServer(("localhost", 8765), Handler)
    server.handle_request()  # serve exactly one redirect

    code = captured.get("code")
    if not code:
        raise SystemExit("No authorization code returned — consent was cancelled?")

    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — fixed Google token URL
        tok = json.loads(resp.read().decode())

    refresh = tok.get("refresh_token")
    if not refresh:
        raise SystemExit(f"No refresh_token in response (already consented? revoke + retry): {tok}")

    print("\n=== REFRESH TOKEN — store as the youtube-oauth-refresh-token secret ===\n")
    print(refresh)
    print("\nNext: see docs/YOUTUBE_REPLY_OAUTH.md step 3 (create the secret + wire into deploy).")


if __name__ == "__main__":
    main()
