#!/usr/bin/env python3
"""Knowify CLI OAuth login — "log in with your Knowify creds" from the terminal.

No passwords are stored. Uses the standard OAuth 2.0 Authorization-Code + PKCE
flow against Knowify's authorization server (developers-v2.knowify.com), with
Dynamic Client Registration so no pre-provisioned app is needed. You log in once
in the browser; we keep only the resulting access/refresh TOKENS (read-only
scopes) in ~/.config/knowify/tokens.json (chmod 600, OUTSIDE the git repo).

    python scripts/knowify/knowify_oauth.py            # login (opens browser)
    python scripts/knowify/knowify_oauth.py --status   # show token state

Then scripts/knowify/knowify_pull.py can pull data with the stored token.
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

AS = "https://developers-v2.knowify.com"
REG = AS + "/oauth/reg"
AUTH = AS + "/oauth/auth"
TOKEN = AS + "/oauth/token"
UA = "perkins-knowify-importer/1.0"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"

# READ-ONLY scopes only — this tool never requests *:write.
SCOPES = "openid profile offline_access " + " ".join(
    f"{e}:read" for e in (
        "invoices", "clients", "projects", "bills", "payments", "milestones",
        "items", "purchase-items", "purchases", "time", "time-entries",
        "contracts", "documents", "vendors", "submittals", "assets",
        "list-items", "resources", "departments", "service-tickets", "tickets",
        "allocations", "billables", "aia-invoices", "users",
    )
)

CFG_DIR = os.path.expanduser("~/.config/knowify")
TOKENS = os.path.join(CFG_DIR, "tokens.json")


def _post(url, data, form=True):
    body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
    ct = "application/x-www-form-urlencoded" if form else "application/json"
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": ct, "Accept": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _save(obj):
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(TOKENS, "w") as f:
        json.dump(obj, f, indent=1)
    os.chmod(TOKENS, 0o600)


def _pkce():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _register_client():
    """Dynamic Client Registration → returns client_id (+ secret if issued)."""
    reg = _post(REG, {
        "client_name": "Perkins Knowify Importer (read-only)",
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",  # public CLI client (PKCE)
        "scope": SCOPES,
    }, form=False)
    return reg


class _Handler(http.server.BaseHTTPRequestHandler):
    code = None
    state = None

    def do_GET(self):
        q = urllib.parse.urlparse(self.path).query
        params = dict(urllib.parse.parse_qsl(q))
        _Handler.code = params.get("code")
        _Handler.state = params.get("state")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h2>Knowify login complete.</h2>You can close this tab and return to the terminal.")

    def log_message(self, *a):
        pass


def login():
    client = _register_client()
    client_id = client["client_id"]
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(16)
    auth_url = AUTH + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT_URI,
        "scope": SCOPES, "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
    })

    srv = http.server.HTTPServer(("localhost", REDIRECT_PORT), _Handler)
    threading.Thread(target=srv.handle_request, daemon=True).start()

    print("\nOpen this URL in your browser and log in with your Knowify credentials:\n")
    print("  " + auth_url + "\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass
    print("Waiting for the browser redirect on localhost:%d ..." % REDIRECT_PORT)

    import time
    for _ in range(300):
        if _Handler.code:
            break
        time.sleep(1)
    if not _Handler.code:
        sys.exit("Timed out waiting for login.")
    if _Handler.state != state:
        sys.exit("State mismatch — aborting (possible CSRF).")

    tok = _post(TOKEN, {
        "grant_type": "authorization_code", "code": _Handler.code,
        "redirect_uri": REDIRECT_URI, "client_id": client_id, "code_verifier": verifier,
    })
    _save({"client_id": client_id, "client_secret": client.get("client_secret"),
           "access_token": tok["access_token"], "refresh_token": tok.get("refresh_token"),
           "expires_in": tok.get("expires_in"), "scope": tok.get("scope", SCOPES)})
    print(f"\n✓ Logged in. Read-only token stored at {TOKENS} (chmod 600).")
    print("  Now run:  python scripts/knowify/knowify_pull.py")


def _selfcheck():
    v, c = _pkce()
    assert c == base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    print("pkce ok")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    elif "--status" in sys.argv:
        print(json.dumps({k: ("<set>" if k in ("access_token", "refresh_token", "client_secret") and v else v)
                          for k, v in (json.load(open(TOKENS)).items() if os.path.exists(TOKENS) else {})}, indent=1)
              if os.path.exists(TOKENS) else "no token yet — run without --status to log in")
    else:
        login()
